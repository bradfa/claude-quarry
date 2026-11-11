"""Tests of the guest setup on the host image: libvirt, the quarry network, and
later the quarry-guest command and the firewall.

The tests boot the host image in QEMU, as the other tests do. Run only this
file with:

    BUILD_CONF=image/build/test.conf test/.venv/bin/python -m pytest \
        test/test_guest_setup.py -v --junitxml=image/build/junit-guest-setup.xml
"""

import re
import shlex
import time

import pytest

from helpers import failed_units

PACKAGES = ("libvirt-daemon-system", "libvirt-clients", "qemu-system-x86", "qemu-utils", "ovmf", "nftables")
# virtlockd.service is in libvirt-daemon-lock, which the image does not install.
LIBVIRT_UNITS = ("libvirtd.service", "virtlogd.service", "libvirt-guests.service")
VIRSH = "virsh -c qemu:///system"
NETWORK = "quarry"
BRIDGE = "virbr-quarry"
IMAGES_DIR = "/var/lib/libvirt/images"
GUEST_ADDRESS = "10.250.0.10"

# The test host gets the guest image as a second, read-only disk, and
# quarry-guest uses it as the base image of the guest. Virtio drives get their
# names in the order of the command line, so the disk of the host stays vda.
# A disk that is made with -device gets a lower PCI slot, and then the firmware
# boots the guest image instead of the host.
BASE_DISK = "/dev/vdb"

# The login goes from the test host to the guest, with the agent of the test.
# The guest is a new machine each time, so its host key is not checked.
SSH = ("ssh -o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "
       "-o LogLevel=ERROR -o ConnectTimeout=10")
# The guest runs inside a virtual machine that runs in a virtual machine.
GUEST_BOOT_TIMEOUT = 900


@pytest.fixture(scope="module")
def host(make_vm, host_image, guest_image):
    machine = make_vm("setup-host", host_image, resize="100G", memory=4096)
    machine.extra_args = ["-drive", f"if=virtio,format=raw,readonly=on,file={guest_image}"]
    with machine.running():
        yield machine


def wait_for_output(machine, command, text, timeout=120):
    """Run a command as root until its output has the text. Return the output.
    Libvirt starts the autostart network a few seconds after the boot."""
    deadline = time.monotonic() + timeout
    while True:
        result = machine.sudo(command)
        if result.returncode == 0 and text in result.stdout:
            return result.stdout
        if time.monotonic() > deadline:
            raise AssertionError(f"'{command}' did not show '{text}' in {timeout} s\n"
                                 f"return code: {result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}")
        time.sleep(3)


def guest_run(machine, settings, user, command, timeout=60):
    """Run a command in the guest. Return the finished process."""
    return machine.run(f"{SSH} {user}@{settings.guest_name} {shlex.quote(command)}",
                       forward_agent=True, timeout=timeout)


def guest_check(machine, settings, user, command, timeout=60):
    result = guest_run(machine, settings, user, command, timeout)
    assert result.returncode == 0, (
        f"'{command}' in the guest returned {result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}")
    return result


def wait_for_guest(machine, settings, timeout=GUEST_BOOT_TIMEOUT):
    """Wait until a login to the guest works."""
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = guest_run(machine, settings, settings.admin_user, "true", timeout=30)
        if last.returncode == 0:
            return
        time.sleep(5)
    state = machine.sudo(f"{VIRSH} domstate {settings.guest_name}").stdout.strip()
    raise AssertionError(f"No login to the guest in {timeout} s. The state of the guest is '{state}'. "
                         f"Last SSH error: {last.stderr if last else None}")


# Step 1: libvirt in the image

def test_1_01_packages_installed(host):
    out = host.check("dpkg-query -W -f='${db:Status-Abbrev}${Package}\\n' " + " ".join(PACKAGES)).stdout
    lines = out.splitlines()
    assert sorted(lines) == sorted(f"ii {name}" for name in PACKAGES), lines


@pytest.mark.parametrize("unit", LIBVIRT_UNITS)
def test_1_02_units_wait_for_vmdata(host, unit):
    out = host.check(f"systemctl show -p RequiresMountsFor --value {unit}").stdout
    assert "/var/lib/libvirt" in out.split(), f"{unit} does not require the mount: {out!r}"


def test_1_03_libvirt_runs_with_qemu(host):
    out = host.check_sudo(f"{VIRSH} version").stdout
    assert "Running hypervisor: QEMU" in out, out


def test_1_04_state_is_on_vmdata(host):
    # The vmdata mount hides the directories that the package made. Libvirt
    # must make its own on the XFS file system, and not on the root.
    wait_for_output(host, "ls /var/lib/libvirt", "qemu")
    target = host.check_sudo("findmnt -no TARGET -T /var/lib/libvirt/qemu").stdout.strip()
    assert target == "/var/lib/libvirt"


