# Host baseline

The runbook starts from a fixed host baseline that the owner controls. The
baseline is a debos image. `image/host.yaml` builds it. The USB installer
writes it to the host disk (see `installer.md`).

## Requirements for the host

- A UEFI PC with CPU virtualization and an IOMMU (see `passthrough.md`).
- Debian 13 (trixie).
- One wired network connection to the office LAN. The reference host uses its
  onboard Ethernet port (`eno1`).
- Secure Boot can be on or off. The baseline boots in both cases. It is off on
  the reference host for now. The test suite always boots the image with Secure
  Boot on.

The reference host is an HP EliteDesk with an Intel i7-4770 (4 cores, 8
threads), a Q87 chipset, 15 GiB of RAM, and one 1 TB spinning disk. Its
firmware is UEFI 2.31. The owner accepts slow builds on the spinning disk for
now. An SSD helps most. Measure a real build before the owner decides.

`/dev/kvm` exists on the reference host, and the `kvm_intel` module is loaded.
On current kernels, the kernel clears the `vmx` flag when the firmware turns
off VMX, so the `kvm-ok` tool is not needed.

## Decisions

| Topic | Decision |
| --- | --- |
| Boot | UEFI and systemd-boot. No GRUB. |
| Secure Boot | The image boots with Secure Boot on and off. The chain is the Microsoft shim, `systemd-boot`, and the kernel. Debian signs all three, so updates need no key of the owner. See Secure Boot below. |
| Storage | No LVM. A fixed-size root, a swap partition, and an XFS partition for VM storage that fills the rest of the disk. |
| Network tool | `systemd-networkd` for everything. The image removes `ifupdown`. |
| Host access | No root login and no passwords. The first user is in the `sudo` group and logs in with an SSH key. |
| `sudo` | The forwarded SSH agent gates `sudo` (`pam_ssh_agent_auth`). The build variable `SUDO_MODE=nopasswd` removes the check. |
| Time sync | `chrony` with the global `pool.ntp.org` pool. `chrony` handles a bad clock better than `ntpd`. |
| Updates | `unattended-upgrades` installs the updates of the Debian and security suites every day. It never reboots the host. |
| Image settings | The build script takes the user name, the SSH key, and other settings from environment variables, a config file, or a prompt. The recipes hold no user name and no key. |
| Host disk | Use the existing spinning disk first. |

## The image

The recipe is an adaptation of the x86_64 UEFI recipes in the `debos-configs`
repository. It installs Debian 13 with the `main`, `contrib`, `non-free`, and
`non-free-firmware` components, the `trixie-updates` suite, and the
`trixie-security` suite. The image has no libvirt, so the runbook can show those
steps. Tailscale is an optional overlay (see `network.md`).

### Disk layout

| Partition | Size | File system | Made by |
| --- | --- | --- | --- |
| ESP | 2 GiB | FAT | The image |
| Root | About 30 GB | ext4 | The image |
| `swap` | 4 GiB | swap | `systemd-repart`, on the first boot |
| `vmdata` | The rest of the disk (at least 16 GiB) | XFS | `systemd-repart`, on the first boot |

Rules for the layout:

- The image size is 34 GB by default (`IMAGE_SIZE`). Root does not grow.
- The ESP is large because Debian keeps one copy of each kernel and initrd in
  `/boot` and another copy in the ESP.
- The partition type GUIDs come from the Discoverable Partitions Specification,
  so systemd finds the ESP and the root partition by type.
- The ESP and root start on 1 MiB boundaries. The partitions that
  `systemd-repart` adds start on 4 KiB boundaries.
- The definitions for `systemd-repart` are in `/etc/repart.d`.
- `/etc/fstab` activates the swap partition and mounts `vmdata` at
  `/var/lib/libvirt`, both by partition label.
  `systemd-gpt-auto-generator` runs before `systemd-repart`, so it cannot find
  the swap partition on the first boot. The `fstab` line gives swap from the
  first boot.
