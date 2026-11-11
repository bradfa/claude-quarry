# Network layout and firewall

The guest reaches the internet through a NAT network that the host firewall
restricts. It reaches the board through a separate passthrough Ethernet card
that the host cannot see. The rules on this page are the design. The firewall
tests run in a virtual machine only, and nothing has run on a real host.

## Layout

- The guest has two network interfaces.
  - The first is a virtio interface on a dedicated libvirt NAT network (not the
    default network). It gives internet access. The host image defines this
    network: its name is `quarry`, its bridge is `virbr-quarry`, and its
    addresses are `10.250.0.0/24`. The host is `10.250.0.1`. The image has no
    `default` network.
  - The second is the passthrough Ethernet card (see `passthrough.md`). Cable it
    directly to the board or to a dedicated switch.
- Never cable the board network to the office LAN or to any uplink.
- The guest runs a DHCP server on the board network. The host has no address on
  it.
- The host uplink is its onboard Ethernet port (`eno1`), on the office LAN.

On the reference host, the only firewall rules are the Tailscale rules. They
come from `iptables-nft`, with an accept policy. The Tailscale `ts-forward`
chain accepts forwarded traffic to `tailscale0`. Nothing else stops a guest from
reaching the tailnet through the host.

## Host firewall

The host image has the rules in `/etc/quarry/claude-guest.nft`. They are in
their own nftables table, `inet claude_guest`, and they do not touch the tables
of Tailscale or libvirt. The `inet` family covers IPv6. `quarry-firewall.service`
loads the file before the network starts, and `systemctl reload` loads it again.
The stock `nftables.service` is off, because its `/etc/nftables.conf` starts with
`flush ruleset` and would delete the tables of libvirt and Tailscale. The
counters `host_input`, `not_uplink`, and `private_ranges` count the dropped
packets (`nft list counters`). For traffic from the guest bridge:

- Allow established and related traffic in the input chain, so that the guest
  can answer the host. The forward chain has no such rule. The return traffic
  from the internet comes in on the uplink, and a rule for the guest side would
  let a flow that began while the table was absent skip the drops.
- Allow DNS and DHCP to the libvirt dnsmasq on the bridge address. The guest
  needs them.
- Drop all other traffic from the guest to the host (input chain). This includes
  the Tailscale address of the host and the DNS port of the other host addresses.
- Let forwarded guest traffic leave only through a wired interface (`en*`, the
  same match as the systemd-networkd file of the image, so the rules need no
  interface name for each host). Drop forwarded guest traffic to every other
  interface, including `tailscale0`.
- Drop forwarded traffic from the guest to these destinations: private ranges,
  CGNAT (`100.64.0.0/10`), link-local ranges, IPv6 unique local addresses
  (`fc00::/7`, which covers the tailnet), multicast, and the office LAN. Allow
  forwarded traffic to the internet. The ranges cover the office LAN only when it
  uses private addresses. A LAN with public addresses needs its own rule.
- Allow connections that the host opens to the guest, for example SSH.

The order of the rules is not a problem for drop rules. A drop in any nftables
base chain ends the packet. An accept in another chain does not override it.

Libvirt 11.3 uses the first backend that it finds, and it tries `iptables`
before `nftables`. The package depends on `iptables | nftables`, so apt installs
`iptables`. The host image sets `firewall_backend = "nftables"` in
`/etc/libvirt/network.conf`. Libvirt then makes its own table, `libvirt_network`,
and does not use the tables `filter`, `nat`, and `mangle`. A test checks this.

The guest setup tests (`test/test_guest_setup.py`, step 4) boot a guest on the
test host and probe from inside it. A stand-in for the LAN and a dummy
`tailscale0` interface replace the real networks. Each probe must work with the
firewall unit stopped, and it must fail with the unit running. The test host
has no Tailscale, so check that the table works beside Tailscale on the real
host [Q4]. Run `nft list ruleset` there. Try to reach a LAN machine, a tailnet
address, and a host service from inside the guest. All must fail. Repeat the
test after every libvirt, Tailscale, or nftables change.

## Guest rules

- Set `net.ipv4.ip_forward` to 0 in the guest, so that the board network never
  routes to the internet through the guest.
- Bind dnsmasq to the board interface only.
- Export NFS only to the board subnet.
- The board network carries no other traffic.

## No egress allowlist

Bitbake fetches from many hosts, so a domain allowlist would block real work.
The accepted exposure is that a prompt injection could send the Claude login
token or the workspace data to any internet host. These options exist for
later:

- A host-side proxy with a domain list and a default-deny rule.
- A pre-filled download directory with `BB_NO_NETWORK` set for the unattended
  run [A13].

## Tailscale on the host

Many users of this scheme run Tailscale on the host. A compromised host holds a
Tailscale node identity. With the default policy, every device on the tailnet
can reach every other device. A compromised host could then reach the other
machines of the owner. The host firewall blocks the guest from the tailnet. It
does not help if the host itself is compromised.

Mitigations, in order of strength:

1. Do not run Tailscale on the host. Use SSH over the office LAN.
2. Tag the host and restrict the policy so that the host cannot start
   connections to other devices.
3. Keep the default policy. This is the weakest choice. Record it as an
   accepted risk.

For option 2:

1. Open the policy file on the Access controls page of the Tailscale console
   (`https://console.tailscale.com/admin/acls`). If the file has no `acls`
   section, the default allow-all policy applies.
2. Define a tag in `tagOwners`. Then apply it on the Machines page with "Edit
   tags". The tag must exist first. A tagged device loses user ownership, and
   its key expiry is off by default. Remove the node from the console if the
   host is lost.
3. Replace the allow-all rule with one rule for your own devices. This example
   adapts the documentation format [A14]. Replace `<your-login>`:

```json
{
  "tagOwners": {
    "tag:lab": ["<your-login>"]
  },
  "acls": [
    {
      "action": "accept",
      "src": ["<your-login>"],
      "dst": ["*:*"]
    }
  ]
}
```

No rule has `tag:lab` as a source, so the host should not be able to start
connections [A15]. Check this with the policy tests in the console before you
rely on it. Test from the host: `nc -vz -w 3 <tailnet address of the daily
machine> 22` must fail. SSH from the daily machine to the host must still work.

The change also replaces the allow-all rule for all your other devices. The
example keeps access between your own devices. Check this before you save.

## Risks

| Risk | Mitigation | Status |
| --- | --- | --- |
| The guest reaches the LAN, the tailnet, or host services through NAT | Own nftables table with drop rules. Forward only through `en*`. Test from inside the guest | Written. Tested in a virtual machine after the next image build, not on a real host |
| A compromised host reaches other machines of the owner over Tailscale | Tag the host and restrict the policy, or run no Tailscale on the host | Open until the owner changes the policy |

## Sources

- Tailscale default policy and the policy file location:
  <https://tailscale.com/kb/1018/acls>
- Tailscale tags, `tagOwners`, and key expiry: <https://tailscale.com/kb/1068/tags>
- nftables verdicts across base chains:
  <https://wiki.nftables.org/wiki-nftables/index.php/Configuring_chains>
