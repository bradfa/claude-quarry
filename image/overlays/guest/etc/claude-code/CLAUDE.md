# The quarry guest

You run in a disposable virtual machine (the quarry guest) for embedded
development.

- You are an unprivileged user. You have no `sudo`, and you cannot install
  Debian packages. If a task needs a package, say so and stop.
- The machine holds no git credentials. Commit to the local repository, and do
  not try to push. The owner fetches your commits from this machine.
- The system disk resets from time to time. Files in your home directory can
  disappear. Keep all work on the data disk (`/data`).
- The build tools for the Yocto Project are installed, and you can run them as
  your user.
- Do not change anything in `/etc/claude-code`. It belongs to root, and the
  owner manages it.
