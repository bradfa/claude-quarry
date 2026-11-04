"""Tests of the guest image (image/guest.yaml) in a virtual machine.

The guest needs a second disk with the file system label "data". The tests
make it, as the host does for a real guest. The tests in this file depend on
their order: the reboot test (step 9) and the reset test (step 10) change the
state of the first machine.

Tests that need a login to Claude Code (for example that a hook in the
configuration directory does not load) are not here. See
test/manual/real-guest.md.
"""

import json
import os
import re
import shutil
import subprocess
import time

import pytest

from helpers import EFI_SYSTEM, LINUX_ROOT_X86_64, GIB, failed_units
from vm import BOOT_TIMEOUT, data_disk_args, make_data_disk

CONFIG_DIR = "/data/claude-config"
HOST_KEY = "/data/etc/ssh/ssh_host_ed25519_key"
SECURE_BOOT_VARIABLE = "/sys/firmware/efi/efivars/SecureBoot-8be4df61-93ca-11d2-aa0d-00e098032b8c"


@pytest.fixture
def sudo_mode_agent(settings):
    if settings.sudo_mode != "agent":
        pytest.skip("the image uses SUDO_MODE=nopasswd")


@pytest.fixture
def sudo_mode_nopasswd(settings):
    if settings.sudo_mode != "nopasswd":
        pytest.skip("the image uses SUDO_MODE=agent")


def make_guest(make_vm, guest_image, name, data_disk):
    """Make a machine with the data disk, or with none when data_disk is None."""
    machine = make_vm(name, guest_image, resize="100G")
    if data_disk is not None:
        machine.extra_args = data_disk_args(data_disk)
    return machine


@pytest.fixture(scope="module")
def guest_a(make_vm, guest_image, work_dir):
    data_disk = work_dir / "guest-a-data.img"
    make_data_disk(data_disk)
    machine = make_guest(make_vm, guest_image, "guest-a", data_disk)
    machine.data_disk = data_disk
    with machine.running():
        yield machine


@pytest.fixture(scope="module")
def guest_nodata(make_vm, guest_image):
    machine = make_guest(make_vm, guest_image, "guest-nodata", None)
    try:
        machine.start(wait=False)
        yield machine
    finally:
        machine.stop()


def as_claude(machine, settings, command, **kwargs):
    return machine.run(command, user=settings.claude_user, **kwargs)


def check_as_claude(machine, settings, command, **kwargs):
    return machine.check(command, user=settings.claude_user, **kwargs)


def sshd_settings(machine, user):
    """The effective sshd settings for one user, as lists of values."""
    out = machine.check_sudo(f"sshd -T -C user={user},host=localhost,addr=127.0.0.1").stdout
    found = {}
    for line in out.splitlines():
        key, _, value = line.partition(" ")
        found.setdefault(key, []).append(value)
    return found


# Step 1: the image file

def test_1_01_image_is_sparse(guest_image):
    assert guest_image.stat().st_blocks * 512 < guest_image.stat().st_size, "the image is not sparse"


# Step 2: the layout of the image

def test_2_01_partitions(guest_image):
    sfdisk = shutil.which("sfdisk", path=os.environ["PATH"] + ":/usr/sbin:/sbin")
    if sfdisk is None:
        pytest.skip("sfdisk is not installed")
    out = subprocess.run([sfdisk, "--json", str(guest_image)], capture_output=True, text=True, check=True).stdout
    table = json.loads(out)["partitiontable"]["partitions"]
    assert [p["type"].lower() for p in table] == [EFI_SYSTEM, LINUX_ROOT_X86_64]
    assert all(p["start"] % 2048 == 0 for p in table), "a partition is not aligned to 1 MiB"
    assert table[0]["size"] * 512 == GIB


# Step 3: the boot

def test_3_01_serial_console_shows_login(guest_a):
    assert "login:" in guest_a.serial_text(), (
        "no login prompt on the serial port. Build the image with "
        "KERNEL_CMDLINE_EXTRA=console=tty0 console=ttyS0,115200")


def test_3_02_no_failed_units(guest_a):
    assert failed_units(guest_a) == []


def test_3_03_secure_boot_is_on(guest_a):
    # The tests always start the machine with the Secure Boot firmware, so this
    # shows that the guest boots through the signed chain. The last byte of
    # the variable is its value.
    assert guest_a.check(f"od -An -tu1 {SECURE_BOOT_VARIABLE}").stdout.split()[-1] == "1"


