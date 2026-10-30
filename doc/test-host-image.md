# Test of the host image in a virtual machine

This page tests `image/host.yaml` before it goes on the real host. You run each
step and write the real result in the Result column. A step passes only when the
real result matches the expected result.

The test uses QEMU with UEFI firmware (OVMF) and a 100 GB sparse disk. The
disk is larger than the image, so the first-boot growth of the layout is
tested too.

## Status

First run on 2026-10-29, in a QEMU virtual machine on the owner's daily
machine. Steps 1 to 8 pass. Disks A and B booted from one image and have
different machine IDs and different SSH host keys. The `nopasswd` build (step
8) passes too. It also showed that the recipe purges `ifupdown` (check 4.15)
and that the swap is active on the first boot.

Open:

- Step 9 (a disk with no free space) has not run. It tests the `nofail` option
  on the `vmdata` mount.
- Nothing has run on the real host yet. The `en*` network match and the
  removable-media boot path need the real hardware (see Risks).

Bugs that the first runs found, all fixed in the recipe:

- `systemd-repart` was not in the package list. It is a separate package in
  Debian 13. Without it, no swap or VM storage partition existed, and the boot
  ended in emergency mode.
- The kernel command line had no console on the serial port, so `-nographic`
  showed no boot messages. The build variable `KERNEL_CMDLINE_EXTRA` sets it.
- The ESP was readable by everyone, which exposes the boot random seed. The
  `fstab` entry now has `umask=0077`.
- The partitions were not aligned to 1 MiB. The recipe now uses sector values.
- `systemd-gpt-auto-generator` runs before `systemd-repart`, so it missed the
  swap partition on the first boot. An `fstab` line now activates the swap.
- `ifupdown` came with the base system next to `systemd-networkd`. The recipe
  now purges it.

## Prerequisites

- `debos`, `bmaptool`, `qemu-system-x86`, and the `ovmf` package.
- Access to `/dev/kvm`.
- Internet access for the build and for the time test.
- An SSH key pair and an SSH agent that holds the key.

## 1. Build the image

```
cp image/build.conf.example image/build.conf
```

Edit `image/build.conf`. Set `ADMIN_USER` and `ADMIN_SSH_KEY_FILE`. Also set
this line. It makes the serial port the system console, so `-nographic` in
step 3 shows the boot messages and the login prompt:

```
KERNEL_CMDLINE_EXTRA=console=tty0 console=ttyS0,115200
```

Then run:

```
image/build.sh
ls -lh image/build/host.img image/build/host.bmap
```

| # | Check | Expected result | Result |
| --- | --- | --- | --- |
| 1.1 | `image/build.sh` exit code | 0. The log shows a `-v` or `echo` line for each file change | Pass |
| 1.2 | `ls` output | Both files exist. `host.img` is 34 GB (sparse) | Pass |

If the build fails, keep the full log. The most likely places are the
`systemd-boot` install and the `sed` on the boot entries (see Risks).

The build log has two known messages that are harmless. `bootctl` warns that
the ESP is world accessible. The build-time mount of the ESP cannot take mount
options, and the installed system mounts the ESP with `umask=0077`. `chrony`
warns about `/var/log/chrony`. The package does that inside the build chroot.

## 2. Write the image to two test disks

Two disks show that each host gets its own machine ID and SSH host keys.

```
mkdir -p ~/vm-test && cd ~/vm-test
for n in a b; do
    bmaptool copy ~/path/to/claude-quarry/image/build/host.img disk-$n.img
    truncate -s 100G disk-$n.img
    cp /usr/share/OVMF/OVMF_VARS_4M.fd vars-$n.fd
done
```

| # | Check | Expected result | Result |
| --- | --- | --- | --- |
| 2.1 | `bmaptool copy` exit code | 0. It reports that it used the `.bmap` file | Not reported |
| 2.2 | `ls -ls disk-a.img` | Apparent size is 100 GB. Disk use is much smaller | Pass. Disk B, not yet booted, used 1.7 GB |
| 2.3 | `sfdisk -d disk-a.img` | The `start=` value of the ESP and of root is a multiple of 2048 (1 MiB). The `start=` value of `swap` and `vmdata` is a multiple of 8 (4 KiB), because `systemd-repart` makes them on the first boot. The ESP type is `C12A7328-F81F-11D2-BA4B-00A0C93EC93B` and the root type is `4F68BCE3-E8CD-4DB1-96E7-FBCAF984B709` | Pass. Starts 2048, 4196352, 66406224, 74794832. The types match |

After the first boot, a disk can use much more space than before. The owner saw
66 GB used on disk A. The cause is not known. The `repart` journal shows that
it finished in about one second, so `repart` did not write the partition. This
is not a problem for the test.

## 3. Boot disk A

```
qemu-system-x86_64 -enable-kvm -machine q35 -cpu host -smp 2 -m 4096 \
    -drive if=pflash,format=raw,readonly=on,file=/usr/share/OVMF/OVMF_CODE_4M.fd \
    -drive if=pflash,format=raw,file=vars-a.fd \
    -drive if=virtio,format=raw,file=disk-a.img \
    -nic user,model=virtio-net-pci,hostfwd=tcp::2222-:22 \
    -nographic
```

