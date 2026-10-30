# PCI passthrough

The guest owns one PCIe USB xHCI card and one PCIe Ethernet card. PCI
passthrough with VFIO gives both cards to the guest. The vfio-pci driver binds
to a device so that host drivers cannot use it. QEMU then reaches the device
through a `/dev/vfio` group node.

A virtual machine fits hardware work better than a container. A VM that owns a
whole USB controller handles hot-plug like a normal machine, and it can own a
physical Ethernet card.

## Requirements

1. **Firmware and kernel.** VT-x and VT-d are on, and the IOMMU is active. The
   Debian default is on, so the kernel command line needs no IOMMU option. Do
   not add `intel_iommu=on`. The libvirt packages probably load the `vfio`
   modules [A05]. If they do not, load the modules at boot.
2. **IOMMU groups.** Every device in a group must go to the guest together. If
   one device of a group is bound to vfio-pci, QEMU gives an error when another
   device of that group is assigned. Check the group of each card before you
   buy or install it.
3. **Bind the cards to vfio-pci.** Two methods exist.
   - A libvirt `hostdev` with `managed='yes'` detaches the device from the host
     driver at guest start and attaches it again at stop [A06].
   - The second method binds at boot with `vfio-pci.ids`. It needs a softdep so
     that vfio-pci loads before the native driver.

   The runbook uses the per-address method (the first one), because it is safe
   on other hardware too. The `vfio-pci.ids` method is safe on the reference
   host only, because the added card (8086:10d3) differs from the onboard I217
   (8086:153a).
4. **Define the `hostdev` entries.** Each card is a `hostdev` of type `pci`,
   with the domain, bus, slot, and function of the card. No example is tested
   yet.
5. **Fix the guest memory.** VFIO pins all guest RAM, so ballooning and
   overcommit do not work [A07]. Start with 10 GiB of RAM and 6 vCPUs for the
   guest [Q5]. On the reference host, this leaves about 5 GiB and one core for
   the host.
6. **Test the reset behavior.** A card must reset cleanly when the guest stops.
   The 82574L Ethernet card has no function-level reset. Its reset methods are
   `pm` and `bus`. Run many start and stop cycles with each card [Q2, Q3]. The
   owner has used the xHCI card model in passthrough on other PCs, but the
   reference host is new.
7. **Interrupt remapping.** A platform without it needs an unsafe-interrupts
   option. The reference host has interrupt remapping (x2apic mode), so it does
   not need that option.
8. **Board-specific faults.** One user reported that a host crashed when a
   second USB controller was added to a passthrough setup. This is one report
   on one board. Test the cards one at a time.
9. **Privilege model.** Passthrough uses the system libvirt daemon, which runs
   as root. QEMU itself probably runs as an unprivileged user with a security
   profile on Debian [A08]. Keep the account that manages libvirt away from
   anything that Claude can reach. Never expose the libvirt socket inside the
   guest.

A member of the `libvirt` group probably has close to root access on the host
[A02]. On the reference host, the owner account is already in the `sudo` group,
so the group adds no new privilege there. The trust moves to the hypervisor and
the IOMMU.

## Host preparation

Install these packages on the host: `qemu-system-x86`, `libvirt-daemon-system`,
`libvirt-clients`, `virtinst`, `qemu-utils`, and `ovmf`. All of them exist in
Debian 13. The package `qemu-kvm` is not a real package name there. `virtiofsd`
is not needed, because guests share nothing at first. Add the management user to
the `libvirt` group. Run `virt-host-validate` to check the host.

## Reference host measurements

These facts come from the discovery output of the reference host.

- The kernel is 6.12.113. The kernel command line has no IOMMU option, and the
  kernel still built IOMMU groups.
- Three DMAR lines report "inconsistent" features: `pgsel_inv`, `sc_support`,
  and `pass_through`. The `ecap` values suggest that pass-through is clear on
  `dmar0` and set on `dmar1`. `dmar0` appears to serve only the integrated
  graphics [A03]. Do not add `iommu=pt`. VFIO does not need it.
- Two RMRR regions exist. The kernel marks them `direct-relaxable`. The small
  region belongs to the three USB controllers (groups 3, 6, and 10). The large
  region belongs to the integrated graphics (group 0). The LPC group (group 11)
  has a low-memory region. The added Ethernet card has no RMRR.
- Each onboard device is in its own IOMMU group, except for 00:16.0 with
  00:16.3, and 00:1f.0 with 00:1f.2 and 00:1f.3. The added Ethernet card is in
  its own group (group 12). Root ports 00:1c.0 and 00:1c.3 are in their own
  groups.
- All external USB devices are on the onboard xHCI controller. Both EHCI buses
  have only empty internal hubs. A guest that owns the onboard xHCI controller
  would remove every external USB port from the host.

For this reason, the plan keeps the onboard xHCI controller on the host and adds
a PCIe USB xHCI card for the guest. The slot behind 00:1c.0 (bus 01) is empty.
The new card should appear there, in its own group [A04, Q2].

| Device | Location | Goes to | Purpose |
| --- | --- | --- | --- |
| Onboard Intel I217-LM Ethernet (`eno1`, 8086:153a) | 00:19.0, group 5 | Host | Host uplink on the office LAN |
| Added Intel 82574L Ethernet card (`enp2s0`, 8086:10d3) | 02:00.0, group 12 | Guest | Board network: DHCP, TFTP, NFS |
| Added PCIe USB xHCI card (ordered, not installed) | To be checked | Guest | USB-UART, SD mux, USB product, hot-plug |
| Onboard xHCI controller | 00:14.0, group 3 | Host | Host keyboard and rescue input |
| Realtek USB Wi-Fi adapter (`rtl8192cu`) | On the onboard xHCI | Host | Current uplink. It goes away when `eno1` is cabled |

## Risks

| Risk | Mitigation | Status |
| --- | --- | --- |
| A passthrough card fails to reset and needs a host reboot | Many start and stop tests before real use. The 82574L has no function-level reset | To test |
| Hypervisor or IOMMU escape | Keep the host patched. The devices sit behind the IOMMU | Accepted, low |
| Membership in the `libvirt` group equals near-root access | The owner account already has `sudo`. No libvirt socket in the guest | Accepted |

## Sources

- VFIO basics: <https://stackharbor.com/en/knowledge-base/gpu-passthrough-vfio-iommu/>
  and <https://cubepath.com/docs/hardware-and-system-management/pci-passthrough-for-virtual-machines>
- The IOMMU group rule (libvirt-users thread):
  <https://listman.redhat.com/archives/libvirt-users/2015-August/008180.html>
- The interrupt remapping option (vfio-users thread):
  <https://listman.redhat.com/archives/vfio-users/2018-August/004633.html>
- A host crash with a second USB controller (one report):
  <https://bbs.archlinux.org/viewtopic.php?id=285268>
- RMRR exclusion and the USB exemption:
  <https://lkml.iu.edu/hypermail/linux/kernel/1409.1/03280.html> and
  <https://lkml.iu.edu/2209.2/05142.html>
- The RMRR refusal message for a network card:
  <https://forum.proxmox.com/goto/post?id=612846>
- The host measurements in `host-discovery.txt` and `host-discovery-2.txt`.
