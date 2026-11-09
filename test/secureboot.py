"""Make a copy of a disk where one file in the ESP has lost its signature.

The Secure Boot tests need a disk that the firmware chain must refuse. The copy
is a qcow2 overlay of the image, so the tests need no root and no loop device.
The work goes through mtools (the file in the FAT file system) and qemu-io (the
changed blocks in the overlay).
"""

import json
import os
import shutil
import struct
import subprocess
from pathlib import Path

from helpers import EFI_SYSTEM, SHIM_PATHS, signature_cas
from vm import make_overlay

BLOCK = 256 * 1024
PE32_PLUS = 0x20B
# In a PE32+ file, the optional header has 112 bytes before the data
# directories. Directory number 4 is the certificate table (the signature).
DIRECTORY_START = 112
CERTIFICATE_DIRECTORY = 4


def signature_size(data: bytes) -> int:
    """Return the size of the signature of a PE file. 0 means no signature."""
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe:pe + 4] != b"PE\0\0":
        raise ValueError("not a PE file")
    optional = pe + 24
    if struct.unpack_from("<H", data, optional)[0] != PE32_PLUS:
        raise ValueError("not a PE32+ file")
    return struct.unpack_from("<II", data, optional + DIRECTORY_START + CERTIFICATE_DIRECTORY * 8)[1]


def unsign(data: bytes) -> bytes:
    """Return a PE file without its signature. The signature is at the end of
    the file, and its position is a file offset."""
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    entry = pe + 24 + DIRECTORY_START + CERTIFICATE_DIRECTORY * 8
    if signature_size(data) == 0:
        raise ValueError("the file has no signature")
    offset, size = struct.unpack_from("<II", data, entry)
    if offset + size > len(data):
        raise ValueError("the signature goes past the end of the file")
    return data[:entry] + bytes(8) + data[entry + 8:offset]


def esp_range(image: Path) -> tuple[int, int]:
    """Return the start and the size of the ESP in bytes."""
    sfdisk = shutil.which("sfdisk", path=os.environ["PATH"] + ":/usr/sbin:/sbin")
    if sfdisk is None:
        raise RuntimeError("sfdisk is not installed")
    out = subprocess.run([sfdisk, "--json", str(image)], capture_output=True, text=True, check=True).stdout
    table = json.loads(out)["partitiontable"]
    for part in table["partitions"]:
        if part["type"].lower() == EFI_SYSTEM:
            return part["start"] * table["sectorsize"], part["size"] * table["sectorsize"]
    raise RuntimeError(f"{image} has no EFI system partition")


def copy_range(source: Path, offset: int, size: int, target: Path) -> None:
    """Copy part of a file. Blocks of zeros stay holes, so the copy is small."""
    with open(source, "rb") as src, open(target, "wb") as dst:
        src.seek(offset)
        left = size
        while left:
            block = src.read(min(BLOCK, left))
            if not block:
                raise RuntimeError(f"{source} ends before the range does")
            if block.count(0) == len(block):
                dst.seek(len(block), os.SEEK_CUR)
            else:
                dst.write(block)
            left -= len(block)
        dst.truncate(size)


def mtools(tool: str, esp: Path, *args: str) -> str:
    # MTOOLS_SKIP_CHECK: the checks of mtools on the FAT geometry stop some
    # images that are fine.
    env = {**os.environ, "MTOOLS_SKIP_CHECK": "1"}
    result = subprocess.run([tool, "-i", str(esp), *args], capture_output=True, text=True, check=True, env=env)
    return result.stdout


def esp_shim_cas(image: Path, work_dir: Path, name: str) -> dict[str, list[str]]:
    """Return the CAs that signed each shim file in the ESP of an image."""
    start, size = esp_range(image)
    esp = work_dir / f"{name}-esp.img"
    shim = work_dir / f"{name}-shim.efi"
    copy_range(image, start, size, esp)
    try:
        found = {}
        for path in SHIM_PATHS:
            mtools("mcopy", esp, "-n", f"::{path}", str(shim))
            listing = subprocess.run(["sbverify", "--list", str(shim)], capture_output=True, text=True,
                                     check=True).stdout
            found[path] = signature_cas(listing)
        return found
    finally:
        esp.unlink(missing_ok=True)
        shim.unlink(missing_ok=True)


def kernel_path(esp: Path) -> str:
    """Return the path in the ESP of the kernel of the first boot entry."""
    entry = next(line for line in mtools("mdir", esp, "-b", "::/loader/entries").split() if line.endswith(".conf"))
    for line in mtools("mtype", esp, entry).splitlines():
        words = line.split()
        if len(words) == 2 and words[0] == "linux":
            return words[1]
    raise RuntimeError(f"{entry} has no linux line")


def changed_runs(image: Path, start: int, esp: Path, size: int) -> list[tuple[int, int]]:
    """Return the (offset, length) runs where the ESP copy differs from the image."""
    runs: list[tuple[int, int]] = []
    with open(image, "rb") as old, open(esp, "rb") as new:
        old.seek(start)
        offset = 0
        while offset < size:
            length = min(BLOCK, size - offset)
            if old.read(length) != new.read(length):
                if runs and runs[-1][0] + runs[-1][1] == offset:
                    runs[-1] = (runs[-1][0], runs[-1][1] + length)
                else:
                    runs.append((offset, length))
            offset += length
    return runs


def make_disk_with_unsigned_file(base_image: Path, disk: Path, work_dir: Path, esp_file: str | None = None,
                                 disk_size: str = "100G") -> str:
    """Make disk as a qcow2 overlay of base_image. In the overlay, the file
    esp_file of the ESP (default: the kernel) has no signature. Return the
    path of that file. The disk is larger than the image, as for the other
    test machines. On a disk with no free space, systemd-repart cannot make the
    swap and vmdata partitions, and the boot waits 90 seconds for them."""
    start, size = esp_range(base_image)
    esp = work_dir / f"{disk.stem}-esp.img"
    patch = work_dir / f"{disk.stem}-file"
    try:
        copy_range(base_image, start, size, esp)
        path = esp_file or kernel_path(esp)
        mtools("mcopy", esp, "-n", f"::{path}", str(patch))
        patch.write_bytes(unsign(patch.read_bytes()))
        mtools("mcopy", esp, "-n", "-D", "o", str(patch), f"::{path}")

        make_overlay(base_image, disk, disk_size)
        commands = []
        for index, (offset, length) in enumerate(changed_runs(base_image, start, esp, size)):
            run_file = work_dir / f"{disk.stem}-run{index}"
            with open(esp, "rb") as src:
                src.seek(offset)
                run_file.write_bytes(src.read(length))
            commands += ["-c", f"write -s {run_file} {start + offset} {length}"]
        subprocess.run(["qemu-io", "-f", "qcow2", *commands, str(disk)], check=True, capture_output=True)
        return path
    finally:
        esp.unlink(missing_ok=True)
        patch.unlink(missing_ok=True)
        for run_file in work_dir.glob(f"{disk.stem}-run*"):
            run_file.unlink()
