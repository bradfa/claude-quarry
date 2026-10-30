# Guest storage, snapshots, and recovery

The guest has a read-only base image, a throwaway overlay for the system, and a
separate persistent data disk. A reset removes system damage, and it keeps the
work and the login. All points on this page are design intent. None is tested
[A09].

## Design

- **Host storage.** The images live on the XFS VM storage partition of the host
  (see `host-baseline.md`). The virtual size of each disk is a hard limit. A
  sparse qcow2 file cannot grow past it.
- **Base image.** Build it with debos from the x86_64 UEFI recipe. It needs a
  partition table, a UEFI boot loader (OVMF on the host), a kernel, and the
  packages for Yocto, tmux, dnsmasq, and nfs-kernel-server. These changes apply
  to the guest:
  - Use the suite `trixie` with the security and updates repositories.
  - Remove `avahi-daemon` and `ntp`. Add `chrony` and `qemu-guest-agent`.
  - Replace the root password with a non-root user that has an SSH key. Claude
    Code and bitbake refuse root.
  - Keep the image small, because the data disk is separate.
  - Treat the finished file as immutable. A rebuild makes a new file with a new
    name.
- **Session overlay.** A qcow2 file with the base image as its backing file. All
  system writes of the guest go to the overlay. To recover, delete the overlay
  and make a new one. The base image must never change while an overlay depends
  on it.
- **Data disk.** A second virtual disk, formatted ext4 and mounted in the guest.
  It holds the workspace, the Yocto download directory, the sstate cache, the
  Claude configuration directory (`~/.claude`), and the SSH host keys. The
  Claude login and the guest identity survive a reset. `first-boot.service` runs
  again after every overlay reset, so the SSH host keys must live on the data
  disk. Otherwise the host sees a new key after each reset.
- **No sharing at first.** Guests do not share downloads or sstate. Each guest
  fetches over the NAT network. The download directory needs no cleanup,
  because a rebuilt data disk starts empty. sstate expiry belongs in each
  project configuration, not in this system setup. oe-core probably ships
  `scripts/sstate-cache-management.sh` [A10]. The size of the data disk is the
  system-level limit.
- **Snapshots.** Before a risky experiment, add a new overlay on top of the
  current one. Before each session, copy the data disk while the guest is
  stopped. On XFS, `cp --reflink=always` should be instant and use almost no
  space [A11]. Saving the full guest state to disk (libvirt managed save,
  hibernate) probably does not work with passthrough devices, so do not plan on
  it [A12].
- **Backup.** Copy the data disk while the guest is stopped, or use rsync to
  copy the workspace to the host over SSH.
- **Size.** A Yocto build tree can need tens of GB, and over 100 GB in some
  cases. Set the size of the data disk so that it leaves room for the overlays
  and the checkpoint copies.

Guest disk I/O is probably slower than native I/O [A01]. The host disk is a
spinning disk, so builds are slow.

## Risks

| Risk | Mitigation | Status |
| --- | --- | --- |
| Claude corrupts the overlay or the data disk | An immutable base image, a disposable overlay, and a reflink copy of the data disk before each session | Designed, untested |

## Sources

- None. This page holds design intent.
