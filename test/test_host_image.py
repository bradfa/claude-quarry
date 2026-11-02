"""Tests of the host image (image/host.yaml) in a virtual machine.

The test names follow the check numbers of the old manual page, for example
test_4_03 was check 4.3. The tests in this file depend on their order: the
reboot tests (step 6) change the state of the first machine.
"""

import json
import os
import re
import shutil
import subprocess
import time

import pytest

EFI_SYSTEM = "c12a7328-f81f-11d2-ba4b-00a0c93ec93b"
LINUX_ROOT_X86_64 = "4f68bce3-e8cd-4db1-96e7-fbcaf984b709"
GIB = 2**30


@pytest.fixture
def sudo_mode_agent(settings):
    if settings.sudo_mode != "agent":
        pytest.skip("the image uses SUDO_MODE=nopasswd")


@pytest.fixture
def sudo_mode_nopasswd(settings):
    if settings.sudo_mode != "nopasswd":
        pytest.skip("the image uses SUDO_MODE=agent")


@pytest.fixture(scope="module")
def vm_a(make_vm, host_image):
    with make_vm("host-a", host_image, resize="100G").running() as machine:
        yield machine


@pytest.fixture(scope="module")
def vm_b(make_vm, host_image):
    with make_vm("host-b", host_image, resize="100G").running() as machine:
        yield machine


@pytest.fixture(scope="module")
def vm_full(make_vm, host_image):
    """A disk with the size of the image. No room for swap and vmdata."""
    with make_vm("host-full", host_image).running() as machine:
        yield machine


def partitions(machine):
    out = machine.check("lsblk -Jb -o NAME,SIZE,FSTYPE,PARTLABEL,PARTTYPE,START,MOUNTPOINTS /dev/vda").stdout
    return json.loads(out)["blockdevices"][0].get("children", [])


def partition(machine, label):
    found = [p for p in partitions(machine) if p["partlabel"] == label]
    assert len(found) == 1, f"expected one partition with label {label}, found {found}"
    return found[0]


def failed_units(machine):
    out = machine.check("systemctl --failed --no-legend --plain").stdout
    return [line.split()[0] for line in out.splitlines() if line.strip()]


def swap_is_active(machine):
    device = "/dev/" + partition(machine, "swap")["name"]
    swaps = machine.check("cat /proc/swaps").stdout.splitlines()[1:]
    return any(line.split()[0] == device for line in swaps)


# Step 1: the image files

def test_1_02_image_files_exist(host_image):
    assert host_image.stat().st_blocks * 512 < host_image.stat().st_size, "the image is not sparse"
    assert host_image.with_suffix(".bmap").is_file()
    assert host_image.with_suffix(".img.zst").is_file()


# Step 2: the layout of the image, before the first boot

def test_2_03_image_alignment_and_types(host_image):
    sfdisk = shutil.which("sfdisk", path=os.environ["PATH"] + ":/usr/sbin:/sbin")
    if sfdisk is None:
        pytest.skip("sfdisk is not installed")
    out = subprocess.run([sfdisk, "--json", str(host_image)], capture_output=True, text=True, check=True).stdout
    table = json.loads(out)["partitiontable"]["partitions"]
    assert [p["type"].lower() for p in table] == [EFI_SYSTEM, LINUX_ROOT_X86_64]
    assert all(p["start"] % 2048 == 0 for p in table), "a partition is not aligned to 1 MiB"


# Step 3: the first boot

def test_3_01_serial_console_shows_login(vm_a):
    assert "login:" in vm_a.serial_text(), (
        "no login prompt on the serial port. Build the image with "
        "KERNEL_CMDLINE_EXTRA=console=tty0 console=ttyS0,115200")


def test_3_03_no_failed_units(vm_a):
    assert failed_units(vm_a) == []


# Step 4: the system

