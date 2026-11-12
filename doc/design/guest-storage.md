# Guest storage, snapshots, and recovery

The guest has a read-only base image, a throwaway overlay for the system, and a
separate persistent data disk. A reset removes system damage, and it keeps the
work and the login. All points on this page are design intent. None is tested
[A09].

## Design

- **Host storage.** The images live on the XFS VM storage partition of the host
  (see `host-baseline.md`). The virtual size of each disk is a hard limit. A
  sparse qcow2 file cannot grow past it.
- **Base image.** Build it on the build machine with `image/guest.yaml` (see
  `image/build.sh`), and copy the file to the VM storage of the host. It holds
  the operating system only: a partition table, a UEFI boot loader (OVMF on the
  host), a kernel, the Yocto build packages, tmux, and Claude Code. The
  build variable `GUEST_EXTRA_PACKAGES` adds the packages of one project.
  `dnsmasq` and `nfs-kernel-server` wait for the work on the boards (see
  `hil-services.md`). The size of the image is for the system only (default 32
  GB, sparse). The Yocto trees are on the data disk. These changes apply to the
  guest:
  - Use the suite `trixie` with the security and updates repositories.
  - Remove `avahi-daemon` and `ntp`. Add `chrony` and `qemu-guest-agent`.
  - Replace the root password with two non-root users that have an SSH key: the
    Claude account and the admin account (see `guest-access.md`). Claude Code
    and bitbake refuse root.
  - Keep the image small, because the data disk is separate.
  - Treat the finished file as immutable. A rebuild makes a new file with a new
    name.
- **Session overlay.** A qcow2 file with the base image as its backing file. All
  system writes of the guest go to the overlay. To recover, run
  `quarry-guest reset`. It replaces the overlay and keeps the data disk. The
  base image must never change while an overlay depends on it.
- **Data disk.** A second virtual disk, formatted ext4 and mounted at `/data` in
  the guest. It holds the workspace (`/data/workspace`, owned by the Claude
  account), the Yocto download directory, the sstate cache, the Claude
  configuration directory (`/data/claude-config`, see `claude-code.md`), and the
  SSH host keys. The Yocto directories are subdirectories of the workspace, and
  Claude makes them. `/data` itself belongs to root, so Claude cannot rename or
  replace its configuration directory. The home directory of the Claude account
  stays on the overlay. The Claude login and the guest identity survive a reset.
  `first-boot.service` runs again after every overlay reset, so the SSH host
  keys must live on the data disk. Otherwise the host sees a new key after each
  reset.
- **The `quarry-guest` command.** The host image has `/usr/sbin/quarry-guest`
  for the admin account (with `sudo`). `create --base FILE` makes the overlay and
  an empty data disk in `/var/lib/libvirt/images`, and defines the libvirt
  domain. `start`, `stop`, `reset`, `snapshot`, and `status` do the rest. The
  domain has a fixed MAC address, and the `quarry` network gives it the fixed
  address `10.250.0.10`. The host resolves the guest name through `/etc/hosts`.
  The defaults are 10 GiB of RAM, 6 vCPUs, and a 200 GiB data disk. The options
  `--memory`, `--vcpus`, and `--data-size` change them.
- **No sharing at first.** Guests do not share downloads or sstate. Each guest
  fetches over the NAT network. The download directory needs no cleanup,
  because a rebuilt data disk starts empty. sstate expiry belongs in each
  project configuration, not in this system setup. oe-core probably ships
  `scripts/sstate-cache-management.sh` [A10]. The size of the data disk is the
  system-level limit.
- **Snapshots.** Before a risky experiment, add a new overlay on top of the
  current one. Before each session, run `quarry-guest snapshot` while the guest
  is stopped. It copies the data disk with `cp --reflink=always`. On the XFS
  partition, the copy shares its blocks with the data disk, so it needs almost
  no space. Saving the full guest state to disk (libvirt managed save,
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
