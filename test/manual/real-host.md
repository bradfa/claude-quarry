# Checks on the real host

A virtual machine cannot answer these points. Run them by hand on the real
host, after the tests in `test/` pass. Do not write results in this file. Keep
them in your own notes, and delete the matching row in `doc/assumptions.md` when
a check proves a claim.

WARNING: the installer erases the whole target disk. Make sure that you have
the right disk before you start.

## Prerequisites

- The installer image from `image/build.sh`, and a USB stick that is at least as
  large as `INSTALLER_SIZE`.
- A monitor and a keyboard, or the serial console or the BMC of the host. The
  installer has no SSH.
- An SSH agent on your daily machine that holds the key of `ADMIN_USER`.

## 1. Boot the installer

Write the installer to the USB stick with `bmaptool copy`. Boot the host from the
stick.

| # | Check | Expected result | Open point |
| --- | --- | --- | --- |
| 1.1 | The firmware boots the stick, and the installer banner appears | The banner lists the disks of the host | Q6 |
| 1.2 | Run `lsblk -d -o NAME,SIZE,MODEL,SERIAL,TRAN` | The target disk shows with the expected model and size | |
| 1.3 | Run `quarry-install` with the target disk, and confirm the name | The write ends with `Done.` and exit code 0 | |

## 2. Boot the host

Remove the USB stick, and reboot.

| # | Check | Expected result | Open point |
| --- | --- | --- | --- |
| 2.1 | The firmware boots the disk without a boot entry that you made | The boot menu, then the kernel, then a login prompt | Q6 |
| 2.2 | SSH login with `ssh -A` from the daily machine | It works within 1 minute | |
| 2.3 | `lsblk -o NAME,SIZE,FSTYPE,PARTLABEL,MOUNTPOINTS` | 4 partitions: ESP, root, `swap`, and `vmdata` (XFS) on the rest of the disk | |
| 2.4 | `sudo true` in the session with `-A` | Exit code 0, with the touch or PIN that the Yubikey needs | |
| 2.5 | `systemctl --failed` | `0 loaded units listed` | |
| 2.6 | `chronyc sources` | At least one server has a `*` or a `+` | |

## 3. Network match with a passthrough card

Do this after the Ethernet card for the guest is in the host.

| # | Check | Expected result | Open point |
| --- | --- | --- | --- |
| 3.1 | `networkctl list` | The onboard card is configured by `10-wired.network`. The added card has no configuration from it | A26 |
| 3.2 | Bind the added card to `vfio-pci`, then run `networkctl list` | The bound card does not appear, and the onboard card still works | A26 |

## 4. Secure Boot

Run sections 1 and 2 first, with Secure Boot on or off. Then turn Secure Boot on
in the firmware menu, and leave the keys as they are. If the host does not boot,
turn Secure Boot off again. The virtual machine tests already show that the
firmware chain works, so a failure here points to the real firmware.

| # | Check | Expected result | Open point |
| --- | --- | --- | --- |
| 4.1 | Boot the installer stick with Secure Boot on | The banner appears. The first boot has one extra reboot (the shim fallback) | A33 |
| 4.2 | Boot the host disk with Secure Boot on | A login prompt, within 1 minute of the extra reboot | A33 |
| 4.3 | `mokutil --sb-state` | `SecureBoot enabled` | |
| 4.4 | `cat /sys/kernel/security/lockdown` | `[integrity]` is marked | |
| 4.5 | `bootctl status` | `Secure Boot: enabled (user)`, and the loader is `systemd-boot` | |
| 4.6 | Install `fwupd` by hand, then run `fwupdmgr get-devices` and `fwupdmgr get-updates` | The tool lists a `db` update for the Microsoft UEFI CA 2023, or it says that none is available | A34 |
| 4.7 | After the update of check 4.6 (if one exists), run `mokutil --db` and reboot | `Microsoft UEFI CA 2023` is in the list, and the host still boots | A34 |
| 4.8 | After the cards are in the host, bind a card to `vfio-pci`, start a guest with it, and read `dmesg` | The guest starts, and `dmesg` shows no lockdown message about the card | A32 |
