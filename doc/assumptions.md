# Assumptions and open questions

This page lists what nobody has verified yet. A topic design doc in `doc/design/`
marks each of these claims with its ID, for example `[A07]`.

When you verify a claim or answer a question:

1. Delete its row on this page.
2. In the topic doc, delete the marker and keep the fact as a plain sentence.
3. If the answer changes the design, change the topic doc.

The git history keeps the deleted rows.

## Assumptions

| ID | Claim | Topic doc | How to verify |
| --- | --- | --- | --- |
| A01 | The guest disk I/O is slower than native I/O. | guest-storage | Time one build on the host and one in the guest. |
| A02 | A member of the `libvirt` group has close to root access on the host. | passthrough | Read the libvirt documentation for the system daemon. Test what a group member can do. |
| A03 | On the reference host, the first DMAR unit (`dmar0`) serves only the integrated graphics, and its pass-through bit is clear. | passthrough | Read `/sys/class/iommu/dmar0/devices` and the DMAR lines in `dmesg`. |
| A04 | The new xHCI card appears behind root port 00:1c.0 in its own IOMMU group. | passthrough | Install the card and run the discovery script. |
| A05 | The libvirt packages load the `vfio` modules. | passthrough | Run `lsmod` after the libvirt install. |
| A06 | A libvirt `hostdev` with `managed='yes'` detaches the card from the host driver at guest start and attaches it again at stop. | passthrough | Run start and stop cycles (rollout stage 5). |
| A07 | VFIO pins all guest RAM, so ballooning and overcommit do not work. | passthrough | Check the host memory use of a running guest. |
| A08 | On Debian, QEMU runs as an unprivileged user with a security profile. | passthrough | Check the process owner and `aa-status`. |
| A09 | The overlay and data-disk design works as written: the overlay uses the base image as its backing file, the SSH host keys live on the data disk, and `first-boot.service` does not replace them. | guest-storage | Build the guest image and reset the overlay (rollout stage 3). |
| A10 | oe-core ships `scripts/sstate-cache-management.sh`. | guest-storage | Look in an oe-core tree. |
| A11 | On XFS, `cp --reflink=always` of a data disk is instant and uses almost no space. | guest-storage | Run it on the `vmdata` partition. |
| A12 | The libvirt managed save and hibernate do not work with passthrough devices. | guest-storage | Run `virsh managedsave` with both cards attached. |
| A13 | `BB_NO_NETWORK` with a pre-filled download directory is a workable way to limit egress for an unattended run. | network | Run a build with the variable set. |
| A14 | The Tailscale policy example in the network doc is valid as written. | network | Run the policy tests in the Tailscale console. |
| A15 | With that policy, the tagged host cannot start a connection to another device. | network | From the host, run `nc -vz -w 3 <address of the daily machine> 22`. It must fail. |
| A16 | Claude Code has no built-in run-time limit. | run-control | Read the documentation of each pinned release. Run a long session. |
| A17 | The QEMU guest agent or `chrony` corrects the guest clock after a long suspend. | run-control | Suspend the guest, wait, resume it, and read the clock. |
| A18 | Claude Code refuses `--dangerously-skip-permissions` as root, and bitbake refuses to run as root. | claude-code | Try both as root in the guest. |
| A19 | The Claude Code installer is a curl-and-bash script. | claude-code | Read the installer at rollout stage 4. |
| A20 | Haiku 5.5 works in auto mode on a Teams account. | claude-code | Start auto mode with Haiku on the account. |
| A21 | Hardware steps that need root fail under the Claude Code sandbox. | claude-code | Run one such step (for example `modprobe`) in a sandboxed session. |
| A22 | A Claude Code session reads a changed `CLAUDE.md` after a restart or a resume. | claude-code | Change the file, resume the session, and ask Claude about it. |
| A23 | The `/dev/serial/by-path` names include the physical port of the xHCI card, so udev rules can use them. | hil-services | Plug in the adapters and list the names. |
| A24 | A name clash between SD mux disks and the virtio disks of the guest is unlikely. | hil-services | Run `lsblk` in the guest with the mux attached. |
| A25 | The guest is the natural exporter host for labgrid, because it owns the USB controller. | hil-services | Decide when labgrid work starts. |
| A26 | The `en*` network match does not match a NIC that is bound to `vfio-pci`. | host-baseline | On the real host, bind a NIC to `vfio-pci` and read `networkctl`. |
| A27 | The USB installer boots in QEMU, and `bmaptool` reads the `.zst` image. | installer | Follow `doc/test-installer.md` until the suite replaces it. |

## Open questions

| ID | Question | Topic doc | How to answer |
| --- | --- | --- | --- |
| Q2 | What IOMMU group does the PCIe xHCI card get, and does it share a group with anything except its root port? Does it reset cleanly over many cycles? | passthrough | Install the card. Run the discovery script and the start and stop cycles. |
| Q3 | Does the added Ethernet card reset cleanly over many cycles, given that it has no function-level reset? | passthrough | Run the start and stop cycles. |
| Q4 | Which firewall backend does libvirt 11.3 use on Debian 13, and does the `claude_guest` table work beside it and beside Tailscale? | network | Run `nft list ruleset` after the libvirt install, then test from inside the guest. |
| Q5 | Is 10 GiB of RAM and 6 vCPUs right for the guest, and how long do real builds take on the spinning disk? | passthrough | Time real builds. |
| Q6 | Does the real firmware of the host boot the host image and the installer through the removable-media path? The OVMF firmware of the virtual machine does. | host-baseline | Boot the installer on the real host. |
| Q7 | How does bitbake behave across `virsh suspend` and resume, including fetches in progress and `BB_SERVER_TIMEOUT`? | run-control | Suspend during a build. |
| Q8 | Does a background bitbake task that finishes after the Escape key wake Claude Code and use quota? | run-control | Test one interrupted run. |
| Q9 | Does Haiku usage count differently from other models against the weekly quota on Teams? | run-control | Read `/usage` before and after a Haiku session. |
| Q10 | How should plugins be installed: `--plugin-dir` or a local marketplace? How do `enabledPlugins` and `extraKnownMarketplaces` behave in user settings? | claude-code | Test both ways. |
| Q11 | What does the `autoMode.environment` guidance need to say? | claude-code | Read the auto mode configuration page. |
| Q12 | Does auto mode still work with `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`? | claude-code | Test it. |
| Q14 | Does the company allow unattended automation on a Teams login, and what is the procedure if the token leaks? An API key with a spend limit is an alternative. | claude-code | Ask the owner of the company account. |
| Q15 | Can the quarry guest run QEMU with KVM (nested virtualization) fast enough for the test suite? | test suite | Check `kvm_intel nested` on the quarry host and run the suite in the guest. |
