# Test of the USB installer in a virtual machine

This page tests `image/installer.yaml` and `quarry-install` before they go on
the real host. You run each step and write the real result in the Result
column. A step passes only when the real result matches the expected result.

The test uses QEMU with UEFI firmware (OVMF). A sparse file is the USB stick.
Another sparse file is the empty target disk. Run `doc/test-host-image.md`
first. The host image must pass that test before you test the installer.

## Status

Not run. The recipe passed `debos --dry-run` and the script passed
`shellcheck`. Nothing else has run.

These points are untested assumptions:

- debos gives `$ARTIFACTDIR` to a `run` action that has `chroot: false`. The
  installer recipe uses it to copy the host image.
- The `systemd-boot` package installs the boot loader in the mounted ESP of the
  installer, as it does for the host image.
- The installer starts on the real host by the removable-media path in the ESP.
  Only the real host can answer this.

## Prerequisites

The same as `doc/test-host-image.md`, and the `zstd` program on the build
machine. The `image/build.conf` file must hold
`ADMIN_USER` and `ADMIN_SSH_KEY_FILE`.

## 1. Build the images

```
KERNEL_CMDLINE_EXTRA="console=tty0 console=ttyS0,115200" image/build.sh
ls -lh image/build/
```

The variable gives both images a serial console, so `-nographic` shows the boot
messages. The script builds the host image and then the installer.

| # | Check | Expected result | Result |
| --- | --- | --- | --- |
| 1.1 | `image/build.sh` exit code | 0. The log shows the `cp -v` line for `host.img.zst` and `host.bmap` | Not run |
| 1.2 | `ls -lh image/build/` | `host.img.zst`, `installer.img`, and `installer.bmap` exist, with `host.img` and `host.bmap`. `installer.img` is 8 GB (sparse) | Not run |

If the installer build stops because the root file system is full, set
`INSTALLER_SIZE` to a larger value in `image/build.conf`.

## 2. Make the test media

```
cd ~/vm-test
bmaptool copy ~/path/to/claude-quarry/image/build/installer.img usb.img
truncate -s 100G target.img
truncate -s 10G small.img
cp /usr/share/OVMF/OVMF_VARS_4M.fd vars-usb.fd
```

`usb.img` is the USB stick. `target.img` is the empty disk that the installer
fills. `small.img` is too small for the image.

## 3. Boot the installer and write the image

```
qemu-system-x86_64 -enable-kvm -machine q35 -cpu host -smp 2 -m 4096 \
    -drive if=pflash,format=raw,readonly=on,file=/usr/share/OVMF/OVMF_CODE_4M.fd \
    -drive if=pflash,format=raw,file=vars-usb.fd \
    -drive if=none,format=raw,id=usb,file=usb.img \
    -device virtio-blk-pci,drive=usb,serial=USBSTICK,bootindex=0 \
    -drive if=none,format=raw,id=target,file=target.img \
    -device virtio-blk-pci,drive=target,serial=TARGETDISK0001 \
    -drive if=none,format=raw,id=small,file=small.img \
    -device virtio-blk-pci,drive=small,serial=SMALLDISK0001 \
    -nographic
```

The installer logs in as root on the console without a password. To stop
QEMU, press Ctrl-a and then x. The disk names below are the usual ones for
this command (`vda` is the stick, `vdb` is the target, and `vdc` is the small
disk). Check the names with `lsblk` first.

| # | Command | Expected result | Result |
| --- | --- | --- | --- |
| 3.1 | Watch the boot | systemd-boot starts, then Linux, then a root shell with the installer banner and a list of the 3 disks | Not run |
| 3.2 | `quarry-install` | The usage message, and exit code 1 | Not run |
| 3.3 | `quarry-install /dev/vda1` | It refuses, because the argument is a partition | Not run |
| 3.4 | `quarry-install /dev/vda` | It refuses, because the disk has mounted file systems | Not run |
| 3.5 | `quarry-install /dev/vdc` | It refuses, because the disk is smaller than the image | Not run |
| 3.6 | `quarry-install /dev/vdb`, then type `wrong` | It shows the model, the size, and the name `virtio-TARGETDISK0001`. It says that nothing was written. `lsblk /dev/vdb` shows no partitions | Not run |
| 3.7 | `quarry-install /dev/vdb`, then type `virtio-TARGETDISK0001` | It writes the image. `bmaptool` reports the copy and the checksum check. Exit code 0 | Not run |
| 3.8 | `lsblk -o NAME,SIZE,PARTLABEL /dev/vdb` | 2 partitions: ESP 2G and root about 30G. The rest of the disk is free | Not run |

Stop QEMU after step 3.8.

## 4. Boot the installed disk

```
cd ~/vm-test
cp /usr/share/OVMF/OVMF_VARS_4M.fd vars-target.fd
qemu-system-x86_64 -enable-kvm -machine q35 -cpu host -smp 2 -m 4096 \
    -drive if=pflash,format=raw,readonly=on,file=/usr/share/OVMF/OVMF_CODE_4M.fd \
    -drive if=pflash,format=raw,file=vars-target.fd \
    -drive if=virtio,format=raw,file=target.img \
    -nic user,model=virtio-net-pci,hostfwd=tcp::2226-:22 \
    -nographic
```

Use SSH from another terminal:

```
ssh -A -p 2226 -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no ADMIN_USER@localhost
```

| # | Command | Expected result | Result |
| --- | --- | --- | --- |
| 4.1 | SSH login with the key | It works within 1 minute | Not run |
| 4.2 | `lsblk -o NAME,SIZE,FSTYPE,PARTLABEL,MOUNTPOINTS` | 4 partitions: ESP 2G, root about 30G, `swap` 4G, `vmdata` about 64G (XFS) | Not run |
| 4.3 | `sudo swapon --show` | The `swap` partition is active | Not run |
| 4.4 | `systemctl --failed` | `0 loaded units listed` | Not run |

## 5. A disk without a by-id name

Start the installer as in step 3, but remove the `serial=TARGETDISK0001`
option. The target disk then has no name in `/dev/disk/by-id`.

| # | Command | Expected result | Result |
| --- | --- | --- | --- |
| 5.1 | `quarry-install /dev/vdb` | It says that the disk has no by-id name. It asks for the device path | Not run |
| 5.2 | Type `/dev/vdb` | It writes the image, as in check 3.7 | Not run |

## Risks and open points

1. **The installer boot on real firmware.** The installer, like the host
   image, relies on the removable-media path in the ESP. Open for the real
   host.
2. **Stale data in unmapped blocks.** `bmaptool` does not write the blocks that
   are empty in the image. The old data of the target disk stays there. The
   script runs `wipefs` first, which removes the file system signatures only.
   This is as safe as a normal `bmaptool` flash, but it does not erase old
   data. Say this in the runbook if the old disk held secrets.
3. **The size of the installer.** `INSTALLER_SIZE` is 8 GB by default. The
   compressed host image must fit with the installer system. Check the real
   size of `host.img.zst` in check 1.2.
