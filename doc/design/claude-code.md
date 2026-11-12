# Claude Code in the guest

Claude Code is installed in the guest image and logged in once by hand. An
idempotent script configures it. The script copies files from a read-only
directory that the host keeps up to date.

## Decisions

| Topic | Decision | Note |
| --- | --- | --- |
| Plan | The Teams subscription of the owner, and nothing else. The limit is the 5-hour and the weekly quota, not money. No per-token billing, no API key, and no special account. | See `run-control.md` |
| Model | Haiku 5.5 with high thinking, used outside working hours. | Haiku 5.5 is listed as supported in auto mode on the Anthropic API. The documentation does not list Team accounts separately [A20]. |
| Unattended use | The owner states that unattended use is normal on Teams. The owner attends at the start and at the end of each session. | The Anthropic legal page says that OAuth login supports "ordinary use" and that Anthropic may enforce its rules without notice. Keep this note [Q14]. |
| Classifier cost | The owner states that classifier calls do not count against quota on Teams. | The documentation lists classifier calls as counted for Enterprise and API accounts. It does not list Team. The classifier runs on Sonnet 5 by default. |
| Permissions | Auto mode with written guidance. No hard allow, ask, or deny rules. | See Permissions below. |
| Sandbox | The Claude Code sandbox is not used. | See below. |
| Credentials | The guest holds no git or cloud credentials. The Claude login is the only token. The Claude account can read it, and the owner accepts this. | The guest can fetch from the internet without authentication. See Login. |
| Config directory | `/data/claude-config` on the data disk, set with `CLAUDE_CONFIG_DIR`. The home directory stays on the overlay. | See Configuration directory. |
| Managed files | Root owns the managed settings, the managed `CLAUDE.md`, and the plugin directory. Only plugins that the owner configures can add skills, agents, hooks, or MCP servers. | See Managed files. |
| Install | The signed Anthropic apt repository, with one package (`claude-code`). The binary is owned by root. | A prompt injection cannot change the binary. See Install. |
| Channel | The build variable `CLAUDE_CODE_CHANNEL` picks `stable` (the default) or `latest`. | `stable` is about 1 week behind and skips releases with major regressions. |
| Updates | The daily `unattended-upgrades` job updates Claude Code. The owner trusts the official releases. | See Install |
| Sessions | The first sessions are interactive, in tmux. Headless runs (`claude -p`) may come later. | |

## Install

- Install Claude Code in the image for a non-root user. Claude Code refuses
  `--dangerously-skip-permissions` as root, and bitbake also refuses root
  [A18].
- Use the signed apt repository of Anthropic. Do not use the curl-and-bash
  installer. The package installs the binary as root, so Claude cannot change
  it. The native installer puts the binary in the home directory, and a prompt
  injection could replace it there. The package install scripts run as root,
  which needs more trust than the user install. The owner accepts this.
- The image build downloads the signing key, and stops if the fingerprint is not
  `31DD DE24 DDFA B679 F42D 7BD2 BAA9 29FF 1A7E CACE`. The key goes to
  `/etc/apt/keyrings/claude-code.asc`, and the source entry uses `signed-by`
  with that file.
- The build variable `CLAUDE_CODE_CHANNEL` is `stable` or `latest`, and the
  default is `stable`. The build stops on any other value. The variable sets
  the repository URL, the suite name, and the origin line for
  `unattended-upgrades`, so no value appears twice. The `stable` channel is
  about one week behind `latest`, and it skips releases with major
  regressions. A newly launched model can need a newer version than `stable`
  has. Then build the image with `latest`. The guest is disposable, so a
  rebuild is the way to change the channel.
- Pin the repository to one package. The pin file
  `/etc/apt/preferences.d/claude-code` has a negative priority for every
  package of the repository, and a normal priority for `claude-code`. Apt
  gives a record with a package name priority over a `Package: *` record, and
  a negative priority prevents the install. Without the pin, the repository
  could replace a package of Debian, such as `libc6` or `openssh-server`:

  ```
  Package: claude-code
  Pin: release o=Anthropic
  Pin-Priority: 500

  Package: *
  Pin: release o=Anthropic
  Pin-Priority: -1
  ```

- Do not pin a version number. A version pin stops the updates.
- The default origins of `unattended-upgrades` do not include this repository.
  The image adds `origin=Anthropic,codename=<channel>,label=Anthropic`. The
  daily job then updates Claude Code, and the pin limits it to that one
  package. An update replaces the binary. It takes effect the next time Claude
  Code starts, so the owner restarts the app between turns. Claude Code does not
  update itself with this install.
