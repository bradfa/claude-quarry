# claude-quarry

Plans, runbooks, and configuration files to run Claude Code in a disposable
KVM virtual machine. The virtual machine does Yocto (bitbake and oe-core) work
that needs real hardware. The owner sets a goal with Claude. Claude then works
alone. Later, the owner reviews the result with Claude.

## Status

This project is in an early stage. The plan exists. The host baseline image
builds, and it passes the virtual machine test (steps 1 to 7 of
`doc/test-host-image.md`, run on 2026-10-29). These parts do not exist yet: the
USB installer, the discovery script, the runbook, and the guest image. Nothing
has run on the real host.

The runbook is written one step at a time. A person runs each step on a real
host. The runbook marks a step as verified only after that run.

## Layout

| Path | Purpose | State |
| --- | --- | --- |
| `doc/plan-sandboxed-autonomous-claude-in-kvm.md` | The plan. It gives the goals, the decisions, the risks, and the open questions. It explains why. | Exists |
| `doc/test-host-image.md` | Test steps for the host image in a virtual machine, with an expected result and the real result of each step. | Exists. Steps 1 to 7 pass. Step 8 has not run |
| `doc/runbook-*.md` | The runbook. It gives exact steps from a fresh Debian 13 install to a working guest, with a check after each step. It explains how. | Planned |
| `host/` | Host files: discovery script, firewall rules, libvirt XML, and systemd timers. | Planned |
| `host/discovery/` | Output of the discovery script, saved from real hosts. | Planned |
| `guest/` | Guest files: provisioning script, Claude Code settings template, and guest CLAUDE.md. | Planned |
| `image/` | debos recipes and overlay files: the host baseline, the USB installer, and the guest base image. `image/build.sh` builds them in a fixed order. | The host baseline builds and boots in a virtual machine. The installer and the guest image are planned |

## Prerequisites

The plan expects this hardware and software:

- A host PC with CPU virtualization support and an IOMMU (Intel VT-x and VT-d,
  or the AMD equivalents).
- Debian 13 (trixie) on the host.
- A PCIe Ethernet card for the board network. It must be in its own IOMMU
  group.
- A PCIe USB xHCI card for the USB-UART adapters, the SD card mux, and the USB
  product. It must be in its own IOMMU group.
- A Claude Code login. The plan assumes a Teams plan.
- A machine with `debos` and `bmaptool` installed, to build the images.
- To test an image in a virtual machine: `qemu-system-x86`, the `ovmf`
  package, and access to `/dev/kvm`.

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

The script writes `image/build/host.img` and `image/build/host.bmap`. The root
account is locked, and password login is off, so the SSH key is the only way
in.

### Test the host image

Follow `doc/test-host-image.md`. It boots the image in QEMU and checks the
disk layout, the network, the access control, and the first-boot identity.

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

## Warning

The planned host installer erases the whole target disk. The runbook will say
this on its first page.