The image was built with `KERNEL_CMDLINE_EXTRA` (step 1), so `-nographic` shows
the boot messages in this terminal. To stop QEMU, press Ctrl-a and then x.

The message `systemd-ssh-generator: Failed to query local AF_VSOCK CID` is
expected in this test. QEMU gives the guest no vsock device. The generator
prints the message at every boot and at every `daemon-reload`. It does no harm.

Do not add `systemd.mask=` for a mount unit to the boot entry to get past a
mount problem. A masked mount that `local-fs.target` requires stops that target.
Then systemd does not remount the root file system, and the root file system
stays read-only. Send the boot messages instead.

Root has no password and the administrator has no password, so you cannot log
in on this console. The `login:` prompt is expected. Use SSH from another
terminal. A new host key appears on each boot, so these test commands do not
save host keys:

```
ssh -A -p 2222 -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no ADMIN_USER@localhost
```

| # | Check | Expected result | Result |
| --- | --- | --- | --- |
| 3.1 | The firmware starts systemd-boot, then Linux | The boot menu appears and then the kernel messages and a `login:` prompt appear in the terminal | Pass |
| 3.2 | SSH login with the key | It works within 1 minute | Pass |
| 3.3 | `systemctl --failed` | `0 loaded units listed` | Pass on disk A and on disk B |

## 4. Check the system on disk A

Run these commands in the SSH session.

| # | Command | Expected result | Result |
| --- | --- | --- | --- |
| 4.1 | `lsblk -o NAME,SIZE,FSTYPE,PARTLABEL,MOUNTPOINTS` | 4 partitions: ESP 2G, root about 30G, `swap` 4G, `vmdata` about 64G (XFS) | Pass. 2G, 29.7G, 4G, 64.3G |
| 4.2 | `sudo swapon --show` (a normal user has no `swapon` in the PATH) | The `swap` partition is active on the first boot. The `fstab` line starts it when `systemd-repart` has made the partition | Pass on the first boot of the image that has the `fstab` line |
| 4.3 | `findmnt /var/lib/libvirt` | Type `xfs`, source is the `vmdata` partition | Pass. `/dev/vda4`, `rw` |
| 4.4 | `networkctl status` | One `en*` link, configured by `10-wired.network`. `ip route` has a default route | Pass. `enp0s2` routable, default route with metric 100 |
| 4.5 | `cat /etc/machine-id` | A 32-character ID, not empty | Pass |
| 4.6 | `cat /proc/cmdline` | No `systemd.machine_id=` option | Pass |
| 4.7 | `sudo bootctl list` (the ESP is only readable by root) | At least one entry for the installed kernel | Pass. One entry. The entry has the build-time ID, not the machine ID (see Risks) |
| 4.8 | `chronyc sources` | Servers from `pool.ntp.org` appear. At least one has a `*` or `+` after a few minutes | Pass. Four servers, one `*` |
| 4.9 | `systemctl is-active ssh chrony systemd-networkd systemd-resolved` | 4 lines of `active` | Pass |
| 4.10 | `ls -l /etc/resolv.conf` | A link to `../run/systemd/resolve/stub-resolv.conf` | Pass |
| 4.11 | `hostname` | The `HOST_NAME` value from `build.conf` | Pass. `quarry-host` |
| 4.12 | `findmnt /boot/efi` | Options include `umask=0077` | Pass. `fmask=0077,dmask=0077` |
| 4.13 | `sudo ls -l /boot/efi/loader/random-seed` | The file exists (the first boot made it). No access for group or others | Pass. `-rwx------ root root` |
| 4.14 | `systemctl status systemd-repart.service` and `sudo journalctl -b -u systemd-repart` | The unit exists and ran. The journal shows that it added the `swap` and `vmdata` partitions | Pass |
| 4.15 | `dpkg -s ifupdown; systemctl status networking.service` | `dpkg` reports that the package is not installed. The unit does not exist | Pass on the `nopasswd` build (step 8). `dpkg` reports that `ifupdown` is not installed, and `networking.service` does not exist |

## 5. Check access control on disk A

| # | Command | Expected result | Result |
| --- | --- | --- | --- |
| 5.1 | In the session with `-A`: `sudo true; echo $?` | `0`, and no password prompt | Pass |
| 5.2 | A new session without `-A`: `sudo true` | It asks for a password and fails. It cannot succeed | Pass |
| 5.3 | `ssh -p 2222 root@localhost` (same options as above) | `Permission denied` | Pass |
| 5.4 | `ssh -o PubkeyAuthentication=no -p 2222 ADMIN_USER@localhost` | `Permission denied`. It does not ask for a password | Pass |
| 5.5 | `sudo passwd -S root` | Status `L` (locked) | Pass. `root L` |

## 6. Reboot disk A