def test_4_01_partition_layout(vm_a):
    esp, root, swap, vmdata = partitions(vm_a)
    assert esp["parttype"].lower() == EFI_SYSTEM
    assert 2 * GIB <= esp["size"] < 2.2 * GIB
    assert root["parttype"].lower() == LINUX_ROOT_X86_64
    assert 25 * GIB < root["size"] < 32 * GIB
    assert (swap["partlabel"], vmdata["partlabel"]) == ("swap", "vmdata")
    assert swap["size"] == 4 * GIB
    assert vmdata["fstype"] == "xfs"
    assert vmdata["size"] > 55 * GIB
    # systemd-repart made these two on the first boot.
    assert swap["start"] % 8 == 0 and vmdata["start"] % 8 == 0


def test_4_02_swap_active_on_first_boot(vm_a):
    assert swap_is_active(vm_a)


def test_4_03_vmdata_mounted_at_libvirt(vm_a):
    device = "/dev/" + partition(vm_a, "vmdata")["name"]
    fields = vm_a.check("findmnt -no FSTYPE,SOURCE /var/lib/libvirt").stdout.split()
    assert fields == ["xfs", device]


def test_4_04_network_configured(vm_a):
    links = [line.split() for line in vm_a.check("networkctl list --no-legend").stdout.splitlines()]
    wired = [link for link in links if link[1].startswith("en")]
    assert len(wired) == 1, f"expected one en* link, found {links}"
    assert wired[0][3:5] == ["routable", "configured"]
    assert "10-wired.network" in vm_a.check(f"networkctl status {wired[0][1]}").stdout
    assert vm_a.check("ip route show default").stdout.strip() != ""


def test_4_05_machine_id(vm_a):
    assert re.fullmatch(r"[0-9a-f]{32}", vm_a.check("cat /etc/machine-id").stdout.strip())


def test_4_06_no_machine_id_on_cmdline(vm_a):
    assert "systemd.machine_id=" not in vm_a.check("cat /proc/cmdline").stdout


def test_4_07_boot_entry_exists(vm_a):
    out = vm_a.check_sudo("bootctl list --no-pager").stdout
    assert "linux:" in out, out


def test_4_08_chrony_has_a_source(vm_a):
    deadline = time.monotonic() + 300
    out = ""
    while time.monotonic() < deadline:
        out = vm_a.check("chronyc -n sources").stdout
        if re.search(r"^\^[*+]", out, re.MULTILINE):
            return
        time.sleep(10)
    pytest.fail(f"no synchronized NTP source after 5 minutes:\n{out}")


@pytest.mark.parametrize("unit", ["ssh", "chrony", "systemd-networkd", "systemd-resolved"])
def test_4_09_service_active(vm_a, unit):
    assert vm_a.check(f"systemctl is-active {unit}").stdout.strip() == "active"


def test_4_10_resolv_conf_link(vm_a):
    assert vm_a.check("readlink /etc/resolv.conf").stdout.strip() == "../run/systemd/resolve/stub-resolv.conf"


def test_4_11_host_name(vm_a, settings):
    assert vm_a.check("hostname").stdout.strip() == settings.host_name


def test_4_12_esp_mount_options(vm_a):
    options = vm_a.check("findmnt -no OPTIONS /boot/efi").stdout.strip().split(",")
    # The kernel shows umask=0077 as fmask and dmask.
    assert "umask=0077" in options or {"fmask=0077", "dmask=0077"} <= set(options), options


def test_4_13_random_seed_is_private(vm_a):
    mode = int(vm_a.check_sudo("stat -c %a /boot/efi/loader/random-seed").stdout.strip(), 8)
    assert mode & 0o077 == 0


def test_4_14_repart_ran(vm_a):
    assert vm_a.check("systemctl show -p Result --value systemd-repart.service").stdout.strip() == "success"


def test_4_15_ifupdown_is_gone(vm_a):
    assert vm_a.run("dpkg -s ifupdown").returncode != 0
    assert vm_a.run("systemctl cat networking.service").returncode != 0


# Step 5: access control

def test_5_00_agent_is_forwarded(vm_a, sudo_mode_agent):
    vm_a.check('test -S "$SSH_AUTH_SOCK"', forward_agent=True)