- The `vmdata` mount has `nofail`. A missing or damaged partition does not stop
  the boot, so the host stays reachable. Without `nofail`, the boot ends in
  emergency mode, and the locked root account gives no shell. The owner chose
  this because the host always has a console path: a monitor, a KVM switch, a
  serial console server, or a BMC.
- The runbook adds `RequiresMountsFor=/var/lib/libvirt` to the libvirt units.
  Then libvirt cannot write VM disks to the root file system when the mount is
  missing.
- A runaway guest cannot fill the host root, because VM storage is a separate
  file system.

### Boot

- The recipe installs `systemd-boot` after the kernel. The package makes the
  boot entries.
- The entries must not hold `systemd.machine_id=`. The recipe removes that
  option, because it forces the build-time ID on every host.
- The ESP mounts with `umask=0077`. The ESP holds the boot random seed, and a
  FAT file system has no file modes.
- The kernel command line has no `console=` option, so a host with a monitor
  uses the monitor. The build variable `KERNEL_CMDLINE_EXTRA` adds options, for
  example a serial console for a virtual machine test.

### Secure Boot

The image boots with Secure Boot on and off. The shim does nothing when Secure
Boot is off.

- The chain: the firmware trusts the Microsoft UEFI CA, and Microsoft signs the
  Debian `shim`. The `shim` holds the Debian CA. Debian signs `systemd-boot` and
  the kernel. The firmware starts the `shim`, the `shim` starts `systemd-boot`,
  and `systemd-boot` starts the kernel.
- The recipe installs `shim-signed` and `systemd-boot-efi-amd64-signed` in the
  same step as `systemd-boot`. The scripts of the `systemd-boot` package then
  put the signed `shim` at `EFI/BOOT/BOOTX64.EFI` (the removable-media path) and
  in `EFI/debian`. A dpkg trigger keeps these files current after a package
  update, so `unattended-upgrades` needs no extra step.
- A new host has no boot entry. On the first boot, the firmware starts the
  `shim` at the removable-media path, and the `shim` starts `systemd-boot`. The
  file `EFI/debian/BOOTX64.CSV` names `systemd-boot` as the second stage. By the
  second boot, the firmware variables hold an entry named `Debian` that starts
  `EFI/debian/shimx64.efi`. In the virtual machine tests, the first boot had no
  extra reboot. Nobody traced which part of the `shim` makes the entry. The
  real firmware can behave differently [A33].
- The recipe does not install `efibootmgr`. The package scripts would then write
  boot entries during the build. A build that runs on the build machine, without
  the virtual machine of `debos`, could reach the firmware variables of that
  machine.
- With Secure Boot on, the kernel starts in lockdown mode. Lockdown blocks
  unsigned kernel modules, access to `/dev/mem`, and the start of an unsigned
  kernel with `kexec`. The image has no module that Debian does not sign. It is
  not verified that lockdown allows libvirt and VFIO passthrough [A32].

#### Firmware with no keys

A firmware can have no Microsoft key in its database. On the HP EliteDesk of the
owner, with the latest BIOS from HP (American Megatrends 4.654, UEFI 2.31), the
setting "Key Ownership" has two values.
"HP Keys" rejects the `shim` of the installer (a red "Secure Boot Violation"
box). "Custom Keys" leaves the firmware in Setup Mode with an empty database
(`mokutil --sb-state` shows `SecureBoot disabled` and `Platform is in Setup
Mode`), and the BIOS has no menu to import a key. The firmware then boots every
file, so Secure Boot does not enforce anything. The fix is a script of the host
image.

- Run `sudo quarry-enroll-secure-boot-keys` on the host while the firmware is in
  Setup Mode, and then reboot. The script stops with an error in any other
  state.
- It writes the Microsoft UEFI CA 2011 and 2023 to `db`, and the Microsoft KEK
  CA 2011 and KEK 2K CA 2023 to `KEK`. The KEK lets `fwupd` apply later updates
  of `db` [A34]. It makes a new Platform Key (PK), writes it last (this ends
  Setup Mode), and deletes the private key. No other signing key exists on the
  host. To change the keys later, put the firmware in Setup Mode again.