@pytest.mark.parametrize("unit", ["ssh", "chrony", "systemd-networkd", "systemd-resolved", "quarry-data-setup"])
def test_3_04_service_active(guest_a, unit):
    assert guest_a.check(f"systemctl is-active {unit}").stdout.strip() == "active"


def test_3_05_host_name(guest_a, settings):
    assert guest_a.check("hostname").stdout.strip() == settings.guest_name


def test_3_06_network_configured(guest_a):
    links = [line.split() for line in guest_a.check("networkctl list --no-legend").stdout.splitlines()]
    wired = [link for link in links if link[1].startswith("en")]
    assert len(wired) == 1, f"expected one en* link, found {links}"
    assert wired[0][3:5] == ["routable", "configured"]
    assert "10-wired.network" in guest_a.check(f"networkctl status {wired[0][1]}").stdout


def test_3_07_resolv_conf_link(guest_a):
    assert guest_a.check("readlink /etc/resolv.conf").stdout.strip() == "../run/systemd/resolve/stub-resolv.conf"


def test_3_08_ifupdown_is_gone(guest_a):
    assert guest_a.run("dpkg -s ifupdown").returncode != 0


# Step 4: the two accounts

def test_4_01_both_accounts_log_in(guest_a, settings):
    assert guest_a.check("id -un").stdout.strip() == settings.admin_user
    assert check_as_claude(guest_a, settings, "id -un").stdout.strip() == settings.claude_user


def test_4_02_claude_is_in_no_group(guest_a, settings):
    groups = check_as_claude(guest_a, settings, "id -Gn").stdout.split()
    assert groups == [settings.claude_user], groups


def test_4_03_admin_is_in_sudo_group(guest_a, settings):
    assert "sudo" in guest_a.check("id -Gn").stdout.split()


def test_4_04_claude_has_no_sudo(guest_a, settings):
    result = as_claude(guest_a, settings, "sudo -n -l")
    assert result.returncode != 0
    assert "NOPASSWD" not in result.stdout, result.stdout


def test_4_05_sshd_settings_of_both_accounts(guest_a, settings):
    claude = sshd_settings(guest_a, settings.claude_user)
    admin = sshd_settings(guest_a, settings.admin_user)
    assert claude["allowagentforwarding"] == ["no"]
    assert admin["allowagentforwarding"] == ["yes"]
    for found in (claude, admin):
        assert sorted(found["allowusers"]) == sorted([settings.claude_user, settings.admin_user])
        assert found["authorizedkeysfile"] == ["/etc/ssh/authorized_keys/%u"]
        assert found["hostkey"] == [HOST_KEY]
        assert found["passwordauthentication"] == ["no"]
        assert found["permitrootlogin"] == ["no"]


def test_4_06_key_files_belong_to_root(guest_a, settings):
    out = guest_a.check(
        f"stat -c '%U:%G %a %n' /etc/ssh/authorized_keys /etc/ssh/authorized_keys/{settings.claude_user} "
        f"/etc/ssh/authorized_keys/{settings.admin_user}").stdout.splitlines()
    assert [line.split()[:2] for line in out] == [["root:root", "755"], ["root:root", "644"], ["root:root", "644"]]


def test_4_07_claude_cannot_change_key_files(guest_a, settings):
    path = f"/etc/ssh/authorized_keys/{settings.claude_user}"
    assert as_claude(guest_a, settings, f"test -w {path}").returncode != 0
    assert as_claude(guest_a, settings, f"echo x >> {path}").returncode != 0
    assert as_claude(guest_a, settings, "touch /etc/ssh/authorized_keys/new").returncode != 0
    assert as_claude(guest_a, settings, "test -e ~/.ssh/authorized_keys").returncode != 0


def test_4_08_homes_are_private(guest_a, settings):
    out = guest_a.check_sudo(f"stat -c %a /home/{settings.claude_user} /home/{settings.admin_user}").stdout.split()
    assert out == ["700", "700"]
    assert as_claude(guest_a, settings, f"ls /home/{settings.admin_user}").returncode != 0
    assert guest_a.run(f"ls /home/{settings.claude_user}").returncode != 0


def test_4_09_claude_gets_no_agent(guest_a, settings):
    # sshd refuses the forwarding for the Claude account, even when the client asks.
    check_as_claude(guest_a, settings, 'test -z "$SSH_AUTH_SOCK"', forward_agent=True)
    guest_a.check('test -S "$SSH_AUTH_SOCK"', forward_agent=True)


