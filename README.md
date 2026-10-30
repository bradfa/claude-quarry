# claude-quarry

claude-quarry lets Claude Code work alone on embedded Linux and Yocto jobs that
need real hardware, and it keeps that work away from your own computer. It is a
plan, a runbook, and the image recipes to set up a dedicated host PC. On that
host, Claude Code runs inside a disposable KVM virtual machine. The virtual
machine owns a USB controller and an Ethernet card, so Claude can reach serial
adapters, SD card muxes, and boards on a bench.

You set a goal with Claude, and then Claude works alone, usually outside
working hours. Later, you review the result with Claude and approve it or ask
for changes.

## The problem

A Yocto build is only part of the job when you work on a board. Claude must
also flash an SD card, watch a serial console, power-cycle the board, and boot
it over the network with DHCP, TFTP, and NFS. That needs real devices and root
access on the machine that has them.

Claude Code can run many commands without asking you each time (auto mode).
That is useful for a long unattended job. It is also a risk on your daily
computer, which holds your files, your SSH keys, and your credentials. A bad
command, or a prompt injection in a fetched source file or in board console
output, must not reach any of these.

A container does not solve this well for hardware work. A device that the
container gets at start can go stale when it is unplugged and plugged in again.
A rootless container cannot own a physical Ethernet card. Bitbake also
conflicts with the default container security profile. The plan describes
these problems and their sources in `doc/plan-sandboxed-autonomous-claude-in-kvm.md`.

## What you get

- **A separate host.** The Claude Code work runs on a dedicated PC. Your daily
  computer and its files are not on it.
- **A disposable guest.** The virtual machine has a read-only base image and a
  throwaway overlay. If Claude breaks the system, you delete the overlay and
  start again. The work and the Claude login stay on a separate data disk.
- **Real hardware in the guest.** The guest owns a PCIe USB controller and a
  PCIe Ethernet card (PCI passthrough). USB hot-plug works like on a normal
  machine, and the guest can run the DHCP, TFTP, and NFS servers for a board.
- **Limits that Claude cannot change.** A firewall on the host stops the guest
  from reaching your LAN, your Tailscale network, and the host itself. A timer
  on the host suspends the guest at a set time.
- **A reproducible setup.** The host starts from a fresh Debian 13 install, or
  from an installer image that this project builds. The runbook gives exact
  steps, with a check after each step, so another engineer can follow it.

## Why you may not want it

- The virtual machine protects the host. It does not protect what is inside
  the guest. The guest has open internet access, because bitbake fetches from
  many hosts. A prompt injection could send your Claude login token or the
  workspace data to the internet. If this is not acceptable, do not use this
  project, or add a proxy with a domain list. The plan lists this risk first.
- It needs a dedicated PC, two PCIe cards, and a wired network. It is more
  work to set up than a container.
- The plan is for one user. It assumes a company Teams plan, and that
  unattended use is allowed under it. Check this for your account.
- Overnight runs use the same weekly quota as your daytime work.
- A host with a spinning disk builds slowly. An SSD helps most.

## What you need

The plan was written for one reference host. Other hardware should work if it
meets the same requirements, but nobody has tested it.

| Item | Requirement | Reference host |
| --- | --- | --- |
| Host PC | A UEFI PC with CPU virtualization and an IOMMU (Intel VT-x and VT-d, or the AMD equivalents) | HP EliteDesk, Intel i7-4770 (4 cores, 8 threads), Q87 chipset |
| Memory | The guest has a fixed amount of RAM. The plan starts with 10 GiB and 6 vCPUs for the guest, and leaves the rest for the host | 15 GiB |
| Disk | Room for the virtual machine disks. A Yocto build tree can need tens to over 100 GB. An SSD is much faster | One 1 TB spinning disk |
| Host network | A wired connection to your LAN for the host and for internet access | Onboard Intel I217-LM (`eno1`) |
| Board network | A PCIe Ethernet card. It must be in its own IOMMU group. Cable it to the board or to a dedicated switch, never to your LAN | Intel 82574L |
| USB for the guest | A PCIe USB xHCI card for the USB-UART adapters, the SD card mux, and the USB product. It must be in its own IOMMU group | Ordered, not installed yet |
| Operating system | Debian 13 (trixie) | Debian 13 |
| Claude Code | A Claude Code login. The plan assumes a Teams plan | |
| Build machine | A machine with `debos` and `bmaptool` installed, to build the images. This can be your daily computer | |
| Image test | To test an image in a virtual machine: `qemu-system-x86`, the `ovmf` package, and access to `/dev/kvm` | |

