# Run control: time limit, quota, and stalls

A timer on the host suspends the whole guest at a set time. The same Claude
session continues when the guest resumes. Claude Code probably has no built-in
run-time limit [A16], so the limit must live outside the guest.

## Time limit

1. About 10 minutes before the deadline, a host timer (a systemd timer or `at`)
   sends a short message into the guest tmux session over SSH. The message asks
   Claude to finish the current step, leave the tree consistent, and wait.
2. At the deadline, the host runs `virsh suspend` on the guest. This freezes all
   guest CPUs, including tmux, Claude Code, and any background bitbake process.
   The owner continues later with `virsh resume`.
3. A hard stop (`virsh destroy`) is a last resort. It ends the tmux session and
   all background tasks. A new session needs `claude --continue` (`-c`, the most
   recent conversation in the directory) or `claude --resume` (`-r`, by ID or
   name).

Suspend is better than the Escape key, because Claude often runs long bitbake
builds in the background. An interrupt stops only the turn of Claude. A
background task that finishes after the deadline may wake Claude and use quota
[Q8].

Claude Code can schedule its own wake-ups (`ScheduleWakeup`, `CronCreate`). The
guest `CLAUDE.md` must forbid them in unattended runs. The host suspend stops
them while the guest is paused.

## After a resume

All points are untested. These things may go wrong:

- The guest clock jumps forward. The QEMU guest agent or `chrony` should correct
  it [A17].
- Network connections time out. Fetches in progress probably fail and retry.
- The bitbake server may react badly to a long freeze. `BB_SERVER_TIMEOUT` may
  matter [Q7].
- USB devices behind the passthrough controller may time out or reset.
- A pending API request may fail. A community wiki says that a temporary API
  error in interactive mode appears inline, and that the process stays at its
  prompt.
- A host reboot ends the guest session.

## Quota

When Claude Code reaches the subscription limit in an interactive session, it
pauses. The user must type `continue` after the reset. This design relies on
that behavior. Do not install tools that continue automatically.

The weekly limit is separate. It can block requests while the 5-hour window
still has room. On Teams plans, usage draws from a per-seat allowance with a
rolling 5-hour window and a weekly window. Claude chat shares the allowance. A
session limit applies to all models, so a switch of model does not restore
access.

Overnight runs and daytime work share the weekly quota, so the owner must watch
`/usage`. The CLI reference lists no command that prints usage outside a
session, so a host script cannot read the quota. The documentation does not say
when the 5-hour window starts. Nobody knows if Haiku usage counts differently on
Teams [Q9].

## Auto mode stalls

In auto mode, Claude Code pauses auto mode and prompts after 3 blocked actions
in a row, or after 20 in total. The limits are not configurable. The total
counter lasts for the session. It resets only when it triggers a fallback. A
long run therefore stalls after 20 blocks in total, even if the blocks are far
apart.

- In an interactive tmux session, the prompt waits for the owner. The owner
  accepts stalls.
- In a `-p` run, there is no prompt. A blocked action does not run, and the run
  continues. Plan for this difference before headless runs.
- One user reported that an unavailable classifier blocked every Bash call
  without a fallback to prompts. This report may be fixed.
- For notification, the host watches the tmux pane over SSH (`tmux
  capture-pane`), so the guest needs no new outbound path.

## Risks

| Risk | Mitigation | Status |
| --- | --- | --- |
| Overnight runs use the weekly quota that daytime work needs | Off-hours use only. Watch `/usage`. Stop at the limit | Open |
| Auto mode stalls after 20 blocks in total | The owner accepts stalls. The host watches the tmux pane | Accepted |

## Sources

- Auto mode plans, models, classifier, thresholds, and `-p` behavior:
  <https://code.claude.com/docs/en/permission-modes>
- Commands and flags (`-c`, `-r`, `-p`): <https://code.claude.com/docs/en/cli-reference>
- `/usage` and the Team limits: <https://code.claude.com/docs/en/costs>
- Pause at the usage limit, manual continue:
  <https://github.com/anthropics/claude-code/issues/35744>
- The weekly limit blocking while 5-hour quota remains:
  <https://github.com/anthropics/claude-code/issues/12829>
- Transient API error handling in interactive mode:
  <https://github.com/cheapestinference/claude-auto-retry/wiki>
- A classifier outage that blocked all Bash calls:
  <https://github.com/anthropics/claude-code/issues/82653>
