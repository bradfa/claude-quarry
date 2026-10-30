# Host baseline

The runbook starts from a fixed host baseline that the owner controls. The
baseline is a debos image. `image/host.yaml` builds it. The USB installer
writes it to the host disk (see `installer.md`).

## Requirements for the host

- A UEFI PC with CPU virtualization and an IOMMU (see `passthrough.md`).
- Debian 13 (trixie).
- One wired network connection to the office LAN. The reference host uses its
  onboard Ethernet port (`eno1`).
- Secure Boot is off on the reference host. The baseline does not need it to be
  on or off.

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
| Storage | No LVM. A fixed-size root, a swap partition, and an XFS partition for VM storage that fills the rest of the disk. |
| Network tool | `systemd-networkd` for everything. The image removes `ifupdown`. |
| Host access | No root login and no passwords. The first user is in the `sudo` group and logs in with an SSH key. |
| `sudo` | The forwarded SSH agent gates `sudo` (`pam_ssh_agent_auth`). The build variable `SUDO_MODE=nopasswd` removes the check. |
| Time sync | `chrony` with the global `pool.ntp.org` pool. `chrony` handles a bad clock better than `ntpd`. |
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

### Network and services

- `systemd-networkd` configures every wired NIC with DHCP. The match uses the
  type `ether` and the name pattern `en*`, so the image holds no NIC name.
- `systemd-networkd-wait-online` waits for any one link, not for all links.
- `systemd-resolved` provides DNS, and `/etc/resolv.conf` links to its stub
  file.
- The recipe purges `ifupdown`, which the base system installs. Two network
  managers must not run together.
- `chrony` keeps the time. It steps the clock when the offset is large during
  the first updates.
- `openssh-server` is on. The SSH configuration has no root login and no
  password login.
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
  fails without an agent.
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
  [Q6].

## Risks

| Risk | Mitigation | Status |
| --- | --- | --- |
| Builds are slow on the spinning disk and 15 GiB of RAM | Start small, measure, and add an SSD later | Accepted for now |

## Tests

`doc/test-host-image.md` tests the image in QEMU.

## Sources

- The `debos-configs` repository (recipes).
- The Linux source file `arch/x86/kernel/cpu/feat_ctl.c` (the `vmx` flag):
  <https://raw.githubusercontent.com/torvalds/linux/master/arch/x86/kernel/cpu/feat_ctl.c>
- Debian 13 KVM host checks: <https://computingforgeeks.com/?p=21285>
- The host measurements in `host-discovery.txt` and `host-discovery-2.txt`.
