"""Tests of the USB installer (image/installer.yaml and quarry-install).

The installer boots in QEMU from a copy of installer.img, and the tests type
at its serial console. The test names follow the check numbers of the old
manual page, for example test_3_06 was check 3.6. The tests depend on their
order: test_3_07 writes the image to the target disk, and the later tests use
that disk.
"""

import pytest

import console
from helpers import (assert_first_boot_layout, assert_image_partitions, failed_units, lsblk_children,
                    partitions, swap_is_active)

ERASE_PROMPT = "to erase the whole disk: "
TARGET_NAME = "virtio-TARGETDISK0001"


def by_serial(machine, serial):
    return machine.check(f"readlink -f /dev/disk/by-id/virtio-{serial}").output.strip()


# The installer with three disks: the USB stick, an empty target disk, and a
# disk that is too small for the image.

@pytest.fixture(scope="module")
def disks(installer_image, work_dir):
    return console.make_disks(work_dir, "installer", installer_image, "100G", small_size="10G")


@pytest.fixture(scope="module")
def installer(make_console, disks):
    with make_console("installer", disks).running() as machine:
        yield machine


@pytest.fixture(scope="module")
def usb(installer):
    return by_serial(installer, "USBSTICK")


@pytest.fixture(scope="module")
def target(installer):
    return by_serial(installer, "TARGETDISK0001")


@pytest.fixture(scope="module")
def small(installer):
    return by_serial(installer, "SMALLDISK0001")


@pytest.fixture(scope="module")
def installed(installer, target):
    """Write the image to the target disk. The first test that needs the
    result makes the write, and the write is not a check by itself."""
    return installer.run(f"quarry-install {target}", answers=[(ERASE_PROMPT, TARGET_NAME)],
                         timeout=console.INSTALL_TIMEOUT)


# Step 3: the installer

def test_3_00_installer_carries_the_host_image(installer):
    files = installer.check("ls /usr/share/quarry").output.split()
    assert "host.img.zst" in files and "host.bmap" in files, (
        f"{files}. Build the installer again with image/build.sh")


def test_3_01_banner_lists_the_disks(installer):
    log = installer.log_text()
    assert "claude-quarry installer" in log
    for serial in ("USBSTICK", "TARGETDISK0001", "SMALLDISK0001"):
        assert serial in log, f"{serial} is not in the banner. See {installer.log_path}"


def test_3_02_usage(installer):
    result = installer.run("quarry-install")
    assert result.status == 1
    assert "usage: quarry-install" in result.output


def test_3_03_refuses_a_partition(installer, usb):
    result = installer.run(f"quarry-install {usb}1")
    assert result.status != 0
    assert "not a whole disk" in result.output


def test_3_04_refuses_a_disk_with_mounted_file_systems(installer, usb):
    result = installer.run(f"quarry-install {usb}")
    assert result.status != 0
    assert "mounted file systems" in result.output


def test_3_05_refuses_a_disk_that_is_too_small(installer, small):
    result = installer.run(f"quarry-install {small}")
    assert result.status != 0
    assert "and the image has" in result.output


def test_3_06_wrong_name_writes_nothing(installer, target):
    result = installer.run(f"quarry-install {target}", answers=[(ERASE_PROMPT, "wrong")])
    assert result.status != 0
    assert TARGET_NAME in result.output
    assert "Nothing was written" in result.output
    assert installer.check(f"lsblk -nro NAME {target}").output.split() == [target.removeprefix("/dev/")]


def test_3_07_writes_the_image(installed):
    assert installed.status == 0, installed.output
    assert "Done." in installed.output


def test_3_08_target_has_the_image_partitions(installer, target, installed):
    out = installer.check(f"lsblk -Jb -o NAME,SIZE,FSTYPE,PARTLABEL,PARTTYPE,START,MOUNTPOINTS {target}").output
    assert_image_partitions(lsblk_children(out))


# Step 4: boot the installed disk. The installer stops first, because two
# machines cannot open one disk file.

@pytest.fixture(scope="module")
def installed_vm(installer, installed, make_vm, disks):
    installer.stop()
    with make_vm("installed", None, disk=disks[1].path).running() as machine:
        yield machine


def test_4_01_login_works(installed_vm):
    installed_vm.check("true")


def test_4_02_first_boot_layout(installed_vm):
    assert_first_boot_layout(partitions(installed_vm))


def test_4_03_swap_active(installed_vm):
    assert swap_is_active(installed_vm)


def test_4_04_no_failed_units(installed_vm):
    assert failed_units(installed_vm) == []


# Step 5: a disk without a name in /dev/disk/by-id

@pytest.fixture(scope="module")
def installer_no_name(installer_image, work_dir, make_console):
    disks = console.make_disks(work_dir, "installer-no-name", installer_image, "100G", target_serial=None)
    with make_console("installer-no-name", disks).running() as machine:
        yield machine


@pytest.fixture(scope="module")
def target_no_name(installer_no_name):
    usb = by_serial(installer_no_name, "USBSTICK")
    # QEMU adds a CD-ROM drive (sr0), so list only the devices of type disk.
    lines = installer_no_name.check("lsblk -dnro NAME,TYPE").output.splitlines()
    others = [f"/dev/{name}" for name, kind in (line.split() for line in lines)
              if kind == "disk" and f"/dev/{name}" != usb]
    assert len(others) == 1, others
    return others[0]


def test_5_01_asks_for_the_device_path(installer_no_name, target_no_name):
    result = installer_no_name.run(f"quarry-install {target_no_name}", answers=[(ERASE_PROMPT, "wrong")])
    assert result.status != 0
    assert "has no name in /dev/disk/by-id" in result.output
    assert f"Type the device path {target_no_name}" in result.output


def test_5_02_device_path_writes_the_image(installer_no_name, target_no_name):
    result = installer_no_name.run(f"quarry-install {target_no_name}", answers=[(ERASE_PROMPT, target_no_name)],
                                   timeout=console.INSTALL_TIMEOUT)
    assert result.status == 0, result.output
    assert "Done." in result.output
