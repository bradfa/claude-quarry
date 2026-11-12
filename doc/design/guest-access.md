# Access and privileges in the guest

The guest has two accounts. Claude works in one of them, and it has no root and
no `sudo`. The owner uses the other one for administration. All points on this
page are design intent and are not tested, unless a point says that it is.

## Decisions

| Topic | Decision | Note |
| --- | --- | --- |
| Accounts | The Claude account (default name `claude`) and the admin account. | The owner logs in as the Claude account every day. |
| Root | Claude has no root and no `sudo`. Only the admin account has `sudo`. | See Root work without `sudo`. |
| Login | SSH public key only. No passwords. No root login. | |
| Key files | Root owns the authorized keys files. | Claude cannot add a key. |
| Agent | An SSH agent is forwarded to the admin account only. The Claude account refuses it. | See The agent in admin sessions. |
| Admin `sudo` | `pam_ssh_agent_auth`, as on the host. It fails without a forwarded agent. | See `host-baseline.md`. |
| Updates | A daily `unattended-upgrades` job is the one root process that runs by itself. | See Updates. |

## Accounts

- The image build takes two user names. `CLAUDE_USER` has the default `claude`.
  `ADMIN_USER` has no default, as on the host. The build stops if a name is
  `root`, or if the two names are the same.
- The Claude account is not in the `sudo` group and has no `sudoers` rule.
- The admin account is in the `sudo` group.
- Each home directory has mode 0700, so neither account can read the other.
- Both accounts use the same public key of the owner.

## SSH login

The owner logs in as the Claude account every day, to talk to Claude in tmux
(see `claude-code.md`). The owner logs in as the admin account for
administration. This is the file `/etc/ssh/sshd_config.d/10-quarry.conf`:

```
PermitRootLogin no
PasswordAuthentication no
AllowUsers claude admin
AuthorizedKeysFile /etc/ssh/authorized_keys/%u

Match User claude
    AllowAgentForwarding no
```

The build writes the real user names. This is the client configuration on the
daily machine:

```
Host quarry-host
    HostName quarry-host.local
    User admin

Host quarry-guest
    User claude
    ForwardAgent no
    ProxyJump quarry-host

Host quarry-guest-admin
    HostName quarry-guest
    User admin
    ForwardAgent yes
    ProxyJump quarry-host
```

- The guest has no address on the LAN. Its address is on the `quarry` network of
  the host (see `network.md`), and only the host knows its name. `ProxyJump`
  makes the host open the connection, so the host resolves the name. The host
  only relays the connection. It never sees the agent, and the `ForwardAgent`
  line applies to the guest.
- `AllowUsers` lists exactly the two accounts.
- `AuthorizedKeysFile` points to a directory that root owns. Claude cannot
  add a key to its own account, and it cannot change the options of a key. With
  the default file in the home directory, Claude could do both.
- `AllowAgentForwarding no` for the Claude account guards against a mistake in
  the client configuration, for example `ssh -A` to the wrong alias. It does not
  stop Claude. The `sshd_config` manual says that a ban on agent forwarding does
  not improve security against a user who has a shell, because that user can
  install a forwarder. Claude has no agent to forward, so this is not a
  threat.
- The Git workflow uses the Claude account. `git fetch quarry` runs over the
  `quarry-guest` alias (see `claude-code.md`).

## The agent in admin sessions

- `sudo` in the admin account asks the forwarded agent, with the same
  `pam_ssh_agent_auth` setup as on the host. Without `ssh -A`, `sudo` fails.
- `sshd` makes the socket of the forwarded agent for the admin user, and the
  socket is private to that user. The Claude account cannot read it [A30].
- Root can use the socket. If Claude gets root through a bug, and an admin
  session is open at that moment, Claude can ask the agent to sign. The touch
  policy of the Yubikey limits this, but a touch that the owner gives for one
  purpose can authorize another inside the cache time. Keep admin sessions
  short, and close them when the work is done.

## Rules for the two accounts

- The admin account never runs anything from the home directory or the workspace
  of the Claude account. This includes `make`, scripts, and a command in a
  repository that reads files which Claude controls.
- The admin account never attaches to the tmux session of the Claude account.
- The Claude account is in the `kvm` group and in no other group. It is never in
  the `sudo` group, and never in the `disk` group. The `disk` group gives raw
  access to the disks of the guest, including the data disk with the Claude
  login.

## Root work without `sudo`

Hardware work needs privileges. The design gives each need a narrow method. A
`sudo` rule is the last method that we use. A rule with a wildcard, or a rule
for a command that runs a file which Claude can write, is root in disguise.