# Step 2: the quarry network

def test_2_01_only_the_quarry_network_exists(host):
    wait_for_output(host, f"{VIRSH} net-list --name", NETWORK)
    names = host.check_sudo(f"{VIRSH} net-list --all --name").stdout.split()
    assert names == [NETWORK], names


def test_2_02_quarry_network_starts_at_boot(host):
    out = wait_for_output(host, f"{VIRSH} net-info {NETWORK}", "Autostart")
    assert re.search(r"Active:\s+yes", out), out
    assert re.search(r"Autostart:\s+yes", out), out
    assert re.search(r"Persistent:\s+yes", out), out


def test_2_03_bridge_has_the_gateway_address(host):
    # A bridge with no guest has no carrier, so its state is not checked.
    wait_for_output(host, f"ip -4 -br addr show {BRIDGE}", "10.250.0.1/24")


def test_2_04_libvirt_uses_nftables(host):
    # Libvirt makes its own nftables table for the network. The iptables
    # backend makes the tables "filter", "nat", and "mangle" instead.
    out = host.check_sudo("nft list tables").stdout
    assert "libvirt_network" in out, out
    assert "table ip filter" not in out, out


# Step 3: the quarry-guest command. The tests depend on their order: they make
# the guest, start it, reset it, and stop it.

def test_3_01_command_and_name(host, settings):
    host.check("test -x /usr/sbin/quarry-guest")
    assert host.check("cat /etc/quarry/guest-name").stdout.strip() == settings.guest_name
    fields = host.check(f"getent hosts {settings.guest_name}").stdout.split()
    assert fields[0] == GUEST_ADDRESS, fields


def test_3_02_create(host, settings):
    host.check_sudo(f"quarry-guest create --base {BASE_DISK} --memory 1024 --vcpus 1 --data-size 2")
    status = host.check_sudo("quarry-guest status").stdout
    assert "state: shut off" in status, status
    assert "base image: /dev/" in status, status
    label = host.check_sudo(f"blkid -s LABEL -o value {IMAGES_DIR}/{settings.guest_name}-data.img").stdout
    assert label.strip() == "data"


def test_3_03_create_twice_fails(host):
    result = host.sudo(f"quarry-guest create --base {BASE_DISK}")
    assert result.returncode != 0
    assert "exists already" in result.stderr, result.stderr


def test_3_04_start_and_log_in(host, settings):
    host.check_sudo("quarry-guest start")
    wait_for_guest(host, settings)
    for user in (settings.admin_user, settings.claude_user):
        assert guest_check(host, settings, user, "id -un").stdout.strip() == user
    claude = settings.claude_user
    assert guest_check(host, settings, claude, "hostname").stdout.strip() == settings.guest_name
    assert guest_check(host, settings, claude, "findmnt -no FSTYPE /data").stdout.strip() == "ext4"
    assert GUEST_ADDRESS in guest_check(host, settings, claude, "ip -4 -br addr show").stdout


def test_3_05_reset_keeps_the_data_disk(host, settings):
    claude, admin = settings.claude_user, settings.admin_user
    key = "cat /data/etc/ssh/ssh_host_ed25519_key.pub"
    key_before = guest_check(host, settings, admin, key).stdout
    guest_check(host, settings, claude, "echo kept > /data/claude-config/marker && echo gone > ~/marker")
    host.check_sudo("quarry-guest stop", timeout=240)
    assert "state: shut off" in host.check_sudo("quarry-guest status").stdout
    host.check_sudo("quarry-guest reset")
    host.check_sudo("quarry-guest start")
    wait_for_guest(host, settings)
    assert guest_check(host, settings, claude, "cat /data/claude-config/marker").stdout.strip() == "kept"
    assert guest_run(host, settings, claude, "test -e ~/marker").returncode != 0, "the home directory was not reset"
    assert guest_check(host, settings, admin, key).stdout == key_before, "the SSH host key changed"


def test_3_06_snapshot_copies_the_data_disk(host, settings):
    host.check_sudo("quarry-guest stop", timeout=240)
    copy = host.check_sudo("quarry-guest snapshot").stdout.strip()
    data = f"{IMAGES_DIR}/{settings.guest_name}-data.img"
    assert copy.startswith(f"{IMAGES_DIR}/{settings.guest_name}-data-"), copy
    sizes = [host.check_sudo(f"stat -c %s {path}").stdout.strip() for path in (data, copy)]
    assert sizes[0] == sizes[1], sizes
    assert host.check_sudo(f"blkid -s LABEL -o value {copy}").stdout.strip() == "data"


# Last, because the other tests start the services.

def test_9_01_no_failed_units(host):
    assert failed_units(host) == []
