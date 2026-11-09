"""Test settings. They have the same names as the settings of image/build.sh.

A value comes from the environment first, then from the file that BUILD_CONF
names (default image/build.conf). The images under test must come from the
same settings.
"""

import os
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BUILD_DIR = REPO / "image" / "build"
LOG_DIR = BUILD_DIR / "test-logs"

NAMES = ("ADMIN_USER", "ADMIN_SSH_KEY_FILE", "SUDO_MODE", "HOST_NAME",
         "CLAUDE_USER", "CLAUDE_CODE_CHANNEL", "GUEST_NAME", "SHIM_REMOVE_SIGNATURE")


@dataclass(frozen=True)
class Settings:
    admin_user: str
    claude_user: str
    claude_code_channel: str
    private_key: Path
    sudo_mode: str
    host_name: str
    guest_name: str
    shim_remove_signature: str
    host_image: Path
    guest_image: Path
    installer_image: Path


def read_conf(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        values[name] = value
    return values


def load() -> Settings:
    values = read_conf(Path(os.environ.get("BUILD_CONF", REPO / "image" / "build.conf")))
    for name in NAMES:
        if name in os.environ:
            values[name] = os.environ[name]

    for name in ("ADMIN_USER", "ADMIN_SSH_KEY_FILE"):
        if not values.get(name):
            raise ValueError(f"{name} is not set. Set it in image/build.conf or in the environment")

    # The tests log in with the private key that belongs to the public key of
    # the image. It must have no passphrase, because no one is there to type it.
    public_key = Path(values["ADMIN_SSH_KEY_FILE"])
    if public_key.suffix != ".pub":
        raise ValueError("ADMIN_SSH_KEY_FILE must end in .pub, and the private key must be next to it")
    private_key = public_key.with_suffix("")
    if not private_key.is_file():
        raise ValueError(f"cannot find the private key {private_key}")

    sudo_mode = values.get("SUDO_MODE", "agent")
    if sudo_mode not in ("agent", "nopasswd"):
        raise ValueError("SUDO_MODE must be agent or nopasswd")

    channel = values.get("CLAUDE_CODE_CHANNEL", "stable")
    if channel not in ("stable", "latest"):
        raise ValueError("CLAUDE_CODE_CHANNEL must be stable or latest")

    shim_remove_signature = values.get("SHIM_REMOVE_SIGNATURE", "none")
    if shim_remove_signature not in ("none", "2011", "2023"):
        raise ValueError("SHIM_REMOVE_SIGNATURE must be none, 2011, or 2023")

    host_image = Path(os.environ.get("QUARRY_TEST_HOST_IMAGE", BUILD_DIR / "host.img"))
    guest_image = Path(os.environ.get("QUARRY_TEST_GUEST_IMAGE", BUILD_DIR / "guest.img"))
    installer_image = Path(os.environ.get("QUARRY_TEST_INSTALLER_IMAGE", BUILD_DIR / "installer.img"))

    return Settings(
        admin_user=values["ADMIN_USER"],
        claude_user=values.get("CLAUDE_USER", "claude"),
        claude_code_channel=channel,
        private_key=private_key,
        sudo_mode=sudo_mode,
        host_name=values.get("HOST_NAME", "quarry-host"),
        guest_name=values.get("GUEST_NAME", "quarry-guest"),
        shim_remove_signature=shim_remove_signature,
        host_image=host_image,
        guest_image=guest_image,
        installer_image=installer_image,
    )
