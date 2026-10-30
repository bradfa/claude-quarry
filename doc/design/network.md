# Network layout and firewall

The guest reaches the internet through a NAT network that the host firewall
restricts. It reaches the board through a separate passthrough Ethernet card
that the host cannot see. The rules on this page are the design. None is
tested.

## Layout

- The guest has two network interfaces.
  - The first is a virtio interface on a dedicated libvirt NAT network (not the
    default network). It gives internet access.
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

Put the rules in their own nftables table, for example `inet claude_guest`. Do
not edit the tables of Tailscale or libvirt. Use the `inet` family so that IPv6
is covered. For traffic from the guest bridge:

- Allow established and related traffic.
- Allow DNS and DHCP to the libvirt dnsmasq on the bridge address. The guest
  needs them.
- Drop all other traffic from the guest to the host (input chain). This includes
  the Tailscale address of the host.
- Let forwarded guest traffic leave only through `eno1`. Drop forwarded guest
  traffic to every other interface, including `tailscale0`.
- Drop forwarded traffic from the guest to these destinations: private ranges,
  CGNAT (`100.64.0.0/10`), link-local ranges, IPv6 unique local addresses
  (`fc00::/7`, which covers the tailnet), multicast, and the office LAN. Allow
  forwarded traffic to the internet.
- Allow connections that the host opens to the guest, for example SSH.

The order of the rules is not a problem for drop rules. A drop in any nftables
base chain ends the packet. An accept in another chain does not override it.

Find out which firewall backend libvirt 11.3 uses on Debian 13 [Q4]. Run
`nft list ruleset` after you install libvirt. Test from inside the guest: try to
reach a LAN machine, a tailnet address, and a host service. All must fail.
Repeat the test after every libvirt, Tailscale, or nftables change.

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
| The guest reaches the LAN, the tailnet, or host services through NAT | Own nftables table with drop rules. Forward only through `eno1`. Test from inside the guest | To test |
| A compromised host reaches other machines of the owner over Tailscale | Tag the host and restrict the policy, or run no Tailscale on the host | Open until the owner changes the policy |

## Sources

- Tailscale default policy and the policy file location:
  <https://tailscale.com/kb/1018/acls>
- Tailscale tags, `tagOwners`, and key expiry: <https://tailscale.com/kb/1068/tags>
- nftables verdicts across base chains:
  <https://wiki.nftables.org/wiki-nftables/index.php/Configuring_chains>
