# Claude Code in the guest

Claude Code is installed in the guest image and logged in once by hand. An
idempotent script configures it. The script copies files from a read-only
directory that the host keeps up to date.

## Decisions

| Topic | Decision | Note |
| --- | --- | --- |
| Plan | A company Teams subscription. The limit is the 5-hour and the weekly quota, not money. | See `run-control.md` |
| Model | Haiku 5.5 with high thinking, used outside working hours. | Haiku 5.5 is listed as supported in auto mode on the Anthropic API. The documentation does not list Team accounts separately [A20]. |
| Unattended use | The owner states that unattended use is normal on Teams. The owner attends at the start and at the end of each session. | The Anthropic legal page says that OAuth login supports "ordinary use" and that Anthropic may enforce its rules without notice. Keep this note [Q14]. |
| Classifier cost | The owner states that classifier calls do not count against quota on Teams. | The documentation lists classifier calls as counted for Enterprise and API accounts. It does not list Team. The classifier runs on Sonnet 5 by default. |
| Permissions | Auto mode with written guidance. No hard allow, ask, or deny rules. | See Permissions below. |
| Sandbox | The Claude Code sandbox is not used. | See below. |
| Credentials | The guest holds no git or cloud credentials. The Claude login is the only token. | The guest can fetch from the internet without authentication. |
| Sessions | The first sessions are interactive, in tmux. Headless runs (`claude -p`) may come later. | |

## Install

- Install Claude Code in the image for a non-root user. Claude Code refuses
  `--dangerously-skip-permissions` as root, and bitbake also refuses root
  [A18].
- The installer is a curl-and-bash script [A19].
- Pin the version with `claude install <version>`.
- Set `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`. It turns off auto-updates,
  telemetry, and error reporting. It also turns off the fetch of feature flags.
  Test that auto mode still works with it [Q12].

## Login

- The owner logs in once, interactively, with the company Teams account
  (`/login`).
- On Linux, the credentials live in `~/.claude/.credentials.json` with mode
  0600, under `CLAUDE_CONFIG_DIR` when that variable is set. The directory is on
  the persistent data disk (see `guest-storage.md`), so the login survives
  resets.
- Do not use `claude setup-token`. It makes a token that is valid for one year.
- No API key and no other token goes into the guest.
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
- The `autoMode` settings apply from user or managed settings only. The user
  settings file on the daily machine of the owner has `autoMode.environment`,
  and it is empty. Write the guidance there: describe the VM, say what is
  allowed, and say what needs a human. Read the auto mode configuration page for
  the exact keys [Q11]. `claude auto-mode config` prints the effective rules.
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

## Provisioning script

A shell script runs at guest boot and on demand over SSH. It does these things:

- It copies `settings.json` and `CLAUDE.md` from the shared directory over the
  existing files. It copies and does not link, because Claude Code can write to
  `settings.json`.
- It leaves the credentials and the session data alone.
- It installs plugins from a local directory with `--plugin-dir`, or it declares
  a local marketplace in `settings.json` (`extraKnownMarketplaces` and
  `enabledPlugins`). These keys wait for folder trust when they come from a
  repository file. Test the behavior for user settings [Q10]. One bug report
  says that the CLI did not auto-install plugins that managed settings listed.
  Another report shows a marketplace entry with a file source.
- It does not depend on `/etc/claude-code/managed-settings.json` for protection.
  Settings from the administrator take priority over user settings.
- After a sync, the owner restarts or resumes the Claude session so that changes
  of `CLAUDE.md` apply [A22].

The first version is a shell script. Ansible can replace it later, because the
guest has SSH.

## Session

The owner connects over SSH and starts tmux inside the guest (`tmux new -A -s
main`), so the session survives disconnects.

## Risks

| Risk | Mitigation | Status |
| --- | --- | --- |
| A prompt injection (fetched source code, board console output) leads to theft of the Claude token or the workspace data | Auto mode guidance. The guest holds no other credentials. The host firewall blocks the LAN, the tailnet, and the host. Revoke the token if anything looks wrong | Accepted by the owner |
| Anthropic enforces its "ordinary use" wording against unattended runs | The owner states that unattended use is normal on Teams. Attend at the start and at the end of each session. Keep the setup single-user | Open. The documentation does not confirm it |
| The classifier is the only gate for Bash, because the sandbox is not used | Auto mode guidance. The VM and the host firewall are the boundary | Accepted by the owner |

## Sources

- Legal terms, OAuth login, and "ordinary use":
  <https://code.claude.com/docs/en/legal-and-compliance>
- Auto mode: <https://code.claude.com/docs/en/permission-modes>
- The sandbox network proxy and nested namespaces:
  <https://code.claude.com/docs/en/sandboxing>
- Commands and flags (`--plugin-dir`, `claude install`):
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