Run `sudo systemctl reboot`, then start QEMU again with the same command.

| # | Check | Expected result | Result |
| --- | --- | --- | --- |
| 6.1 | `cat /etc/machine-id` | The same ID as in 4.5 | Pass |
| 6.2 | `sudo journalctl -b -u systemd-repart` | It reports `No changes`, or no change to the partitions | Pass. `No changes.` |
| 6.3 | `systemctl --failed` | `0 loaded units listed` | Pass |
| 6.4 | `sudo swapon --show` | The `swap` partition is active | Pass |

## 7. Boot disk B and compare

Boot disk B with `vars-b.fd` and `disk-b.img`. Use a different forward port, for
example `hostfwd=tcp::2223-:22`.

| # | Command | Expected result | Result |
| --- | --- | --- | --- |
| 7.1 | `cat /etc/machine-id` | A different ID than on disk A | Pass |
| 7.2 | `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub` | A different fingerprint than on disk A | Pass |

## 8. Test the other sudo mode

Set `SUDO_MODE=nopasswd` in `image/build.conf`, or set the variable for one
build: `SUDO_MODE=nopasswd image/build.sh`. Build again, write one disk as in
step 2, and boot it. Use a different forward port, for example
`hostfwd=tcp::2224-:22`. Log in without `-A`. This build also has the `ifupdown`
purge, so check 4.15 and check 4.2 can run on it too.

| # | Command | Expected result | Result |
| --- | --- | --- | --- |
| 8.1 | In a session without `-A`: `sudo -n true; echo $?` | `0`, and no prompt | Pass. `sudo true` works with no password and no SSH agent |
| 8.2 | `ls /etc/security/sudo_authorized_keys` | The file does not exist | Pass |

## 9. Boot a disk with no free space

A disk that has the size of the image leaves no room for the `swap` and
`vmdata` partitions. The `vmdata` mount has `nofail`, so the host must boot and
stay reachable. Use the image from step 8 or from step 1, and a new port.

```
cd ~/vm-test
bmaptool copy ~/path/to/claude-quarry/image/build/host.img disk-d.img
cp /usr/share/OVMF/OVMF_VARS_4M.fd vars-d.fd
```

Do not run `truncate` on `disk-d.img`. Start QEMU as in step 3 with
`disk-d.img`, `vars-d.fd`, and `hostfwd=tcp::2225-:22`. Wait about a minute,
because the mount waits for its device until the 30 second timeout.

| # | Command | Expected result | Result |
| --- | --- | --- | --- |
| 9.1 | SSH login on port 2225 | The login works | Not run |
| 9.2 | `lsblk -o NAME,SIZE,PARTLABEL,MOUNTPOINTS` | Only the ESP and root partitions | Not run |
| 9.3 | `systemctl --failed` | `var-lib-libvirt.mount` failed. Record every other failed unit, for example `systemd-repart.service`, because the recipe does not handle a full disk on purpose | Not run |
| 9.4 | `findmnt /var/lib/libvirt` | No output. The directory exists on the root file system | Not run |

## 10. Test the real host (after the virtual machine passes)

Do this only on the target host. The install erases the whole disk. Use the
USB installer for this (see the installer test steps, which are not written
yet).

## Risks and open points

A virtual machine cannot answer every point. This list shows the state of each
point that rested on documentation before the first run.

1. **Boot entries.** Verified in the virtual machine (checks 3.1 and 4.7). The
   recipe installs `systemd-boot` after the kernel, and trixie makes the
   entries. The entry lives in a directory that has the build-time machine ID.
   After the first boot, a kernel update uses the real machine ID, and the old
   directory stays in the ESP. A fixed entry token in `/etc/kernel/entry-token`
   would avoid this. This is a known issue. The owner chose not to add the
   token now, and nobody has tested it. The cost is an unused directory in the
   ESP, which is 2 GiB.
2. **Machine ID option.** Verified (checks 4.6 and 7.1).
3. **Swap activation.** `systemd-gpt-auto-generator` runs before
   `systemd-repart`, so the first boot had no swap. An `fstab` line fixes it.
   Verified (checks 4.2 and 6.4).
4. **`pam_ssh_agent_auth`.** Verified on trixie (checks 5.1 and 5.2).
5. **The `en*` pattern.** It must not match a NIC that is bound to `vfio-pci`.
   This only shows on the real host. Open.
6. **`debos` value passing.** Verified. The SSH key with spaces reached the
   image (check 3.2).
7. **The removable-media boot path.** The virtual machine started with empty
   firmware variables and still booted, so the fallback path in the ESP works
   in OVMF. Real firmware can differ. Open for the real host.
8. **Missing `vmdata` partition.** The `vmdata` mount has `nofail`, so a
   missing partition does not stop the boot. Without it, the boot would end in
   emergency mode, and a locked root account gives no shell. The runbook must
   make the libvirt units require the mount (`RequiresMountsFor=`), so libvirt
   cannot write VM disks to the root file system. Step 9 tests the boot. Not
   run yet.