Check the IOMMU groups before you buy cards. Every device in a group must go to
the guest together. The plan has a section on passthrough requirements, and
the runbook will have a discovery script that prints the facts about your host.

## Warning

The host installer erases the whole target disk. Use a dedicated PC. The
runbook will say this on its first page.

## Status

This project is in an early stage. Nothing has run on the real host yet.

| Part | State |
| --- | --- |
| Plan | Written |
| Host baseline image | Builds, and passes the virtual machine test (steps 1 to 8 of `doc/test-host-image.md`, run on 2026-10-29 and 2026-10-30) |
| USB installer | The recipe exists. Nobody has built or tested it yet (`doc/test-installer.md`) |
| Discovery script, runbook, guest image | Not written |
| Passthrough, firewall, time limit, Claude Code setup | Design only. Nothing is tested |

The runbook is written one step at a time. A person runs each step on a real
host. The runbook marks a step as verified only after that run.

## How to use this project today

1. Read the plan in `doc/`.
2. Compare your host with the host section of the plan.

The runbook will replace step 2 with a discovery script.

### Build the host image

The image has no user name and no SSH key in it. You give both to the build
script.

```
cp image/build.conf.example image/build.conf
```

Edit `image/build.conf`. Set `ADMIN_USER` and `ADMIN_SSH_KEY_FILE`. Each
setting has a comment. The script also asks for the two required settings if
you leave them out, and it stops with an error if a value is missing. Then run:

```
image/build.sh
```

The script builds the host image and then the USB installer. It writes
`image/build/host.img`, `host.img.gz`, and `host.bmap` for the host image, and
`image/build/installer.img` and `installer.bmap` for the installer. To build
only the host image, run `image/build.sh host`. The root account is locked, and
password login is off, so the SSH key is the only way in.

### Test the host image

Follow `doc/test-host-image.md`. It boots the image in QEMU and checks the
disk layout, the network, the access control, and the first-boot identity.

### Test the USB installer

Follow `doc/test-installer.md`. It boots the installer in QEMU, writes the host
image to an empty virtual disk, and boots that disk. The installer is not
tested yet.

## Layout

| Path | Purpose | State |
| --- | --- | --- |
| `doc/plan-sandboxed-autonomous-claude-in-kvm.md` | The plan. It gives the goals, the decisions, the risks, and the open questions. It explains why. | Exists |
| `doc/test-host-image.md` | Test steps for the host image in a virtual machine, with an expected result and the real result of each step. | Exists. Steps 1 to 8 pass. Step 9 has not run |
| `doc/test-installer.md` | Test steps for the USB installer in a virtual machine, with an expected result for each step. | Exists. Nothing has run |
| `doc/runbook-*.md` | The runbook. It gives exact steps from a fresh Debian 13 install to a working guest, with a check after each step. It explains how. | Planned |
| `host/` | Host files: discovery script, firewall rules, libvirt XML, and systemd timers. | Planned |
| `host/discovery/` | Output of the discovery script, saved from real hosts. | Planned |
| `guest/` | Guest files: provisioning script, Claude Code settings template, and guest CLAUDE.md. | Planned |
| `image/` | debos recipes and overlay files: the host baseline, the USB installer, and the guest base image. `image/build.sh` builds them in a fixed order. | The host baseline builds and boots in a virtual machine. The installer recipe exists and is not tested. The guest image is planned |

## Conventions

- Prose follows ASD-STE100 (Simplified Technical English) and uses US English
  spelling.
- Files use ASCII characters only.
- Each runbook step states its expected result. Record the real result after a
  run on a real host.
- Items marked (A) in the plan are assumptions that nobody has verified.
  Items marked (V) were verified in a virtual machine test. Items marked (H)
  were measured on the real host.

## Related work

The `image/` recipes are adaptations of the x86_64 UEFI recipes in the
`debos-configs` repository.