- The certificates are in `/usr/local/share/quarry/secureboot`, and the script
  checks the SHA-256 fingerprint of each one before it writes anything. Each
  fingerprint also matches a certificate in a Debian package (see the script).
  The script adds no Windows key, so the host cannot start Windows.
- The virtual machine tests (`test/test_enroll_keys.py`) run the script on OVMF
  in Setup Mode, reboot, and check that Secure Boot is on and that the host
  still boots. The real firmware can differ in how it accepts the variable
  writes [A38].
- The installer has the same problem as the host. With a firmware in Setup Mode,
  the installer starts. After the keys are in, the installer stick also passes
  the check, because it has the same Microsoft-signed `shim`.

What Secure Boot does not verify: the initrd, the kernel command line (in
`/boot/efi/loader/entries`), and the root file system. An attacker who has root
on the host can still change them and keep a foothold. Only a verified root file
system (dm-verity) closes this gap. It needs image-based updates, and it stops
the daily `apt` updates. The owner chose the daily updates. The main attack on
this host is a bug in QEMU or in the kernel, and a fast patch is the best
defense. The recovery for a host that someone may have changed is the USB
installer.

The reference firmware, from commands that the owner ran on 2026-11-02:

| Item | Content |
| --- | --- |
| Platform key | HP |
| KEK | Microsoft KEK CA 2011 and an HP key |
| `db` | Microsoft UEFI CA 2011, Microsoft Windows Production PCA 2011, and an HP key |
| Debian `shim` | Two signatures: one from the UEFI CA 2011 and one from the UEFI CA 2023 |

- The firmware has the 2011 CA, so it accepts the first signature of the `shim`.
  The 2011 certificates are past their "Not After" date (June 2026). A firmware
  has no trusted clock, and it should ignore the date. A real boot shows this
  [A33].
- A later `shim` can carry only the 2023 signature. The firmware then needs the
  Microsoft UEFI CA 2023 in its `db`. Microsoft publishes a `db` update that the
  KEK CA 2011 signs, and `fwupd` can apply it. Do this before the host takes a
  `shim` with one signature [A34].

### Network and services

- `systemd-networkd` configures every wired NIC with DHCP. The match uses the
  type `ether` and the name pattern `en*`, so the image holds no NIC name.
- `systemd-networkd-wait-online` waits for any one link, not for all links.
- `systemd-resolved` provides DNS, and `/etc/resolv.conf` links to its stub
  file.
- `systemd-resolved` and `systemd-networkd` both have `MulticastDNS=yes`. The
  host then answers mDNS queries and shows as `<host name>.local` on the LAN.
  It listens on UDP port 5353 on the LAN. The image has no DHCP lease list to
  look at, and not every user can read one. The daily machine needs an mDNS
  client to resolve the name [A37].
- `quarry-login-banner.service` writes `/run/issue.d/50-quarry-network.issue`
  at boot and on each address or link change, and then runs `agetty --reload`.
  The login prompt of every console, the monitor and a serial line, then lists
  each network card with its state and addresses. It also shows the `ssh -A`
  command for the admin user, with the `.local` name and each IPv4 address. The
  `\4` escape of `agetty` shows only the first interface, so a generated file
  is needed. A card that has no device link (a bridge or a tunnel) is not
  listed [A36].
- The recipe purges `ifupdown`, which the base system installs. Two network
  managers must not run together.
- `chrony` keeps the time. It steps the clock when the offset is large during
  the first updates.
- `openssh-server` is on. The SSH configuration has no root login and no
  password login.
- The package defaults of `unattended-upgrades` do the update work. The image
  has no configuration file for it. The two `apt` timers run once a day. The
  defaults cover the base suite and `trixie-security`, but not `trixie-updates`.
  An automatic reboot is off, because a reboot stops the guest and any run in
  it. After a kernel update, the owner reboots the host when no run is active.
  `/var/run/reboot-required` shows that a reboot is due.
