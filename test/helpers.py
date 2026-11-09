"""Checks that the host image tests and the installer tests share."""

import json

EFI_SYSTEM = "c12a7328-f81f-11d2-ba4b-00a0c93ec93b"
LINUX_ROOT_X86_64 = "4f68bce3-e8cd-4db1-96e7-fbcaf984b709"
GIB = 2**30

LSBLK_COLUMNS = "NAME,SIZE,FSTYPE,PARTLABEL,PARTTYPE,START,MOUNTPOINTS"

# The two places in the ESP where the shim is. The firmware starts the first
# one on a new host, and the boot entry that the shim makes uses the second.
SHIM_PATHS = ("/EFI/BOOT/BOOTX64.EFI", "/EFI/debian/shimx64.efi")
CA_2011 = "Microsoft Corporation UEFI CA 2011"
CA_2023 = "Microsoft UEFI CA 2023"


def expected_shim_cas(shim_remove_signature):
    """The CAs that signed the shim in the ESP, for a value of the build
    setting SHIM_REMOVE_SIGNATURE."""
    return {"none": sorted([CA_2011, CA_2023]), "2011": [CA_2023], "2023": [CA_2011]}[shim_remove_signature]


def signature_cas(listing):
    """Return the CA of each signature, from the output of sbverify --list.
    The issuers of a signature follow its "signature N" line."""
    cas = []
    in_issuers = False
    for line in listing.splitlines():
        if line.startswith("signature "):
            in_issuers = False
        elif "image signature issuers:" in line:
            in_issuers = True
        elif "image signature certificates:" in line:
            in_issuers = False
        elif in_issuers and "CN=" in line:
            cas.append(line.split("CN=")[-1].strip())
    return sorted(cas)


def lsblk_children(lsblk_json):
    """Return the partitions from the output of lsblk -Jb for one disk."""
    return json.loads(lsblk_json)["blockdevices"][0].get("children", [])


def partitions(machine):
    return lsblk_children(machine.check(f"lsblk -Jb -o {LSBLK_COLUMNS} /dev/vda").stdout)


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


def assert_image_partitions(children):
    """The two partitions that the image has before the first boot."""
    esp, root = children
    assert esp["parttype"].lower() == EFI_SYSTEM
    assert 2 * GIB <= esp["size"] < 2.2 * GIB
    assert root["parttype"].lower() == LINUX_ROOT_X86_64
    assert 25 * GIB < root["size"] < 32 * GIB


def assert_first_boot_layout(children):
    """The four partitions after the first boot on a disk with free space."""
    assert len(children) == 4, children
    assert_image_partitions(children[:2])
    swap, vmdata = children[2:]
    assert (swap["partlabel"], vmdata["partlabel"]) == ("swap", "vmdata")
    assert swap["size"] == 4 * GIB
    assert vmdata["fstype"] == "xfs"
    assert vmdata["size"] > 55 * GIB
    # systemd-repart made these two on the first boot.
    assert swap["start"] % 8 == 0 and vmdata["start"] % 8 == 0
