"""Start a QEMU virtual machine from a disk image and run commands over SSH."""

import contextlib
import os
import shutil
import socket
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

OVMF_DIR = Path("/usr/share/OVMF")
OVMF_CODE = OVMF_DIR / "OVMF_CODE_4M.fd"
OVMF_VARS = OVMF_DIR / "OVMF_VARS_4M.fd"
# The Secure Boot firmware enforces signatures. Its variable store has the keys
# that a PC ships with: the Microsoft CA that signs the Debian shim.
OVMF_CODE_SECBOOT = OVMF_DIR / "OVMF_CODE_4M.secboot.fd"
OVMF_VARS_SECBOOT = OVMF_DIR / "OVMF_VARS_4M.ms.fd"

# Without /dev/kvm, QEMU emulates the CPU. That works but is slow, so the
# boot timeout is much longer. QUARRY_TEST_BOOT_TIMEOUT overrides it.
HAS_KVM = os.access("/dev/kvm", os.R_OK | os.W_OK)
BOOT_TIMEOUT = int(os.environ.get("QUARRY_TEST_BOOT_TIMEOUT", 240 if HAS_KVM else 1800))


def free_port():
    # Another process can take the port before QEMU binds it. The chance is
    # small, and QEMU then fails at start, which the test reports.
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def make_overlay(base_image, disk, size=None):
    """Make a qcow2 disk that reads from a raw image. Writes go to the new file."""
    command = ["qemu-img", "create", "-q", "-f", "qcow2", "-F", "raw",
               "-b", str(base_image.resolve()), str(disk)]
    if size:
        command.append(size)
    subprocess.run(command, check=True)


def make_blank_disk(disk, size):
    subprocess.run(["qemu-img", "create", "-q", "-f", "qcow2", str(disk), size], check=True)


def make_data_disk(disk, size_gib=2):
    """Make a sparse raw disk with an ext4 file system that has the label
    "data", as the guest image expects. mke2fs needs no root for a file."""
    mke2fs = shutil.which("mke2fs", path=os.environ["PATH"] + ":/usr/sbin:/sbin")
    if mke2fs is None:
        raise RuntimeError("mke2fs is not installed (package e2fsprogs)")
    with open(disk, "wb") as handle:
        handle.truncate(size_gib * 2**30)
    subprocess.run([mke2fs, "-q", "-F", "-t", "ext4", "-L", "data", str(disk)], check=True)


def data_disk_args(disk):
    """The QEMU options that attach the data disk as the second virtio disk."""
    return ["-drive", f"if=virtio,format=raw,file={disk}"]


def firmware_args(vars_file, secure_boot=True):
    """Copy the variable store to vars_file and return the QEMU options for the
    machine and the firmware. Only a test that must prove that a disk is fine
    without Secure Boot turns it off."""
    if secure_boot:
        code, template = OVMF_CODE_SECBOOT, OVMF_VARS_SECBOOT
        # The keys sit in flash that only the firmware can write (SMM). QEMU
        # needs S3 off for this.
        machine = ["-machine", "q35,smm=on", "-global", "driver=cfi.pflash01,property=secure,value=on",
                   "-global", "ICH9-LPC.disable_s3=1"]
    else:
        code, template = OVMF_CODE, OVMF_VARS
        machine = ["-machine", "q35"]
    shutil.copyfile(template, vars_file)
    return [*machine,
            "-drive", f"if=pflash,format=raw,readonly=on,file={code}",
            "-drive", f"if=pflash,format=raw,file={vars_file}"]


def check_tools():
    """Return the name of the first missing prerequisite, or None."""
    for tool in ("qemu-system-x86_64", "qemu-img", "qemu-io", "mdir", "mtype", "mcopy",
                 "ssh", "ssh-agent", "ssh-add"):
        if shutil.which(tool) is None:
            return tool
    for firmware in (OVMF_CODE, OVMF_VARS, OVMF_CODE_SECBOOT, OVMF_VARS_SECBOOT):
        if not firmware.is_file():
            return str(firmware)
    return None