- The recipe installs `amd64-microcode`, `intel-microcode`, and the non-free
  firmware for Realtek and miscellaneous devices.

### Identity

The build removes the machine ID, the SSH host keys, and the boot random seed.
Each host makes its own on the first boot. `first-boot.service` runs
`ssh-keygen -A` when the host keys are missing.

### Access

- Root has no password and cannot log in.
- The first user has an SSH key and is in the `sudo` group.
- With `SUDO_MODE=agent` (the default), `sudo` asks the forwarded SSH agent. It
  fails without an agent. `timestamp_timeout=0` turns off the `sudo` cache, so
  every `sudo` command asks the agent. If a guest escape is suspected, the owner
  closes the agent connection (or locks the Yubikey), and `sudo` stops at once.
  The default cache of 15 minutes would keep `sudo` working without the agent.
- With `SUDO_MODE=nopasswd`, the `sudo` group uses `sudo` without a check.

### Build settings

`image/build.sh` takes each setting from an environment variable, then from
`image/build.conf`, and then from a prompt on a terminal. A required setting
with no value stops the script. `image/build.conf.example` documents each
setting.

## Known issues

- The boot entry lives in a directory that has the build-time machine ID. After
  the first boot, a kernel update uses the real machine ID, and the old
  directory stays in the ESP. A fixed entry token in `/etc/kernel/entry-token`
  would avoid this. The owner chose not to add it now. Nobody has tested it.
  The cost is an unused directory in the ESP.
- The ESP mount point has a trailing slash in `/etc/fstab`, so `bootctl` shows
  double slashes. This is cosmetic.

## Not verified

- The `en*` match does not match a NIC that is bound to `vfio-pci` [A26].
- The real firmware boots the image through the removable-media path in the ESP
  [Q6]. With Secure Boot on, this path holds the `shim`, and the `shim` fallback
  makes the boot entry [A33].
- Lockdown mode allows libvirt and VFIO passthrough [A32].
- The Microsoft UEFI CA 2023 update works on the reference firmware [A34].

## Risks

| Risk | Mitigation | Status |
| --- | --- | --- |
| Builds are slow on the spinning disk and 15 GiB of RAM | Start small, measure, and add an SSD later | Accepted for now |
| A `shim` update has only the 2023 signature, and the firmware has no 2023 CA. The host then does not boot after the next reboot. | Add the 2023 CA to the firmware `db` first [A34] | Open |
| Secure Boot does not verify the initrd, the command line, and the root file system | Daily updates and fast patches. The USB installer is the recovery | Accepted by the owner |

## Tests

`test/test_host_image.py` tests the image in QEMU. `test/README.md` explains how
to run it. The tests boot every machine with the Secure Boot firmware. Step 10
checks the chain, and it shows that the firmware refuses a kernel and a
`systemd-boot` without their signatures. The checks on the real host are in
`test/manual/real-host.md`.

## Sources

- The `debos-configs` repository (recipes).
- The Linux source file `arch/x86/kernel/cpu/feat_ctl.c` (the `vmx` flag):
  <https://raw.githubusercontent.com/torvalds/linux/master/arch/x86/kernel/cpu/feat_ctl.c>
- Debian 13 KVM host checks: <https://computingforgeeks.com/?p=21285>
- The Debian wiki page about Secure Boot (the chain, signed kernels, lockdown,
  and `systemd-boot` with the `shim`): <https://wiki.debian.org/SecureBoot>
- The maintainer script of the `systemd-boot` package (the files that it puts
  in the ESP, and its trigger):
  <https://sources.debian.org/src/systemd/257.13-1~deb13u1/debian/systemd-boot.postinst/>
- The output of `mokutil --pk`, `--kek`, and `--db`, and of `sbverify --list`
  for `shimx64.efi.signed`, that the owner ran on the reference host on
  2026-11-02.