| Need | Method |
| --- | --- |
| Serial adapters and USB devices | A group, for example `dialout`, and `udev` rules that match vendor and product IDs. |
| SD card mux and SD cards | A `udev` rule that gives the mux disk to a new group, for example `sdmux`. The rule matches the `/dev/disk/by-id` name of the mux. Not the `disk` group. |
| Hardware virtualization (`/dev/kvm`) for a test VM or `runqemu` | The Claude account is in the `kvm` group, and it has no other group. The device exists only when the guest has nested virtualization (see `host-baseline.md`). |
| Kernel modules | The image loads the needed modules at boot (`/etc/modules-load.d`). `udev` loads the USB serial drivers. |
| DHCP, TFTP, and NFS for a board | Root-owned services and a root-owned generator. See below. |
| Software packages | The image build installs them. Claude has no `apt`. Python environments and similar tools install in the home directory. |
| Start, stop, and reboot of the guest | The host does this. Claude does not need it. |

### Services for the board

Do not let a root service read a configuration file that Claude writes.
`dnsmasq` runs the program of its `dhcp-script` option as root, even when
`dnsmasq` itself drops to a normal user. A `dnsmasq` file that Claude can write
gives Claude root. An NFS `exports` file has the same problem, because an
entry can export any directory with `no_root_squash`.

The design is this:

1. Claude writes data, not configuration. For each board, a small file holds the
   MAC address, the IP address, the boot file name, and the name of the root
   file system directory.
2. A path unit sees a changed file. A root-owned service starts a root-owned
   generator script.
3. The generator checks every field against a strict pattern. It writes the
   `dnsmasq` and `exports` configuration itself, with fixed options. It tests
   the result (`dnsmasq --test`), and it restarts the service only if the test
   passes.

The extraction of a root file system with the correct ownership also needs root.
The same pattern can work: Claude puts a tarball in a spool directory, and a
root-owned service extracts it into a fixed directory under the export root. The
checks for such a tarball (paths that leave the directory, links, set-user-ID
files) are not designed yet [A31].

## Updates

The daily job of `unattended-upgrades` runs as root and updates Debian packages
and `claude-code` (see `host-baseline.md` and `claude-code.md`). It is the only
root process that runs by itself in the guest.

The system of the guest is an overlay on a read-only base image (see
`guest-storage.md`). An overlay reset removes the installed updates. Then the
guest starts again with the packages of the base image, and the daily job
updates it again. The base image needs a rebuild at regular times. How often is
not decided yet.

## Not designed yet

- The checks for a root file system tarball [A31].
- How often the base image is rebuilt.

## Tests

`test/test_guest_image.py` checks these points in a virtual machine.

- The Claude account cannot write `/etc/claude-code` (see `claude-code.md`).
- The Claude account is not in `sudo` or `disk`, and `sudo -l` shows nothing.
- `sshd -T -C user=claude` shows `allowagentforwarding no`, and the output for
  the admin account shows `yes`.
- `sshd -T` shows `allowusers` with exactly the two accounts, and the
  `authorizedkeysfile` path.
- The Claude account cannot write `/etc/ssh/authorized_keys/claude`.
- A login with the key works for both accounts.
- In an admin session with `ssh -A`, `sudo true` works. Without `-A`, it fails.
- The Claude account cannot use the agent socket of the admin session [A30].

## Risks

| Risk | Mitigation | Status |
| --- | --- | --- |
| Claude gets root through a kernel or service bug | The guest is disposable. It holds no git or cloud credential. The host firewall limits the network. | Accepted |
| Claude gets root while an admin session is open, and uses the agent | Short admin sessions. The touch policy of the Yubikey. | Accepted |
| A root service reads a file that Claude writes, and runs it | Claude writes data only. A root-owned generator checks it and writes the configuration. | Design intent |
| A group gives too much access (for example `disk`) | One group per device type, matched to the device by `udev` rules. | Design intent |
| A prompt injection reads the Claude login token, which the Claude account must read to use the subscription | Revoke the token if anything looks wrong. See `claude-code.md`. | Accepted by the owner |

## Sources

- `sshd_config(5)`: `AllowUsers`, `AuthorizedKeysFile` (tokens `%u` and `%h`),
  `AllowAgentForwarding` (the note about shell access). Read on Debian 13.
- `dnsmasq(8)`, option `--dhcp-script`: "The process is run as root (assuming
  that dnsmasq was originally run as root) even if dnsmasq is configured to
  change UID to an unprivileged user."
- `exports(5)`: the `no_root_squash` option.