def test_5_01_sudo_with_agent(vm_a, sudo_mode_agent):
    result = vm_a.run("sudo true", forward_agent=True)
    if result.returncode != 0:
        # Show what the guest sees, and whether the -n option changes the result.
        diagnosis = vm_a.run(
            'echo "SSH_AUTH_SOCK=$SSH_AUTH_SOCK"; ls -l "$SSH_AUTH_SOCK"; ssh-add -l 2>&1; '
            "ls -l /etc/security/sudo_authorized_keys; sudo -n true 2>&1; echo \"sudo -n rc=$?\"",
            forward_agent=True)
        pytest.fail(f"sudo failed: {result.stderr}\nDiagnosis:\n{diagnosis.stdout}{diagnosis.stderr}")


def test_5_02_sudo_without_agent_fails(vm_a, sudo_mode_agent):
    result = vm_a.run("sudo true", forward_agent=False)
    assert result.returncode != 0
    assert "password" in result.stderr, result.stderr


def test_5_03_root_login_refused(vm_a):
    result = vm_a.run("true", user="root")
    assert result.returncode == 255
    assert "Permission denied" in result.stderr


def test_5_04_password_login_refused(vm_a):
    result = vm_a.run("true", options=["PubkeyAuthentication=no"])
    assert result.returncode == 255
    assert "Permission denied" in result.stderr
    assert "password" not in result.stderr


def test_5_05_root_is_locked(vm_a):
    assert vm_a.check_sudo("passwd -S root").stdout.split()[1] == "L"


# Step 6: reboot of the first machine

@pytest.fixture(scope="module")
def before_reboot(vm_a):
    return {"machine_id": vm_a.check("cat /etc/machine-id").stdout.strip(),
            "partitions": partitions(vm_a)}


@pytest.fixture(scope="module")
def after_reboot(vm_a, before_reboot):
    """The reboot is a prerequisite and not a check, so a failed reboot makes
    the tests of this step error and cannot make them pass."""
    vm_a.reboot()
    return before_reboot


def test_6_01_machine_id_is_kept(vm_a, after_reboot):
    assert vm_a.check("cat /etc/machine-id").stdout.strip() == after_reboot["machine_id"]


def test_6_02_repart_changes_nothing(vm_a, after_reboot):
    assert partitions(vm_a) == after_reboot["partitions"]


def test_6_03_no_failed_units(vm_a, after_reboot):
    assert failed_units(vm_a) == []


def test_6_04_swap_active(vm_a, after_reboot):
    assert swap_is_active(vm_a)


# Step 7: a second machine from the same image

def test_7_01_machine_ids_differ(vm_a, vm_b):
    assert vm_a.check("cat /etc/machine-id").stdout != vm_b.check("cat /etc/machine-id").stdout


def test_7_02_ssh_host_keys_differ(vm_a, vm_b):
    command = "ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub"
    assert vm_a.check(command).stdout != vm_b.check(command).stdout


# Step 8: the nopasswd image. Run the suite with SUDO_MODE=nopasswd and
# QUARRY_TEST_HOST_IMAGE set to the image built with that mode.

def test_8_01_sudo_needs_nothing(vm_a, sudo_mode_nopasswd):
    vm_a.check("sudo true", forward_agent=False)


def test_8_02_no_agent_key_file(vm_a, sudo_mode_nopasswd):
    assert vm_a.run("test -e /etc/security/sudo_authorized_keys").returncode != 0


# Step 9: a disk with no free space. The nofail option on the vmdata mount
# must let the machine boot.

def test_9_01_login_works(vm_full):
    vm_full.check("true")


def test_9_02_only_esp_and_root(vm_full):
    assert [p["parttype"].lower() for p in partitions(vm_full)] == [EFI_SYSTEM, LINUX_ROOT_X86_64]


def test_9_03_only_expected_units_fail(vm_full):
    # systemd-repart has no room to add the partitions. The recipe does not
    # handle a full disk on purpose. The vmdata mount does not fail: systemd
    # skips its job, and the unit stays inactive.
    failed = failed_units(vm_full)
    assert set(failed) <= {"systemd-repart.service", "var-lib-libvirt.mount"}, failed
    assert vm_full.run("systemctl is-active var-lib-libvirt.mount").stdout.strip() != "active"


def test_9_04_libvirt_directory_on_root(vm_full):
    assert vm_full.run("findmnt /var/lib/libvirt").returncode != 0
    vm_full.check("test -d /var/lib/libvirt")
