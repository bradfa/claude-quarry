# Image tests

These tests boot the images of this project in QEMU and check them. They
replace the old manual test pages. They never run on a real host, and they never
build an image.

## Quick start

You need a Debian 13 computer with access to `/dev/kvm`. These steps build the
host image and run all tests. They do not change your own `image/build.conf`.

1. Install the packages (as root):

   ```
   apt install debos bmap-tools zstd qemu-system-x86 qemu-utils ovmf \
       openssh-client util-linux python3-pytest python3-venv
   ```

2. Make a test key and a test configuration. Run this in the top directory of
   the repository:

   ```
   mkdir -p image/build
   ssh-keygen -t ed25519 -N '' -C quarry-test -f image/build/test-key
   cat > image/build/test.conf <<EOF
   ADMIN_USER=tester
   ADMIN_SSH_KEY_FILE=$PWD/image/build/test-key.pub
   SUDO_MODE=agent
   KERNEL_CMDLINE_EXTRA=console=tty0 console=ttyS0,115200
   EOF
   ```

3. Build the host image. This takes some minutes and needs Internet access:

   ```
   BUILD_CONF=image/build/test.conf image/build.sh host
   ```

4. Run the tests. The suite boots three machines, and one test waits up to 5
   minutes for the time sync:

   ```
   python3 -m venv --system-site-packages test/.venv
   BUILD_CONF=image/build/test.conf test/.venv/bin/python -m pytest test -v \
       --junitxml=image/build/junit.xml
   ```

The last line of the output must show no failed test. The suite starts its own
SSH agent for the agent mode of `sudo`, and it never uses your agent. The tests
for the other sudo mode (`SUDO_MODE=nopasswd`) show as skipped. To run them,
change the line in `image/build/test.conf`, build again, and run step 4 again.

What the configuration means:

| Line | Reason |
| --- | --- |
| `ADMIN_USER=tester` | Any valid Linux user name. The image has no other user |
| `ADMIN_SSH_KEY_FILE` | A public key. The private key must be in the same directory, with the same name but without `.pub`, and it must have no passphrase. Use a new key, not your own |
| `SUDO_MODE=agent` | `sudo` asks an SSH agent to sign a challenge. This is the default of the project. The other mode is `nopasswd`, where `sudo` needs nothing |
| `KERNEL_CMDLINE_EXTRA` | Makes the serial port the system console. Test 3.1 reads the boot messages from it |

`HOST_NAME` is not in the file, so the default `quarry-host` applies. The tests
read the same default.

## Without KVM

QEMU then emulates the CPU. The tests still work, but each boot takes many
minutes, and the suite waits up to 30 minutes for each boot.

## Dependencies

The suite uses Python 3.13, the standard library, and Debian packages. It uses
no package from PyPI at this time.

- A Debian package is always acceptable. The project trusts Debian stable, and
  Debian signs its packages. Prefer a Debian package to a PyPI package. For
  example, pytest 8.3 comes from the `python3-pytest` package of Debian 13. The
  venv uses `--system-site-packages`, so it sees the Debian packages.
- A PyPI package is the exception, because attackers publish poisoned PyPI
  packages. Use one only when Debian has no package for it, the standard
  library cannot do the job, and the job is too big to write here. Then follow
  these rules:
  1. Pin every package, including the packages that it needs, with a hash in a
     requirements file.
  2. Install with `pip install --require-hashes -r <file>` in a venv.
  3. Name the reason in the requirements file.

## Settings

The settings have the same names as in `image/build.sh`: `ADMIN_USER`,
`ADMIN_SSH_KEY_FILE`, `SUDO_MODE`, and `HOST_NAME`. They come from the
environment first, then from the file that `BUILD_CONF` names (the default is
`image/build.conf`). They must match the images that you test.

| Variable | Meaning |
| --- | --- |
| `BUILD_CONF` | The configuration file, as for `image/build.sh` |
| `QUARRY_TEST_HOST_IMAGE` | The host image to test. The default is `image/build/host.img` |
| `QUARRY_TEST_BOOT_TIMEOUT` | Seconds to wait for each boot. The default is 240 with KVM |
| `QUARRY_TEST_KEEP` | Set to `1` to keep the disks of the test machines |

## Results and logs

- Do not commit test results.
- `image/build/junit.xml` holds the results.
- `image/build/test-logs/` holds the serial log and the QEMU log of each test
  machine. Send these files with a failure report.

## Layout

| File | Content |
| --- | --- |
| `settings.py` | Reads the settings |
| `vm.py` | Starts QEMU with OVMF on a free port, and runs commands over SSH |
| `conftest.py` | The fixtures |
| `test_host_image.py` | The host image tests. A name such as `test_4_03` is check 4.3 of the old manual page |

Each test machine boots from a qcow2 overlay of the image, so the image file
does not change.
