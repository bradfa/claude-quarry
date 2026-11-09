"""Fixtures for the image tests."""

import os
import shutil
import subprocess
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

import console
import settings as quarry_settings
import vm as quarry_vm


@pytest.fixture(scope="session")
def settings() -> quarry_settings.Settings:
    missing = quarry_vm.check_tools()
    if missing:
        pytest.fail(f"Prerequisite missing: {missing}. See test/README.md", pytrace=False)
    try:
        loaded = quarry_settings.load()
    except (ValueError, OSError) as err:
        pytest.fail(str(err), pytrace=False)
    if loaded.shim_remove_signature == "2011" and shutil.which("virt-fw-vars") is None:
        pytest.fail("Prerequisite missing: virt-fw-vars (package python3-virt-firmware). "
                    "SHIM_REMOVE_SIGNATURE=2011 needs it. See test/README.md", pytrace=False)
    return loaded


@pytest.fixture(scope="session")
def secboot_vars(settings: quarry_settings.Settings, work_dir: Path) -> None:
    """Without the 2011 signature, the shim needs the 2023 CA in the firmware."""
    if settings.shim_remove_signature == "2011":
        quarry_vm.use_secboot_vars_with_2023_ca(work_dir / "OVMF_VARS_4M.ms-2023.fd")


@pytest.fixture(scope="session")
def agent_socket(settings: quarry_settings.Settings) -> Iterator[Path]:
    """An SSH agent that holds the test key. The tests forward it for the
    agent mode of sudo. The agent of the user is never used."""
    # A socket path has a short length limit, so the path is not in image/build.
    directory = Path(tempfile.mkdtemp(prefix="quarry-agent-"))
    socket = directory / "agent.sock"
    agent = subprocess.Popen(["ssh-agent", "-D", "-a", str(socket)], stdout=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 10
        while not socket.exists():
            if time.monotonic() > deadline or agent.poll() is not None:
                pytest.fail("ssh-agent did not start", pytrace=False)
            time.sleep(0.1)
        added = subprocess.run(["ssh-add", str(settings.private_key)], env={"SSH_AUTH_SOCK": str(socket)},
                               capture_output=True, text=True, stdin=subprocess.DEVNULL)
        if added.returncode != 0:
            pytest.fail(f"cannot add the test key (it must have no passphrase): {added.stderr}", pytrace=False)
        yield socket
    finally:
        agent.terminate()
        agent.wait()
        shutil.rmtree(directory)


@pytest.fixture(scope="session")
def work_dir() -> Iterator[Path]:
    """Disks of the test machines. They live in image/build, not in /tmp,
    because /tmp is RAM on Debian 13. QUARRY_TEST_KEEP=1 keeps them."""
    quarry_settings.LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = Path(tempfile.mkdtemp(prefix="test-vms-", dir=quarry_settings.BUILD_DIR))
    yield path
    if os.environ.get("QUARRY_TEST_KEEP") != "1":
        shutil.rmtree(path)


@pytest.fixture(scope="session")
def make_vm(settings, agent_socket, work_dir, secboot_vars):
    def make(name: str, image: Path, **kwargs) -> quarry_vm.Vm:
        return quarry_vm.Vm(name, image, settings, work_dir, quarry_settings.LOG_DIR,
                            agent_socket, **kwargs)
    return make


@pytest.fixture(scope="session")
def make_console(work_dir, secboot_vars):
    def make(name: str, disks: list[console.Disk], **kwargs) -> console.ConsoleVm:
        return console.ConsoleVm(name, work_dir, quarry_settings.LOG_DIR, disks, **kwargs)
    return make


@pytest.fixture(scope="session")
def installer_image(settings) -> Path:
    if not settings.installer_image.is_file():
        pytest.skip(f"{settings.installer_image} does not exist. Build it with image/build.sh")
    return settings.installer_image


@pytest.fixture(scope="session")
def host_image(settings) -> Path:
    if not settings.host_image.is_file():
        pytest.skip(f"{settings.host_image} does not exist. Build it with image/build.sh host")
    return settings.host_image


@pytest.fixture(scope="session")
def guest_image(settings) -> Path:
    if not settings.guest_image.is_file():
        pytest.skip(f"{settings.guest_image} does not exist. Build it with image/build.sh guest")
    return settings.guest_image
