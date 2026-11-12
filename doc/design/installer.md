# USB installer

A small USB installer writes the host baseline image to the disk of the host.
`image/installer.yaml` builds it, and `image/build.sh` builds it after the host
image.

**The install erases the whole target disk.** The README must say this in plain
words, both in its warning and in the deploy steps.

## Design

- The installer is a small Debian 13 system with `bmaptool`, the `zstd`
  program, the compressed host image, the `.bmap` file of that image, and one
  install script (`quarry-install`).
- The recipe copies `host.img.zst` and `host.bmap` from the artifact directory
  (`$ARTIFACTDIR`) into `/usr/share/quarry`. The installer recipe needs no
  include of the host recipe. `image/build.sh` builds the two recipes in a
  fixed order: the host image first, then the installer.
- `bmaptool` reads a `.zst` image with the `.bmap` file of the uncompressed
  image. The installer needs no space to unpack the image. `bmaptool` runs the
  `zstd` program for this, so the installer has the `zstd` package.
- The host recipe makes the `.bmap` file first and then runs `zstd`. The first
  version used `gzip`, and it needed about 2 minutes on the 34 GB image. `zstd`
  is much faster on this mostly empty image.
- The installer boots by UEFI with systemd-boot, like the host. Its ESP is 512
  MiB, because it holds one kernel. It has the same Secure Boot chain as the
  host (the shim, the signed `systemd-boot`, and the signed kernel), so the
  stick boots with Secure Boot on and off. See `host-baseline.md`.
- The installer logs in as root on the console without a password, on tty1 and
  on the serial ports. It has no network service. The user needs physical
  access to the stick.

## The install script

The user runs `quarry-install /dev/DISK`. The script never runs at boot. It
does these steps in order:

1. It checks the argument. It refuses a partition, a path that is not a block
   device, and a disk that has a mounted file system. The disk that the
   installer booted from has a mounted file system, so the script refuses it.
2. It checks that the disk is not smaller than the image. It reads the image
   size from the `.bmap` file. It does not check for the space that the first
   boot needs for the swap and VM storage partitions, so a disk with too little
   free space boots without them. After the first boot, check with `lsblk`.
3. It prints the model, the serial number, the size, and the partitions of the
   disk.
4. It asks the user to type one of the names of the disk in `/dev/disk/by-id`.
   A disk with no by-id name (for example a virtual disk with no serial number)
   is confirmed with the device path.
5. It runs `wipefs` on the disk, and then `bmaptool copy` with the `.bmap`
   file.

`bmaptool` does not write blocks that are empty in the image. Old data of the
target disk stays in those blocks. `wipefs` removes the file system signatures
only. This does not erase old data. Say this in the README if the old disk held
secrets.

## Build settings

- `INSTALLER_SIZE` sets the installer image size. The default is 8 GB. The
  compressed host image must fit with the installer system. Raise the value if
  the build stops because the file system is full.
- By default, debos keeps the root file system tree in the RAM of its build
  machine (2 GB), and the compressed host image does not fit there. The build
  uses `--scratchsize` to keep the tree on disk. The tree always fits in the
  installer image, so `INSTALLER_SIZE` is a safe size.
- The build machine needs `zstd`.
- The installer boots in QEMU, and `bmaptool` reads the `.zst` image. The test
  suite checks this.

## The shim

The installer has the same Debian shim as the host. With the build setting
`SHIM_REMOVE_SIGNATURE` (`2011` or `2023`), the recipe removes one of the two
Microsoft signatures from the shim in the ESP, because some firmware rejects a
file with two (see `host-baseline.md`). The installer never updates its
packages, so it has no apt hook. With `2011`, the firmware needs the 2023 CA in
its `db`. A PC without it shows a red box, so turn Secure Boot off to install,
update `db` on the host with `fwupdmgr update`, and turn Secure Boot on.

## Not verified

- The real firmware boots the installer through the removable-media path in the
  ESP [Q6]. With Secure Boot on, this path holds the shim, and the shim
  fallback makes the boot entry [A33].

## Tests

`test/test_installer.py` tests the installer in QEMU. It writes the host image
to a virtual disk and boots that disk. Both boots use the Secure Boot firmware.
`test/README.md` explains how to run it.
The checks on the real host are in `test/manual/real-host.md`.

## Sources

- `bmaptool copy --help` and the `TransRead.py` module of `bmaptool` 3.9 (the
  formats and the `zstd` program).
