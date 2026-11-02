"""Start a QEMU virtual machine and use its serial console like a person does.

QEMU runs with -nographic, and pexpect plays the part of the terminal. The
installer has no network and no SSH, so the console is the only way to use it.
"""

import contextlib
import os
import re
import shutil
import uuid
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

import pexpect

import vm as quarry_vm

# Writing the host image to the target disk takes minutes without KVM.
INSTALL_TIMEOUT = int(os.environ.get("QUARRY_TEST_INSTALL_TIMEOUT", 1200 if quarry_vm.HAS_KVM else 7200))

# The output of a terminal: escape sequences and carriage returns.
TERMINAL_NOISE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b[()][A-Za-z0-9]|\x1b[=>]|\r")

# The last line of the installer banner (image/overlays/installer/etc/profile.d).
BANNER_END = "confirm the disk name"


@dataclass
class Disk:
    path: Path
    serial: str | None = None


@dataclass
class Result:
    status: int
    output: str


class ConsoleVm:
    """A virtual machine with virtio disks. The first disk is the boot disk."""

    def __init__(self, name: str, work_dir: Path, log_dir: Path, disks: Sequence[Disk], memory: int = 2048):
        self.name = name
        self.disks = disks
        self.memory = memory
        self.vars = work_dir / f"{name}-vars.fd"
        self.log_path = log_dir / f"{name}.serial.log"
        self.child: pexpect.spawn | None = None
        self.log_file = None

    def start(self) -> None:
        shutil.copyfile(quarry_vm.OVMF_VARS, self.vars)
        accel = ["-enable-kvm", "-cpu", "host"] if quarry_vm.HAS_KVM else ["-accel", "tcg", "-cpu", "max"]
        argv = ["-machine", "q35", "-smp", "2", "-m", str(self.memory), *accel, "-nographic",
                "-drive", f"if=pflash,format=raw,readonly=on,file={quarry_vm.OVMF_CODE}",
                "-drive", f"if=pflash,format=raw,file={self.vars}"]
        for index, disk in enumerate(self.disks):
            device = f"virtio-blk-pci,drive=disk{index}"
            if disk.serial:
                device += f",serial={disk.serial}"
            if index == 0:
                device += ",bootindex=0"
            argv += ["-drive", f"if=none,format=qcow2,id=disk{index},file={disk.path}", "-device", device]
        self.log_file = open(self.log_path, "w")
        self.child = pexpect.spawn("qemu-system-x86_64", argv, encoding="utf-8", codec_errors="replace",
                                   timeout=quarry_vm.BOOT_TIMEOUT)
        self.child.logfile_read = self.log_file
        self.wait_for_shell()

    @contextlib.contextmanager
    def running(self) -> Iterator["ConsoleVm"]:
        """Start the machine. Stop it again, also when the start fails."""
        try:
            self.start()
            yield self
        finally:
            self.stop()

    def stop(self) -> None:
        if self.child is not None:
            self.child.terminate(force=True)
            self.child.close()
            self.child = None
        if self.log_file is not None:
            self.log_file.close()
            self.log_file = None

    def wait_for_shell(self) -> None:
        """Wait for the banner. The installer logs in as root by itself."""
        self.child.expect(BANNER_END)
        # A long command would wrap at the default 80 columns, and the wrap
        # would change the echo of the command.
        self.run("stty cols 250")

    def run(self, command: str, answers: Sequence[tuple[str, str]] = (), timeout: int = 120) -> Result:
        """Type a command and return its output and exit status. For each
        pair in answers, wait for the pattern and type the reply."""
        marker = f"QDONE{uuid.uuid4().hex[:8]}"
        # The echo of this line has "$?" and not a digit after the hyphen, so
        # only the real output matches the pattern below.
        self.child.sendline(f"{command}; echo {marker}-$?")
        parts = []
        for pattern, reply in answers:
            self.child.expect(pattern, timeout=timeout)
            parts.append(self.child.before + self.child.after)
            self.child.sendline(reply)
        self.child.expect(rf"{marker}-(\d+)", timeout=timeout)
        parts.append(self.child.before)
        text = TERMINAL_NOISE.sub("", "".join(parts))
        # Drop the prompt and the echo of the command.
        echo_end = text.find("\n", text.find(f"echo {marker}-$?"))
        return Result(int(self.child.match.group(1)), text[echo_end + 1:])

    def check(self, command: str, **kwargs) -> Result:
        result = self.run(command, **kwargs)
        assert result.status == 0, f"'{command}' returned {result.status}\n{result.output}"
        return result

    def log_text(self) -> str:
        return self.log_path.read_text(errors="replace")


def make_disks(work_dir: Path, name: str, usb_base: Path, target_size: str, small_size: str | None = None,
               target_serial: str | None = "TARGETDISK0001") -> list[Disk]:
    """The disks of an installer test: the USB stick, the empty target disk,
    and optionally a disk that is too small for the image."""
    usb = work_dir / f"{name}-usb.qcow2"
    quarry_vm.make_overlay(usb_base, usb)
    target = work_dir / f"{name}-target.qcow2"
    quarry_vm.make_blank_disk(target, target_size)
    disks = [Disk(usb, "USBSTICK"), Disk(target, target_serial)]
    if small_size:
        small = work_dir / f"{name}-small.qcow2"
        quarry_vm.make_blank_disk(small, small_size)
        disks.append(Disk(small, "SMALLDISK0001"))
    return disks