def test_4_10_sudo_with_agent(guest_a, sudo_mode_agent):
    guest_a.check("sudo true", forward_agent=True)


def test_4_11_sudo_without_agent_fails(guest_a, sudo_mode_agent):
    result = guest_a.run("sudo true", forward_agent=False)
    assert result.returncode != 0
    assert "password" in result.stderr, result.stderr


# The nopasswd image: run the suite with SUDO_MODE=nopasswd and
# QUARRY_TEST_GUEST_IMAGE set to the image built with that mode.

def test_4_11a_sudo_needs_nothing(guest_a, sudo_mode_nopasswd):
    guest_a.check("sudo true", forward_agent=False)


def test_4_11b_no_agent_key_file(guest_a, sudo_mode_nopasswd):
    assert guest_a.run("test -e /etc/security/sudo_authorized_keys").returncode != 0


def test_4_12_claude_cannot_use_the_agent_of_the_admin(guest_a, settings):
    # A30. The admin runs a command as the Claude account, with the socket of
    # the forwarded agent. The admin itself can use the agent (the control).
    control = guest_a.check("ssh-add -l", forward_agent=True)
    assert "ED25519" in control.stdout or "RSA" in control.stdout or "ECDSA" in control.stdout
    result = guest_a.check_sudo(
        f"-u {settings.claude_user} env SSH_AUTH_SOCK=\"$SSH_AUTH_SOCK\" "
        "sh -c 'ssh-add -l > /dev/null 2>&1; echo rc=$?'", forward_agent=True)
    assert result.stdout.strip() == "rc=2", result.stdout


def test_4_13_root_login_refused(guest_a):
    result = guest_a.run("true", user="root")
    assert result.returncode == 255
    assert "Permission denied" in result.stderr


def test_4_14_password_login_refused(guest_a, settings):
    for user in (settings.admin_user, settings.claude_user):
        result = guest_a.run("true", user=user, options=["PubkeyAuthentication=no"])
        assert result.returncode == 255
        assert "Permission denied" in result.stderr
        assert "password" not in result.stderr


def test_4_15_root_is_locked(guest_a):
    assert guest_a.check_sudo("passwd -S root").stdout.split()[1] == "L"


# Step 5: the data disk and the configuration directory of Claude Code

@pytest.fixture(scope="module")
def auth_status(guest_a, settings):
    """The first run of Claude Code makes the files in the configuration directory."""
    result = as_claude(guest_a, settings, "claude auth status")
    return json.loads(result.stdout)


def test_5_01_data_disk_is_mounted(guest_a):
    assert guest_a.check("findmnt -no FSTYPE,LABEL /data").stdout.split() == ["ext4", "data"]


def test_5_02_config_dir_belongs_to_claude(guest_a, settings):
    out = guest_a.check_sudo(f"stat -c '%U:%G %a' {CONFIG_DIR}").stdout.strip()
    assert out == f"{settings.claude_user}:{settings.claude_user} 700"


def test_5_03_login_session_sets_the_variable(auth_status):
    # The output of Claude Code names the directory that it uses.
    assert auth_status["configDirectory"] == CONFIG_DIR


@pytest.mark.parametrize("name,command", [
    ("ssh command", "echo $CLAUDE_CONFIG_DIR"),
    ("login shell", "bash -lc 'echo $CLAUDE_CONFIG_DIR'"),
    ("tmux", "rm -f /tmp/tmux-var; tmux new-session -d -s t 'echo $CLAUDE_CONFIG_DIR > /tmp/tmux-var'; "
             "for i in 1 2 3 4 5 6 7 8 9 10; do [ -s /tmp/tmux-var ] && break; sleep 1; done; "
             "cat /tmp/tmux-var"),
])
def test_5_04_variable_reaches_every_kind_of_session(guest_a, settings, name, command):
    assert check_as_claude(guest_a, settings, command).stdout.strip() == CONFIG_DIR, name


def test_5_05_state_is_on_the_data_disk(guest_a, settings, auth_status):
    check_as_claude(guest_a, settings, f"test -f {CONFIG_DIR}/.claude.json")
    leftovers = check_as_claude(guest_a, settings, "find ~ -maxdepth 1 -name '.claude*'").stdout.strip()
    assert leftovers == "", leftovers


