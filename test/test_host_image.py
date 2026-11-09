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

from helpers import (EFI_SYSTEM, LINUX_ROOT_X86_64, SHIM_PATHS, assert_first_boot_layout, expected_shim_cas,
                     failed_units, partition, partitions, signature_cas, swap_is_active)
from secureboot import esp_shim_cas, make_disk_with_unsigned_file
from vm import HAS_KVM


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


def test_2_04_shim_signatures_in_the_esp(host_image, settings, work_dir):
    found = esp_shim_cas(host_image, work_dir, "host")
    expected = expected_shim_cas(settings.shim_remove_signature)
    assert found == {path: expected for path in SHIM_PATHS}, (
        f"SHIM_REMOVE_SIGNATURE={settings.shim_remove_signature}, so the CAs of the signatures must be {expected}")


# Step 3: the first boot

def test_3_01_serial_console_shows_login(vm_a):
    assert "login:" in vm_a.serial_text(), (
        "no login prompt on the serial port. Build the image with "
        "KERNEL_CMDLINE_EXTRA=console=tty0 console=ttyS0,115200")


def test_3_03_no_failed_units(vm_a):
    assert failed_units(vm_a) == []


# Step 4: the system

def test_4_01_partition_layout(vm_a):
    assert_first_boot_layout(partitions(vm_a))


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


@pytest.mark.parametrize("unit", ["ssh", "chrony", "systemd-networkd", "systemd-resolved", "quarry-login-banner"])
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


@pytest.mark.parametrize("timer", ["apt-daily.timer", "apt-daily-upgrade.timer"])
def test_4_16_update_timer_active(vm_a, timer):
    assert vm_a.check(f"systemctl is-enabled {timer}").stdout.strip() == "enabled"
    assert vm_a.check(f"systemctl is-active {timer}").stdout.strip() == "active"


def test_4_17_updates_are_on_and_reboot_is_off(vm_a):
    config = vm_a.check("apt-config dump").stdout
    assert 'APT::Periodic::Update-Package-Lists "1";' in config
    assert 'APT::Periodic::Unattended-Upgrade "1";' in config
    # Debian ships the line commented out, and the default is no reboot. So
    # the check is that nothing turns the reboot on.
    assert not re.search(r'^Unattended-Upgrade::Automatic-Reboot "(true|1|yes)";', config, re.MULTILINE)


def test_4_18_login_banner_shows_addresses_and_ssh_command(vm_a, settings):
    assert vm_a.check("systemctl is-active quarry-login-banner").stdout.strip() == "active"
    banner = vm_a.check("cat /run/issue.d/50-quarry-network.issue").stdout
    link = vm_a.check("ip -o route show default").stdout.split()[4]
    address = vm_a.check(f"ip -o -4 addr show dev {link} scope global").stdout.split()[3]
    assert f"{link} (up): " in banner
    assert address in banner
    assert f"ssh -A {settings.admin_user}@{settings.host_name}.local" in banner
    assert f"ssh -A {settings.admin_user}@{address.split('/')[0]}" in banner


def test_4_19_banner_follows_an_address_change(vm_a):
    # The service sees the change from the kernel, so the banner must change
    # within a few seconds. The address is from the documentation range
    # (RFC 5737), so it never reaches a real network.
    link = vm_a.check("ip -o route show default").stdout.split()[4]
    vm_a.sudo(f"ip addr add 192.0.2.77/32 dev {link}")
    try:
        deadline = time.monotonic() + 20
        banner = ""
        while time.monotonic() < deadline and "192.0.2.77" not in banner:
            time.sleep(1)
            banner = vm_a.check("cat /run/issue.d/50-quarry-network.issue").stdout
        assert "192.0.2.77/32" in banner, banner
    finally:
        vm_a.sudo(f"ip addr del 192.0.2.77/32 dev {link}")


def test_4_20_mdns_is_on(vm_a):
    # The slirp network of the test cannot carry multicast, so the test checks
    # the settings and the listening socket, not an answer to a query.
    link = vm_a.check("ip -o route show default").stdout.split()[4]
    assert vm_a.check(f"resolvectl mdns {link}").stdout.strip().endswith(": yes")
    assert ":5353" in vm_a.check("ss -uln").stdout


def shim_cas_on_the_host(machine):
    return {path: signature_cas(machine.check_sudo(f"sbverify --list /boot/efi{path}").stdout)
            for path in SHIM_PATHS}


def put_back_the_package_shim(machine):
    """What the shim package does at each update: copy the file with both
    signatures into the ESP."""
    for path in SHIM_PATHS:
        machine.check_sudo(f"cp /usr/lib/shim/shimx64.efi.signed /boot/efi{path}")


def test_4_21_shim_signatures_on_the_running_host(vm_a, settings):
    expected = expected_shim_cas(settings.shim_remove_signature)
    assert shim_cas_on_the_host(vm_a) == {path: expected for path in SHIM_PATHS}


def test_4_22_script_removes_the_signature_again(vm_a, settings):
    put_back_the_package_shim(vm_a)
    vm_a.check_sudo("quarry-shim-signature")
    expected = expected_shim_cas(settings.shim_remove_signature)
    assert shim_cas_on_the_host(vm_a) == {path: expected for path in SHIM_PATHS}


def test_4_23_apt_hook_runs_the_script_after_a_package_change(vm_a, settings):
    # The reinstall may or may not copy the shim to the ESP. The hook runs
    # after it in both cases, so the result is the same.
    put_back_the_package_shim(vm_a)
    vm_a.check_sudo("env DEBIAN_FRONTEND=noninteractive apt-get update -q", timeout=180)
    vm_a.check_sudo("env DEBIAN_FRONTEND=noninteractive apt-get install --reinstall -y -q shim-signed",
                    timeout=300)
    expected = expected_shim_cas(settings.shim_remove_signature)
    assert shim_cas_on_the_host(vm_a) == {path: expected for path in SHIM_PATHS}


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


