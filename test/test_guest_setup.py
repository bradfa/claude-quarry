"""Tests of the guest setup on the host image: libvirt, the quarry network, and
later the quarry-guest command and the firewall.

The tests boot the host image in QEMU, as the other tests do. Run only this
file with:

    BUILD_CONF=image/build/test.conf test/.venv/bin/python -m pytest \
        test/test_guest_setup.py -v --junitxml=image/build/junit-guest-setup.xml
"""

import re
import time

import pytest

from helpers import failed_units

PACKAGES = ("libvirt-daemon-system", "libvirt-clients", "qemu-system-x86", "qemu-utils", "ovmf", "nftables")
# virtlockd.service is in libvirt-daemon-lock, which the image does not install.
LIBVIRT_UNITS = ("libvirtd.service", "virtlogd.service", "libvirt-guests.service")
VIRSH = "virsh -c qemu:///system"
NETWORK = "quarry"
BRIDGE = "virbr-quarry"


@pytest.fixture(scope="module")
def host(make_vm, host_image):
    with make_vm("setup-host", host_image, resize="100G", memory=4096).running() as machine:
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


# Last, because the other tests start the services.

def test_9_01_no_failed_units(host):
    assert failed_units(host) == []