def test_5_06_host_keys_are_on_the_data_disk(guest_a):
    guest_a.check_sudo(f"test -f {HOST_KEY}")
    assert guest_a.run("ls /etc/ssh/ssh_host_ed25519_key").returncode != 0


def test_5_07_claude_cannot_read_the_host_key(guest_a, settings):
    assert as_claude(guest_a, settings, f"test -r {HOST_KEY}").returncode != 0


# Step 6: Claude Code and the updates

def test_6_01_claude_code_is_owned_by_root(guest_a, settings):
    # Where the package puts the binary is not verified [A28], so the path is
    # not part of the check.
    path = check_as_claude(guest_a, settings, "readlink -f $(command -v claude)").stdout.strip()
    assert guest_a.check(f"stat -c %U {path}").stdout.strip() == "root"
    assert as_claude(guest_a, settings, f"test -w {path}").returncode != 0
    assert as_claude(guest_a, settings, f"test -w $(dirname {path})").returncode != 0
    assert "claude-code" in guest_a.check(f"dpkg -S {path}").stdout


def test_6_02_claude_code_runs(guest_a, settings):
    assert "Claude Code" in check_as_claude(guest_a, settings, "claude --version").stdout


def test_6_03_repository_is_pinned_to_one_package(guest_a, settings):
    claude_code = guest_a.check("apt-cache policy claude-code").stdout
    assert f"downloads.claude.ai/claude-code/apt/{settings.claude_code_channel}" in claude_code
    assert "Candidate: (none)" not in claude_code
    assert "downloads.claude.ai" not in guest_a.check("apt-cache policy libc6").stdout
    assert "downloads.claude.ai" not in guest_a.check("apt-cache policy openssh-server").stdout


def test_6_04_signing_key_has_the_published_fingerprint(guest_a):
    out = guest_a.check("gpg --show-keys --with-colons /etc/apt/keyrings/claude-code.asc").stdout
    assert out.count("\npub:") + out.startswith("pub:") == 1
    assert "fpr:::::::::31DDDE24DDFAB679F42D7BD2BAA929FF1A7ECACE:" in out


def test_6_05_updates_include_the_repository(guest_a, settings):
    config = guest_a.check("apt-config dump").stdout
    line = (f'Unattended-Upgrade::Origins-Pattern:: '
            f'"origin=Anthropic,codename={settings.claude_code_channel},label=Anthropic";')
    assert line in config


@pytest.mark.parametrize("timer", ["apt-daily.timer", "apt-daily-upgrade.timer"])
def test_6_06_update_timer_active(guest_a, timer):
    assert guest_a.check(f"systemctl is-enabled {timer}").stdout.strip() == "enabled"
    assert guest_a.check(f"systemctl is-active {timer}").stdout.strip() == "active"


def test_6_07_updates_are_on_and_reboot_is_off(guest_a):
    config = guest_a.check("apt-config dump").stdout
    assert 'APT::Periodic::Update-Package-Lists "1";' in config
    assert 'APT::Periodic::Unattended-Upgrade "1";' in config
    assert not re.search(r'^Unattended-Upgrade::Automatic-Reboot "(true|1|yes)";', config, re.MULTILINE)


# Step 7: the managed files of Claude Code

@pytest.mark.parametrize("path", ["/etc/claude-code", "/etc/claude-code/managed-settings.json",
                                  "/etc/claude-code/CLAUDE.md"])
def test_7_01_managed_files_belong_to_root(guest_a, settings, path):
    assert guest_a.check(f"stat -c %U:%G {path}").stdout.strip() == "root:root"
    assert as_claude(guest_a, settings, f"test -w {path}").returncode != 0


def test_7_02_managed_settings_content(guest_a):
    managed = json.loads(guest_a.check("cat /etc/claude-code/managed-settings.json").stdout)
    assert managed["permissions"]["defaultMode"] == "auto"
    assert managed["forceLoginMethod"] == "claudeai"
    assert managed["strictPluginOnlyCustomization"] is True
    assert managed["allowManagedPermissionRulesOnly"] is True
    assert managed["allowManagedHooksOnly"] is True
    assert managed["strictKnownMarketplaces"] == []
    assert "$defaults" in managed["autoMode"]["environment"]


