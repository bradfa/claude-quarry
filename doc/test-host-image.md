# Test of the host image in a virtual machine

This page tests `image/host.yaml` before it goes on the real host. You run each
step and write the real result in the Result column. A step passes only when the
real result matches the expected result.

The test uses QEMU with UEFI firmware (OVMF) and a 100 GB sparse disk. The
disk is larger than the image, so the first-boot growth of the layout is
tested too.

## Prerequisites

- `debos`, `bmaptool`, `qemu-system-x86_64`, and the `ovmf` package.
- Access to `/dev/kvm`.
- Internet access for the build and for the time test.
- An SSH key pair and an SSH agent that holds the key.

## 1. Build the image

```
cp image/build.conf.example image/build.conf
```

Edit `image/build.conf`. Set `ADMIN_USER` and `ADMIN_SSH_KEY_FILE`. Then run:

```
image/build.sh
ls -lh image/build/host.img image/build/host.bmap
```

| # | Check | Expected result | Result |
| --- | --- | --- | --- |
| 1.1 | `image/build.sh` exit code | 0. The log shows a `-v` or `echo` line for each file change | |
| 1.2 | `ls` output | Both files exist. `host.img` is 34 GB (sparse) | |

If the build fails, keep the full log. The most likely places are the
`systemd-boot` install and the `sed` on the boot entries (see Risks).

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
| 2.1 | `bmaptool copy` exit code | 0. It reports that it used the `.bmap` file | |
| 2.2 | `ls -ls disk-a.img` | Apparent size is 100 GB. Disk use is much smaller | |

## 3. Boot disk A

```
qemu-system-x86_64 -enable-kvm -machine q35 -cpu host -smp 2 -m 4096 \
    -drive if=pflash,format=raw,readonly=on,file=/usr/share/OVMF/OVMF_CODE_4M.fd \
    -drive if=pflash,format=raw,file=vars-a.fd \
    -drive if=virtio,format=raw,file=disk-a.img \
    -nic user,model=virtio-net-pci,hostfwd=tcp::2222-:22 \
    -nographic
```

Root has no password, so you cannot log in on this console. Use SSH from
another terminal. A new host key appears on each boot, so these test commands
do not save host keys:

```
ssh -A -p 2222 -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no ADMIN_USER@localhost
```

| # | Check | Expected result | Result |
| --- | --- | --- | --- |
| 3.1 | The firmware starts systemd-boot, then Linux | The boot menu appears and then the kernel starts | |
| 3.2 | SSH login with the key | It works within 1 minute | |
| 3.3 | `systemctl --failed` | `0 loaded units listed` | |

## 4. Check the system on disk A

Run these commands in the SSH session.

| # | Command | Expected result | Result |
| --- | --- | --- | --- |
| 4.1 | `lsblk -o NAME,SIZE,FSTYPE,PARTLABEL,MOUNTPOINTS` | 4 partitions: ESP 2G, root 32G, `swap` 4G, `vmdata` about 62G (XFS) | |
| 4.2 | `swapon --show` | The `swap` partition is active | |
| 4.3 | `findmnt /var/lib/libvirt` | Type `xfs`, source is the `vmdata` partition | |
| 4.4 | `networkctl status` | One `en*` link, configured by `10-wired.network`. `ip route` has a default route | |
| 4.5 | `cat /etc/machine-id` | A 32-character ID, not empty | |
| 4.6 | `cat /proc/cmdline` | No `systemd.machine_id=` option | |
| 4.7 | `bootctl list` | At least one entry for the installed kernel | |
| 4.8 | `chronyc sources` | Servers from `pool.ntp.org` appear. At least one has a `*` or `+` after a few minutes | |
| 4.9 | `systemctl is-active ssh chrony systemd-networkd systemd-resolved` | 4 lines of `active` | |
| 4.10 | `ls -l /etc/resolv.conf` | A link to `../run/systemd/resolve/stub-resolv.conf` | |
| 4.11 | `hostname` | The `HOST_NAME` value from `build.conf` | |

## 5. Check access control on disk A

| # | Command | Expected result | Result |
| --- | --- | --- | --- |
| 5.1 | In the session with `-A`: `sudo true; echo $?` | `0`, and no password prompt | |
| 5.2 | A new session without `-A`: `sudo true` | It asks for a password and fails. It cannot succeed | |
| 5.3 | `ssh -p 2222 root@localhost` (same options as above) | `Permission denied` | |
| 5.4 | `ssh -o PubkeyAuthentication=no -p 2222 ADMIN_USER@localhost` | `Permission denied`. It does not ask for a password | |
| 5.5 | `sudo passwd -S root` | Status `L` (locked) | |

## 6. Reboot disk A

Run `sudo systemctl reboot`, then start QEMU again with the same command.

| # | Check | Expected result | Result |
| --- | --- | --- | --- |
| 6.1 | `cat /etc/machine-id` | The same ID as in 4.5 | |
| 6.2 | `journalctl -b -u systemd-repart` | It reports `No changes`, or no change to the partitions | |
| 6.3 | `systemctl --failed` | `0 loaded units listed` | |

## 7. Boot disk B and compare

Boot disk B with `vars-b.fd` and `disk-b.img`. Use a different forward port, for
example `hostfwd=tcp::2223-:22`.

| # | Command | Expected result | Result |
| --- | --- | --- | --- |
| 7.1 | `cat /etc/machine-id` | A different ID than on disk A | |
| 7.2 | `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub` | A different fingerprint than on disk A | |

## 8. Test the other sudo mode

Set `SUDO_MODE=nopasswd` in `image/build.conf`. Build again, write one disk
as in step 2, and boot it.

| # | Command | Expected result | Result |
| --- | --- | --- | --- |
| 8.1 | In a session without `-A`: `sudo true; echo $?` | `0`, and no prompt | |
| 8.2 | `ls /etc/security/sudo_authorized_keys` | The file does not exist | |

## 9. Test the real host (after the virtual machine passes)

Do this only on the target host. The install erases the whole disk. The
installer recipe does not exist yet, so this step comes later.

## Risks that I could not check

I cannot build or boot here. These points rest on documentation and not on a
test. If a step above fails, look here first.

1. **Boot entries.** The recipe installs `systemd-boot` after the kernel, as
   the `debos-configs` bookworm recipe does. I did not check that trixie makes
   the entries in the same way. Check 3.1 and 4.7. The recipe stops the build
   if no entry file exists, because the `sed` has no file to read.
2. **Machine ID option.** The recipe removes `systemd.machine_id=` from the
   entries. If a later kernel update adds it again, the value is the real ID
   of that host, so this is safe. Check 4.6 and 7.1.
3. **Swap activation.** I expect `systemd-gpt-auto-generator` to activate the
   swap partition without an `fstab` entry. Check 4.2.
4. **`pam_ssh_agent_auth`.** I did not test it on trixie. Check 5.1 and 5.2.
5. **The `en*` pattern.** It must not match a NIC that is bound to `vfio-pci`.
   This only shows on the real host.
6. **`debos` value passing.** The SSH key contains spaces. The script passes it
   with `-t`. The dry run rendered it correctly. Check 3.2 for the real result.

What I did test: `systemd-repart` on a sparse file with the same partition
types. Root stayed at 32 GB. The tool added a 4 GB swap partition and a 62 GB
XFS partition on a disk grown to 100 GB. A second run changed nothing.