- Test the pin in the guest: `apt-cache policy claude-code` shows a candidate
  from the Anthropic repository, and `apt-cache policy libc6` shows no
  candidate from it.
- Where the package puts its files, and whether an update harms a running
  session, are not verified [A28] [A29].
- Do not set `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC`. It turns off
  auto-updates and the fetch of feature flags. The documentation lists separate
  switches for telemetry and error reporting. Find out which switch does what,
  and test that auto mode still works with it [Q12].

## Login

- The owner logs in once, interactively, with the company Teams account
  (`/login`).
- On Linux, the credentials live in `.credentials.json` with mode 0600, under
  `CLAUDE_CONFIG_DIR`. The directory is on the persistent data disk (see
  Configuration directory), so the login survives resets.
- Claude Code runs as the Claude account, and it must read and refresh the
  login. So the Claude account, and a prompt injection that Claude follows, can
  read the token. No file permission prevents this. The owner accepts the risk.
  Revoke the login if anything looks wrong.
- Do not use `claude setup-token`. It makes a token that is valid for one year.
- No API key, no `ANTHROPIC_AUTH_TOKEN`, no `apiKeyHelper`, and no gateway or
  proxy that holds a key. These paths bill per token and do not use the
  subscription quota. The managed setting `forceLoginMethod: "claudeai"` makes
  Claude Code refuse these credentials at start.
- The guest holds no git credentials. The host pulls the private repositories
  (the settings repository and the plugin marketplace) and copies them to the
  guest over SSH.

## Permissions

Use auto mode with guidance and no hard allow, ask, or deny rules.

- Auto mode is available on all plans. On Team and Enterprise it is on by
  default. An administrator can turn it off in managed settings. The company may
  have done that. Cycle the permission mode, or run `/status`, to check.
- `permissions.defaultMode: auto` does not take effect from project or local
  settings. Set it in the user settings, or start Claude Code with
  `--permission-mode auto`.
- The `autoMode` settings apply from user or managed settings only. Put them in
  the managed settings file (see Managed files), so that Claude cannot change
  them. Write the guidance there: describe the VM, say what is allowed, and say
  what needs a human. Read the auto mode configuration page for the exact keys
  [Q11]. `claude auto-mode config` prints the effective rules.
- The classifier is the only gate for Bash. A prompt injection can influence it.
  Treat it as a tool that reduces prompts, not as a security boundary. The VM
  and the host firewall are the boundary.

## The Claude Code sandbox is not used

- The network proxy of the sandbox has an allowlist that starts empty. In auto
  mode, a host that is not on the list is refused without a prompt. Bitbake
  fetches would fail.
- The documentation shows no setting that allows all hosts. A bare `*` is
  documented for WebFetch rules only.
- The sandbox blocks nested user namespaces by default, and bitbake needs them.
  The fix weakens the sandbox.
- Hardware steps that need root probably fail under the sandbox [A21].
- With the network open, the sandbox does not limit exfiltration. It does not
  limit access to USB or network devices either.

The guest settings template has no sandbox keys. The settings of the owner on
the daily machine stay unchanged.

## Configuration directory

The data disk holds one directory for everything that Claude Code keeps:
`/data/claude-config`. The Claude account owns it, and the mode is 0700.

- `CLAUDE_CONFIG_DIR=/data/claude-config` points Claude Code at it. Claude Code
  then writes into it all that it normally writes to `~/.claude` and
  `~/.claude.json`: the login (`.credentials.json`), `settings.json`,
  `.claude.json`, the plugin state, the transcripts, the prompt history, and the
  auto memory. The home directory stays empty. This was measured with Claude
  Code 2.1.316, with a throwaway home directory, a throwaway config directory,
  `claude auth status`, and a local marketplace.
- Set the variable in `/etc/environment`. `sshd` reads that file through
  `pam_env`, so the variable is set for a login shell, for a command that is
  run with `ssh guest command`, and for tmux. Test all three.
- Do not use symlinks from `~/.claude` to the data disk. A program that writes a
  file by a temp file and a rename can replace the symlink, and then the data
  goes back to the overlay. `CLAUDE_CONFIG_DIR` avoids the problem.
- The home directory is on the overlay, so a reset removes the shell history and
  anything that was installed in the home directory.
