# claude-quarry

claude-quarry lets Claude Code work alone on embedded Linux and Yocto jobs that
need real hardware, and it keeps that work away from your own computer. It is a
set of design documents, a runbook, and image recipes to set up a dedicated host
PC. On that host, Claude Code runs inside a disposable KVM virtual machine. The
virtual machine owns a USB controller and an Ethernet card, so Claude can reach
serial adapters, SD card muxes, and boards on a bench.

You set a goal with Claude, and then Claude works alone, usually outside working
hours. Later, you review the result with Claude and approve it or ask for
changes.

## The problem

A Yocto build is only part of the job when you work on a board. Claude must also
flash an SD card, watch a serial console, power-cycle the board, and boot it
over the network with DHCP, TFTP, and NFS. That needs real devices and root
access on the machine that has them.

Claude Code can run many commands without asking you each time (auto mode).
That is useful for a long unattended job. It is also a risk on your daily
computer, which holds your files, your SSH keys, and your credentials. A bad
command, or a prompt injection in a fetched source file or in board console
output, must not reach any of these.

## How it works

1. A dedicated host PC runs Debian 13. The USB installer in this project writes
   a fixed host baseline to its disk.
2. Claude Code runs in a KVM virtual machine on that host. A container did not
   fit, because it cannot hold a physical Ethernet card and it handles device
   hot-plug badly.
3. The virtual machine owns a PCIe USB controller and a PCIe Ethernet card (PCI
   passthrough). USB hot-plug works like on a normal machine, and the guest runs
   the DHCP, TFTP, and NFS servers for a board.
4. The system of the guest is a disposable overlay on a read-only base image. If
   Claude breaks it, you delete the overlay. The work and the Claude login stay
   on a separate data disk.
5. The host sets the limits that Claude cannot change. A firewall stops the guest
   from reaching your LAN, your Tailscale network, and the host. A timer
   suspends the guest at a set time.

## What you need

| Item | Requirement |
| --- | --- |
| Host PC | A UEFI PC with CPU virtualization and an IOMMU (Intel VT-x and VT-d, or the AMD equivalents). Use a dedicated PC |
| Memory | The guest has a fixed amount of RAM. The design starts with 10 GiB and 6 vCPUs, and leaves the rest for the host |
| Disk | Room for the virtual machine disks. A Yocto build tree needs tens of GB, and sometimes over 100 GB. An SSD is much faster than a spinning disk |
| Host network | A wired connection to your LAN, for the host and for internet access |
| Board network | A PCIe Ethernet card in its own IOMMU group. Cable it to the board or to a dedicated switch, never to your LAN |
| USB for the guest | A PCIe USB xHCI card in its own IOMMU group, for the USB-UART adapters, the SD card mux, and the USB product |
| Software | Debian 13 on the host |
| Claude Code | A Claude Code login. The design assumes a Teams plan |
| Build machine | A machine with `debos`, `bmaptool`, and `zstd`, to build the images. This can be your daily computer |
| Image tests | `qemu-system-x86`, the `ovmf` package, and access to `/dev/kvm` |

Check the IOMMU groups before you buy cards. `doc/design/passthrough.md` has the
requirements, and the runbook will have a discovery script for your host.

## Warning

The host installer erases the whole target disk. The runbook will say this on its
first page.

## Risks you accept

- The virtual machine protects the host. It does not protect what is inside the
  guest. The guest has open internet access, because bitbake fetches from many
  hosts. A prompt injection could send your Claude login token or the workspace
  data to the internet. If this is not acceptable, do not use this project, or
  add a proxy with a domain list.
- It needs a dedicated PC, two PCIe cards, and a wired network. It is more work
  to set up than a container.
- The design is for one user. It assumes a company Teams plan, and that
  unattended use is allowed under it. Check this for your account.
- Overnight runs use the same weekly quota as your daytime work.

## Status

This project is in an early stage. Nothing has run on a real host yet.

| Part | State |
| --- | --- |
| Design documents | Written. Each unverified claim is in `doc/assumptions.md` |
| Host baseline image | Builds. It passes the virtual machine test (`doc/test-host-image.md`, steps 1 to 8) |
| USB installer | The recipe builds. The test in `doc/test-installer.md` is in progress |
| Discovery script, runbook, guest image | Not written |
| Passthrough, firewall, time limit, Claude Code setup | Design only. Nothing is tested |

The runbook is written one step at a time. A person runs each step on a real
host. The runbook marks a step as verified only after that run.

The rollout has eight stages. Each stage must pass its tests before the next one
starts. Stages 0 to 4 need no passthrough cards.

0. Host baseline: images, virtual machine tests, real install, first boot.
1. Host preparation: libvirt and QEMU packages, and the firewall table.
2. A test VM from the Debian cloud image: KVM speed, NAT, suspend and resume.
3. The own guest image from debos.
4. Claude Code: install, log in, and run a small task in auto mode.
5. Passthrough: add the cards one at a time, and run start and stop cycles.
6. Hardware tests: replug an adapter, test the SD mux, boot a real board.
7. Unattended runs: add the host timers, and start with short runs.

## Design documents

Each document describes the intended implementation of one topic. If the real
implementation differs, we change the document.

| Document | Topic |
| --- | --- |
| `doc/design/host-baseline.md` | The host image: disk layout, boot, network, access |
| `doc/design/installer.md` | The USB installer and its safety rules |
| `doc/design/passthrough.md` | IOMMU, VFIO, the two cards, and reset behavior |
| `doc/design/guest-storage.md` | Base image, overlay, data disk, snapshots, recovery |
| `doc/design/network.md` | Network layout, host firewall, Tailscale |
| `doc/design/run-control.md` | Suspend timer, time limit, quota, auto mode stalls |
| `doc/design/claude-code.md` | Claude Code install, login, permissions, provisioning |
| `doc/design/hil-services.md` | USB devices, network boot, SD mux, labgrid, safety rules |
| `doc/assumptions.md` | Claims and questions that nobody has verified yet |

## Try it today

### Build the images

The images have no user name and no SSH key in them. You give both to the build
script.

```
cp image/build.conf.example image/build.conf
```

Edit `image/build.conf`. Set `ADMIN_USER` and `ADMIN_SSH_KEY_FILE`. Each setting
has a comment. The script also asks for the two required settings if you leave
them out, and it stops with an error if a value is missing. Then run:

```
image/build.sh
```

The script builds the host image and then the USB installer. It writes
`image/build/host.img`, `host.img.zst`, and `host.bmap` for the host image, and
`image/build/installer.img` and `installer.bmap` for the installer. To build only
the host image, run `image/build.sh host`. The root account is locked, and
password login is off, so the SSH key is the only way in.

### Test the images

- `doc/test-host-image.md` boots the host image in QEMU and checks the disk
  layout, the network, the access control, and the first-boot identity.
- `doc/test-installer.md` boots the installer in QEMU, writes the host image to an
  empty virtual disk, and boots that disk.

## Conventions

- Prose follows ASD-STE100 (Simplified Technical English) and uses US English
  spelling. Files use ASCII characters only.
- Keep this file short. A topic that needs more than a few paragraphs goes into
  a design document.
- A claim that nobody has verified carries a marker such as `[A07]` in the design
  documents. It points to a row in `doc/assumptions.md`. When someone verifies the
  claim, delete the row and the marker.
- Each runbook step states its expected result. Record the real result after a
  run on a real host.

## Related work

The `image/` recipes are adaptations of the x86_64 UEFI recipes in the
`debos-configs` repository.
