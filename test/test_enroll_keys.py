"""Tests of quarry-enroll-secure-boot-keys in the host image.

The machine has a firmware that can enforce Secure Boot but holds no keys. This
is the state of a PC after "Custom Keys" in the setup menu (OVMF_VARS_4M.fd). The
tests depend on their order: the script changes the firmware variables.
"""

import pytest


@pytest.fixture(scope="module")
def vm_setup(make_vm, host_image):
    with make_vm("host-setup-mode", host_image, resize="100G", empty_keys=True).running() as machine:
        yield machine


def test_1_01_firmware_is_in_setup_mode(vm_setup):
    state = vm_setup.check("mokutil --sb-state").stdout
    assert "Setup Mode" in state, state


def test_1_02_script_enrolls_the_keys(vm_setup):
    result = vm_setup.check_sudo("quarry-enroll-secure-boot-keys", timeout=120)
    assert "Done." in result.stdout, result.stdout


def test_1_03_script_refuses_without_setup_mode(vm_setup):
    result = vm_setup.sudo("quarry-enroll-secure-boot-keys", timeout=120)
    assert result.returncode != 0
    assert "not in Setup Mode" in result.stderr, result.stderr


def test_1_04_no_private_key_is_left(vm_setup):
    assert vm_setup.check_sudo("find /run /tmp /root -name 'PK.key'").stdout.strip() == ""


def test_1_05_secure_boot_enforces_after_a_reboot(vm_setup):
    # The host must boot again. The shim has to pass the new db.
    vm_setup.reboot()
    state = vm_setup.check("mokutil --sb-state").stdout
    assert "SecureBoot enabled" in state, state


@pytest.mark.parametrize("variable,names", [
    ("db", ["Microsoft Corporation UEFI CA 2011", "Microsoft UEFI CA 2023"]),
    ("kek", ["Microsoft Corporation KEK CA 2011", "Microsoft Corporation KEK 2K CA 2023"]),
    ("pk", ["quarry host Platform Key"]),
])
def test_1_06_keys_are_in_the_database(vm_setup, variable, names):
    listing = vm_setup.check_sudo(f"mokutil --{variable}").stdout
    for name in names:
        assert name in listing, f"'{name}' is not in {variable}:\n{listing}"
