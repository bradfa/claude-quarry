# Checks in a real guest

The automatic tests in `test/test_guest_image.py` cannot log in to Claude Code,
because the login needs your browser and your account. Run these checks by hand
in a guest after the first login. Do not write results in this file. Keep them
in your own notes, and delete the matching row in `doc/assumptions.md` when a
check proves a claim.

## Prerequisites

- A guest that started from the guest image with a data disk, and an SSH login
  as the Claude account (see `doc/design/guest-access.md`).
- The Teams account of the owner.

## 1. Login and managed settings

Log in as the Claude account. Start `claude` in tmux, and run `/login`.

| # | Check | Expected result | Open point |
| --- | --- | --- | --- |
| 1.1 | `/status`, line `Setting sources` | It names the managed settings file. If it shows only `User settings`, the Teams admin console delivers its own managed settings, and the file is ignored | A35 |
| 1.2 | `/status`, line `Login method` | `Claude Team account` | |
| 1.3 | `ls -l /data/claude-config/.credentials.json` | Owner is the Claude account, mode 0600 | |
| 1.4 | `claude auth status` after a reboot of the guest and after an overlay reset | Still logged in | |
| 1.5 | Press Shift+Tab until the mode changes, or run `/status` | The permission mode is `auto`, and `claude auto-mode config` lists the entries of `autoMode.environment` from the managed file | Q11 |
| 1.6 | `ANTHROPIC_API_KEY=x claude` | Claude Code refuses to start with that key | |

## 2. Locks

| # | Check | Expected result | Open point |
| --- | --- | --- | --- |
| 2.1 | Write a hook in `/data/claude-config/settings.json`, for example a `SessionStart` hook that runs `touch /tmp/hook-ran`. Start a new session | `/tmp/hook-ran` does not exist | |
| 2.2 | Write a skill in `/data/claude-config/skills/test/SKILL.md` and another in the workspace repository under `.claude/skills/`. Start a new session and run `/skills` | Neither skill is listed | |
| 2.3 | Add a permission rule in `/data/claude-config/settings.json`, for example `Bash(touch /tmp/rule-test)` in `permissions.allow` | The rule has no effect | |
| 2.4 | `/plugin` | No marketplace is available, and the official marketplace is not registered | Q10 |
| 2.5 | `/mcp` | No claude.ai connectors are listed | |
| 2.6 | `/memory` | `/etc/claude-code/CLAUDE.md` is loaded | |

## 3. Updates

| # | Check | Expected result | Open point |
| --- | --- | --- | --- |
| 3.1 | As the admin account: `sudo apt-get install --only-upgrade claude-code` during a session, when a newer version exists | The running session continues | A29 |
| 3.2 | `dpkg -L claude-code` | Lists the files that the package installs. Compare with the build log | A28 |