def test_5_02a_sudo_does_not_cache_the_agent_check(vm_a, sudo_mode_agent):
    # Both sudo commands run under one shell, so they share the record of the
    # parent process. With the default 15 minute timestamp, the second command
    # would pass without the agent. Without a cache, it must fail.
    result = vm_a.run("sudo true && env -u SSH_AUTH_SOCK sudo true", forward_agent=True)
    assert result.returncode != 0, "sudo used a cached check after the agent was gone"
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


# Step 10: Secure Boot. The suite boots every machine with the Secure Boot
# firmware, so all the tests above already show that the signed chain boots.
# The firmware trusts the Microsoft CA, the shim trusts the Debian CA, and
# Debian signs systemd-boot and the kernel. The initrd and the kernel command
# line are not verified (see host-baseline.md).

def test_10_01_secure_boot_is_enforced(vm_a):
    assert "SecureBoot enabled" in vm_a.check("mokutil --sb-state").stdout


def test_10_02_kernel_lockdown_is_on(vm_a):
    assert re.search(r"\[(integrity|confidentiality)\]", vm_a.check("cat /sys/kernel/security/lockdown").stdout)


def test_10_03_kernel_package_is_signed(vm_a):
    # Debian names the unsigned kernel packages linux-image-*-unsigned.
    vm_a.check("dpkg -s linux-image-$(uname -r)")
    assert vm_a.run("dpkg -l 'linux-image-*-unsigned' | grep -q '^ii'").returncode != 0


@pytest.mark.parametrize("installed, packaged", [
    ("/boot/efi/EFI/BOOT/BOOTX64.EFI", "/usr/lib/shim/shimx64.efi.signed"),
    ("/boot/efi/EFI/debian/shimx64.efi", "/usr/lib/shim/shimx64.efi.signed"),
    ("/boot/efi/EFI/systemd/systemd-bootx64.efi", "/usr/lib/systemd/boot/efi/systemd-bootx64.efi.signed"),
])
def test_10_04_esp_has_the_signed_files(vm_a, installed, packaged):
    vm_a.check_sudo(f"cmp {installed} {packaged}")


def test_10_05_boot_entry_points_to_shim(vm_a):
    # The shim makes this entry (BOOTX64.CSV). A new firmware has no entry, and
    # the first boot starts the shim at the removable-media path.
    command = ("for f in /sys/firmware/efi/efivars/Boot[0-9A-F][0-9A-F][0-9A-F][0-9A-F]-*; do "
               "tr -d '\\000' < \"$f\" | grep -aqi shimx64.efi && echo \"$f\"; done; true")
    assert vm_a.check(command).stdout.strip(), "no boot entry in the firmware variables points to the shim"


# A file in the ESP without its signature must stop the boot. A boot that
# stops cannot be seen as a login, so the tests wait and then look at the
# serial log. Without KVM, a boot is much slower, so the wait is longer.
REFUSE_WAIT = 120 if HAS_KVM else 900


def assert_boot_refused(machine, shown=(), not_shown=()):
    """Start the machine and check that the boot stops. shown: texts that must
    be on the serial console: the refusal, and the proof that the boot got that
    far. not_shown: texts of a program that must not run."""
    machine.start(wait=False)
    try:
        deadline = time.monotonic() + REFUSE_WAIT
        seen_at = None
        while time.monotonic() < deadline:
            assert machine.proc.poll() is None, f"QEMU stopped. See {machine.qemu_log}"
            assert machine.run("true", timeout=10).returncode != 0, "the machine booted and accepted a login"
            if shown and all(text in machine.serial_text() for text in shown):
                seen_at = seen_at or time.monotonic()
                if time.monotonic() - seen_at > 15:
                    break
            time.sleep(5)
        serial = machine.serial_text()
    finally:
        machine.stop()
    tail = serial[-2000:]
    assert "Linux version" not in serial, f"the kernel started:\n{tail}"
    for text in shown:
        assert text in serial, f"'{text}' is not on the serial console:\n{tail}"
    for text in not_shown:
        assert text not in serial, f"'{text}' is on the serial console:\n{tail}"


@pytest.fixture(scope="module")
def unsigned_kernel_disk(host_image, work_dir):
    disk = work_dir / "unsigned-kernel.qcow2"
    make_disk_with_unsigned_file(host_image, disk, work_dir)
    return disk


def test_10_10_unsigned_kernel_is_refused(make_vm, unsigned_kernel_disk):
    # systemd-boot runs and shows its menu. Then it cannot load the kernel.
    assert_boot_refused(make_vm("refused-kernel", None, disk=unsigned_kernel_disk),
                        shown=("Debian GNU/Linux", "Security violation"))


def test_10_11_unsigned_kernel_boots_without_secure_boot(make_vm, unsigned_kernel_disk):
    # The control for test 10.10: the disk is fine, and only Secure Boot
    # refuses it.
    with make_vm("control-kernel", None, disk=unsigned_kernel_disk, secure_boot=False).running() as machine:
        machine.check("true")


def test_10_12_unsigned_systemd_boot_is_refused(make_vm, host_image, work_dir):
    disk = work_dir / "unsigned-systemd-boot.qcow2"
    make_disk_with_unsigned_file(host_image, disk, work_dir, "/EFI/systemd/systemd-bootx64.efi")
    # The shim shows an error and waits for a key. The menu of systemd-boot
    # never appears.
    assert_boot_refused(make_vm("refused-systemd-boot", None, disk=disk),
                        shown=("Verification failed",), not_shown=("Debian GNU/Linux",))