- The directory starts empty. The owner logs in once with `/login`. The
  `~/.claude` of the daily machine is not copied.
- The transcripts and the history are plain text and can hold console output.
  Claude Code deletes transcripts after `cleanupPeriodDays` (the default is 30
  days). Include them when you size the data disk.

## Managed files

Root owns the files that Claude must not change. A prompt injection that edits
`settings.json`, or that adds a hook, a skill, or an agent to the data disk,
would otherwise stay after every reset. The files are in the image:

| File or directory | Content |
| --- | --- |
| `/etc/claude-code/managed-settings.json` | The settings below. They rank above user, project, and local settings, and above `--settings`. |
| `/etc/claude-code/CLAUDE.md` | The guidance for the guest. A user cannot exclude this file. |

The image has no marketplace yet, because the owner has no plugin yet. Then no
skill, agent, hook, or MCP server loads at all. When the owner has a plugin, it
goes in a root-owned directory (planned: `/opt/claude-marketplace/`) that is
the only allowed marketplace source (see below).

Keys of the managed settings:

- `permissions.defaultMode: "auto"` and the `autoMode` guidance [Q11].
- `allowManagedPermissionRulesOnly: true`. Rules that Claude Code saves from a
  prompt ("Yes, and do not ask again") have no effect.
- `strictPluginOnlyCustomization: true`. Skills, agents, hooks, and MCP servers
  do not load from the user or project files. This includes the files in the
  repositories that Claude works in. Only plugins load. The owner accepts this.
- `allowManagedHooksOnly: true` and `disableSideloadFlags: true`.
- `strictKnownMarketplaces: []`. This allows no marketplace source, not even
  the official one. When the owner has a plugin, the list gets one `directory`
  entry, and `extraKnownMarketplaces` and `enabledPlugins` name the marketplace
  and the plugin. Plugins from a marketplace that has a local path load from
  that directory, not from a copy [Q10].
- `syncClaudeAiPlugins: false`, `syncClaudeAiSkills: false`, and
  `disableClaudeAiConnectors: true`. The login is a claude.ai login, so the
  account of the owner could bring its connectors and synced items into the
  guest. The guest must not have them.
- `forceLoginMethod: "claudeai"` (see Login).

A managed file has a limit. By default, Claude Code uses only the highest-ranked
managed source. If the admin console of the Teams organization delivers any
policy key, Claude Code ignores this file, and it shows no warning [A35]. On
2026-11-02, `/status` on the daily machine of the owner showed `User settings`
and `Project local settings` as the only sources, so the console delivered
nothing. Check `/status` in the guest after the first login. The line
`Setting sources` must name the managed file.

The option `forceLoginOrgUUID` (only logins of the company organization work) is
not in the design. It needs a build variable with the organization ID. The owner
can decide later.

## Provisioning script

A shell script runs as root at guest boot and on demand. The admin account
starts it with `sudo`, because the Claude account must not be able to change the
files that it writes. It does these things:

- It copies the managed settings and the managed `CLAUDE.md` (and later the
  marketplace) from the shared directory of the host over the files in
  `/etc/claude-code` (and `/opt/claude-marketplace`). The image has a first
  copy, so a guest works without the shared directory.
- It does not touch `/data/claude-config`. The login and the session data stay.
- After a sync, the owner restarts or resumes the Claude session so that changes
  of `CLAUDE.md` apply [A22].

The first version is a shell script. Ansible can replace it later, because the
guest has SSH.

## Tests

`test/test_guest_image.py` checks these points in a virtual machine, with no
login:

- `ssh claude@guest 'echo $CLAUDE_CONFIG_DIR'`, a login shell, and a tmux
  window show `/data/claude-config`, and `claude auth status` names that
  directory.
- After `claude auth status`, the file `.claude.json` is in
  `/data/claude-config`, and the home directory has no `.claude*`.
- After a reboot and after an overlay reset, the files on the data disk are
  still there, and the home directory is empty again.
- `/data/claude-config` is owned by the Claude account with mode 0700.
- The Claude account cannot write `/etc/claude-code`.
- `claude plugin marketplace add` of a local directory fails with a policy
  message. This shows that the managed settings apply.

`test/manual/real-guest.md` has the checks that need a login: the line
`Setting sources` in `/status` [A35], a hook or a skill that must not load, and
the mode of `.credentials.json`.

## Session

The owner connects over SSH and starts tmux inside the guest (`tmux new -A -s
main`), so the session survives disconnects.