class Vm:
    """One virtual machine. The disk is a qcow2 overlay of a read-only image,
    so the image is never changed and each machine starts fast. Give no base
    image and a disk to boot an existing qcow2 disk as it is."""

    def __init__(self, name, base_image, settings, work_dir, log_dir, agent_socket,
                 resize=None, memory=2048, disk=None, secure_boot=True):
        self.name = name
        self.secure_boot = secure_boot
        self.settings = settings
        self.agent_socket = agent_socket
        self.memory = memory
        self.port = None
        self.proc = None
        self.disk = disk or work_dir / f"{name}.qcow2"
        self.vars = work_dir / f"{name}-vars.fd"
        self.serial_log = log_dir / f"{name}.serial.log"
        self.qemu_log = log_dir / f"{name}.qemu.log"
        self.base_image = base_image
        self.resize = resize
        self.extra_args = []

    def start(self, wait=True):
        """Start QEMU. With wait=False, do not wait for a login. A test that
        expects a refused boot needs this."""
        if self.base_image is not None:
            make_overlay(self.base_image, self.disk, self.resize)

        self.port = free_port()
        accel = ["-enable-kvm", "-cpu", "host"] if HAS_KVM else ["-accel", "tcg", "-cpu", "max"]
        argv = ["qemu-system-x86_64", *firmware_args(self.vars, self.secure_boot),
                "-smp", "2", "-m", str(self.memory), *accel,
                "-display", "none", "-monitor", "none", "-serial", f"file:{self.serial_log}",
                "-drive", f"if=virtio,format=qcow2,file={self.disk}",
                "-nic", f"user,model=virtio-net-pci,hostfwd=tcp:127.0.0.1:{self.port}-:22",
                *self.extra_args]
        with open(self.qemu_log, "w") as log:
            self.proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=log, stderr=log)
        if wait:
            self.wait_for_ssh()

    @contextlib.contextmanager
    def running(self) -> Iterator["Vm"]:
        """Start the machine. Stop it again, also when the start fails."""
        try:
            self.start()
            yield self
        finally:
            self.stop()

    def stop(self):
        if self.proc is None:
            return
        self.proc.terminate()
        try:
            self.proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()
        self.proc = None

    def ssh_argv(self, command, user=None, forward_agent=False, options=()):
        # The login uses the key file only. Do not set IdentityAgent=none:
        # the client then does not request agent forwarding at all.
        argv = ["ssh", "-p", str(self.port),
                "-o", "UserKnownHostsFile=/dev/null", "-o", "StrictHostKeyChecking=no",
                "-o", "LogLevel=ERROR", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
                "-o", "IdentitiesOnly=yes", "-i", str(self.settings.private_key),
                "-A" if forward_agent else "-a"]
        for option in options:
            argv += ["-o", option]
        return argv + [f"{user or self.settings.admin_user}@127.0.0.1", command]

    def run(self, command, timeout=60, **kwargs):
        """Run a command in the guest. Return the finished process. A timeout
        counts as a failure with return code 124."""
        # The agent of the user must never reach the tests. A forwarding run
        # gets the agent of the test, and every other run gets no agent.
        env = {k: v for k, v in os.environ.items() if k != "SSH_AUTH_SOCK"}
        if kwargs.get("forward_agent"):
            env["SSH_AUTH_SOCK"] = str(self.agent_socket)
        try:
            return subprocess.run(self.ssh_argv(command, **kwargs), capture_output=True, env=env,
                                  text=True, timeout=timeout, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired as err:
            return subprocess.CompletedProcess(err.cmd, 124, "", "timeout")

    def check(self, command, **kwargs):
        result = self.run(command, **kwargs)
        assert result.returncode == 0, (
            f"'{command}' returned {result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}")
        return result

    def sudo(self, command, **kwargs):
        """Run a command with sudo. The agent mode of sudo needs a forwarded agent.
        There is no terminal, so a sudo that needs a password fails at once."""
        kwargs.setdefault("forward_agent", self.settings.sudo_mode == "agent")
        return self.run(f"sudo {command}", **kwargs)

    def check_sudo(self, command, **kwargs):
        result = self.sudo(command, **kwargs)
        assert result.returncode == 0, (
            f"'sudo {command}' returned {result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}")
        return result

    def wait_for_ssh(self, timeout=None, not_boot_id=None):
        """Wait until a login works. With not_boot_id, also wait until the
        guest runs a different boot than that one (used after a reboot)."""
        deadline = time.monotonic() + (timeout or BOOT_TIMEOUT)
        last = None
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"QEMU of {self.name} stopped. See {self.qemu_log}")
            last = self.run("cat /proc/sys/kernel/random/boot_id", timeout=15)
            if last.returncode == 0 and last.stdout.strip() != not_boot_id:
                return
            time.sleep(3)
        tail = "\n".join(self.serial_log.read_text(errors="replace").splitlines()[-20:])
        raise RuntimeError(f"No SSH login to {self.name} in time. Last SSH error: {last.stderr if last else None}\n"
                           f"Last lines of {self.serial_log}:\n{tail}")

    def reboot(self):
        boot_id = self.check("cat /proc/sys/kernel/random/boot_id").stdout.strip()
        # The connection can drop before the command returns, which gives 255.
        result = self.sudo("systemctl reboot")
        if result.returncode not in (0, 255):
            raise RuntimeError(f"the reboot command failed: {result.stderr}")
        self.wait_for_ssh(not_boot_id=boot_id)

    def serial_text(self):
        # QEMU makes the file a moment after it starts.
        if not self.serial_log.exists():
            return ""
        return self.serial_log.read_text(errors="replace")