def test_7_03_marketplaces_are_locked(guest_a, settings):
    # The managed settings allow no marketplace source. If they did not apply,
    # Claude Code would add this local marketplace.
    marketplace = '{"name":"x","owner":{"name":"x"},"plugins":[]}'
    result = as_claude(
        guest_a, settings,
        f"mkdir -p /tmp/market/.claude-plugin && printf '%s' '{marketplace}' > /tmp/market/.claude-plugin/marketplace.json "
        "&& claude plugin marketplace add /tmp/market")
    text = (result.stdout + result.stderr).lower()
    assert result.returncode != 0, text
    assert any(word in text for word in ("policy", "blocked", "not allowed", "disallowed")), text


# Step 8: the build tools

@pytest.mark.parametrize("tool", ["gcc", "make", "gawk", "chrpath", "cpio", "diffstat", "socat", "unzip",
                                  "wget", "zstd", "lz4", "git", "tmux", "python3", "makeinfo", "file"])
def test_8_01_tool_is_installed(guest_a, settings, tool):
    check_as_claude(guest_a, settings, f"command -v {tool}")


def test_8_02_locale_exists(guest_a, settings):
    assert re.search(r"en_US\.utf-?8", check_as_claude(guest_a, settings, "locale -a").stdout, re.IGNORECASE)


def test_8_03_user_namespaces_work(guest_a, settings):
    # Bitbake needs them.
    assert check_as_claude(guest_a, settings, "unshare --user --map-root-user id -u").stdout.strip() == "0"


def test_8_04_claude_can_commit(guest_a, settings):
    check_as_claude(
        guest_a, settings,
        "rm -rf /tmp/repo && git init -q /tmp/repo && cd /tmp/repo && echo x > f && git add f "
        "&& git -c user.name=t -c user.email=t@example.com commit -q -m test")


# Step 9: reboot of the first machine

@pytest.fixture(scope="module")
def before_reboot(guest_a, settings):
    check_as_claude(guest_a, settings, f"echo marker > {CONFIG_DIR}/marker")
    return {"key": guest_a.check_sudo(f"ssh-keygen -lf {HOST_KEY}.pub").stdout}


@pytest.fixture(scope="module")
def after_reboot(guest_a, before_reboot):
    """The reboot is a prerequisite and not a check, so a failed reboot makes
    the tests of this step error and cannot make them pass."""
    guest_a.reboot()
    return before_reboot


def test_9_01_host_key_is_kept(guest_a, after_reboot):
    assert guest_a.check_sudo(f"ssh-keygen -lf {HOST_KEY}.pub").stdout == after_reboot["key"]


def test_9_02_config_dir_is_kept(guest_a, settings, after_reboot):
    assert check_as_claude(guest_a, settings, f"cat {CONFIG_DIR}/marker").stdout.strip() == "marker"


def test_9_03_no_failed_units(guest_a, after_reboot):
    assert failed_units(guest_a) == []


# Step 10: a reset of the system disk. The new machine has a new overlay and
# the same data disk.

@pytest.fixture(scope="module")
def after_reset(guest_a, settings, make_vm, guest_image, after_reboot):
    check_as_claude(guest_a, settings, "echo marker > ~/home-marker")
    key = guest_a.check_sudo(f"ssh-keygen -lf {HOST_KEY}.pub").stdout
    guest_a.check("sync")
    guest_a.stop()
    machine = make_guest(make_vm, guest_image, "guest-reset", guest_a.data_disk)
    with machine.running():
        yield machine, key


def test_10_01_host_key_survives_a_reset(after_reset):
    machine, key = after_reset
    assert machine.check_sudo(f"ssh-keygen -lf {HOST_KEY}.pub").stdout == key


def test_10_02_config_dir_survives_a_reset(after_reset, settings):
    machine, _ = after_reset
    assert check_as_claude(machine, settings, f"cat {CONFIG_DIR}/marker").stdout.strip() == "marker"


def test_10_03_home_directory_does_not(after_reset, settings):
    machine, _ = after_reset
    assert as_claude(machine, settings, "test -e ~/home-marker").returncode != 0


# Step 11: no data disk. The guest must not make host keys on the overlay, and
# Claude Code must not keep its login there. So sshd does not start, and the
# console stays usable.

def test_11_01_no_login_without_the_data_disk(guest_nodata):
    deadline = time.monotonic() + BOOT_TIMEOUT
    while "login:" not in guest_nodata.serial_text():
        assert time.monotonic() < deadline, "the guest did not reach a login prompt without its data disk"
        time.sleep(3)
    assert guest_nodata.run("true", timeout=30).returncode == 255