## Publish the work

The guest holds no git credential, so Claude cannot push. Claude commits to a
repository in the guest. The owner fetches the commits from the guest on the
daily machine, reviews them, and pushes them from there:

```
git remote add quarry ssh://quarry-guest/data/workspace/repo
git fetch quarry
git push origin quarry/branch:branch
```

- Do not forward an SSH agent into the Claude account. While the session is
  open, every process in that account can ask the agent to sign, and that
  includes Claude and anything that a prompt injection starts. A touch or PIN
  policy on the key does not change this fully. A touch that the owner gives
  for one purpose can authorize another. The guest refuses a forwarded agent for
  this account. The admin account is the only account that gets a forwarded
  agent (see `guest-access.md`).
- The fetch is also a review point. Nothing leaves the quarry without the owner.

## Risks

| Risk | Mitigation | Status |
| --- | --- | --- |
| A prompt injection (fetched source code, board console output) leads to theft of the Claude token or the workspace data | Auto mode guidance. The guest holds no other credentials. The host firewall blocks the LAN, the tailnet, and the host. Revoke the token if anything looks wrong | Accepted by the owner |
| Anthropic enforces its "ordinary use" wording against unattended runs | The owner states that unattended use is normal on Teams. Attend at the start and at the end of each session. Keep the setup single-user | Open. The documentation does not confirm it |
| The classifier is the only gate for Bash, because the sandbox is not used | Auto mode guidance. The VM and the host firewall are the boundary | Accepted by the owner |
| A prompt injection plants a hook, a skill, an agent, or a permission rule in the data disk, and it stays after resets | Root-owned managed settings with the locks above. Only plugins from the root-owned marketplace load | Design intent. Needs [A35] |
| The managed file is ignored, because the admin console of the Teams organization starts to deliver managed settings | Check `Setting sources` in `/status` after each login | Open [A35] |

## Sources

- Legal terms, OAuth login, and "ordinary use":
  <https://code.claude.com/docs/en/legal-and-compliance>
- Auto mode: <https://code.claude.com/docs/en/permission-modes>
- Credentials, the order of the credential sources, and `CLAUDE_CONFIG_DIR`:
  <https://code.claude.com/docs/en/authentication>
- The files in the config directory and what Claude Code writes:
  <https://code.claude.com/docs/en/claude-directory>
- Managed settings: the file path, the order of the managed sources, and the
  lock keys: <https://code.claude.com/docs/en/managed-settings>
- Managed plugin keys and the marketplace sources:
  <https://code.claude.com/docs/en/plugins/org>
- The managed `CLAUDE.md`: <https://code.claude.com/docs/en/memory>
- Gateways, and why a gateway credential bills per token:
  <https://code.claude.com/docs/en/llm-gateway>
- The layout test: Claude Code 2.1.316 with a throwaway `HOME` and
  `CLAUDE_CONFIG_DIR`, run on 2026-11-02.
- The sandbox network proxy and nested namespaces:
  <https://code.claude.com/docs/en/sandboxing>
- Install, the apt repository, key fingerprint, and release channels:
  <https://code.claude.com/docs/en/setup>
- The repository files (`Release` and `Packages`, with `Origin: Anthropic`,
  `Label: Anthropic`, and the one package `claude-code`):
  <https://downloads.claude.ai/claude-code/apt/stable/dists/stable/Release>
- Pin priorities and the order of records: `man apt_preferences`.
- Commands and flags (`--plugin-dir`):
  <https://code.claude.com/docs/en/cli-reference>
- Settings files, precedence, and folder trust:
  <https://code.claude.com/docs/en/settings>
- Settings keys (`autoMode`, `sandbox.*`, `extraKnownMarketplaces`):
  <https://code.claude.com/docs/en/settings-reference>
- Environment variables: <https://code.claude.com/docs/en/env-vars>
- Credential storage on Linux: <https://code.claude.com/docs/en/authentication>
- Claude Code refuses root with the skip-permissions flag:
  <https://github.com/anthropics/claude-code/issues/927>
- The CLI did not auto-install plugins from managed settings:
  <https://github.com/anthropics/claude-code/issues/45323>
- A marketplace with a file source:
  <https://github.com/anthropics/claude-code/issues/57737>
- The devcontainer security limits (a container does not stop the theft of
  anything that the guest can reach):
  <https://docs.claude.com/en/docs/claude-code/devcontainer>
