#!/usr/bin/env bash
# Build the claude-quarry images with debos, in a fixed order.
#
# Each setting comes from the first of these sources that has a value:
#   1. an environment variable
#   2. image/build.conf (KEY=value lines, see build.conf.example)
#   3. a prompt, only when stdin is a terminal
# A required setting with no value stops the script before debos starts.
#
# Usage: image/build.sh [host] [installer] [guest]
#
# With no target, the script builds the host image, then the installer, then
# the guest image. The installer carries the host image, so the order of these
# two is fixed. The guest image build downloads Claude Code from the Anthropic
# apt repository, so it needs access to downloads.claude.ai.

set -euo pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
build_dir=$script_dir/build
conf_file=${BUILD_CONF:-$script_dir/build.conf}

die() {
    echo "build.sh: $*" >&2
    exit 1
}

# The file is parsed, not sourced, so a config file cannot run code.
load_config() {
    local file=$1 key value
    [[ -r $file ]] || return 0
    while IFS='=' read -r key value || [[ -n $key ]]; do
        [[ $key =~ ^[[:space:]]*(#|$) ]] && continue
        case $key in
            ADMIN_USER | ADMIN_SSH_KEY_FILE | SUDO_MODE | HOST_NAME | IMAGE_SIZE | INSTALLER_SIZE | MIRROR | KERNEL_CMDLINE_EXTRA) ;;
            CLAUDE_USER | CLAUDE_CODE_CHANNEL | GUEST_NAME | GUEST_IMAGE_SIZE | GUEST_EXTRA_PACKAGES) ;;
            SHIM_REMOVE_SIGNATURE) ;;
            *) die "unknown setting in $file: $key" ;;
        esac
        [[ -n ${!key:-} ]] || printf -v "$key" '%s' "$value"
    done <"$file"
}

prompt_for() {
    local name=$1 text=$2 reply
    [[ -z ${!name:-} ]] || return 0
    [[ -t 0 ]] || die "$name is not set and stdin is not a terminal"
    read -r -p "$text: " reply
    printf -v "$name" '%s' "$reply"
}

load_config "$conf_file"

prompt_for ADMIN_USER "Name of the first (administrator) user"
prompt_for ADMIN_SSH_KEY_FILE "Path to the SSH public key file for that user"

: "${SUDO_MODE:=agent}"
: "${HOST_NAME:=quarry-host}"
: "${IMAGE_SIZE:=34GB}"
: "${INSTALLER_SIZE:=8GB}"
: "${MIRROR:=http://deb.debian.org/debian/}"
: "${KERNEL_CMDLINE_EXTRA:=}"
: "${CLAUDE_USER:=claude}"
: "${CLAUDE_CODE_CHANNEL:=stable}"
: "${GUEST_NAME:=quarry-guest}"
: "${GUEST_IMAGE_SIZE:=32GB}"
: "${GUEST_EXTRA_PACKAGES:=}"
: "${SHIM_REMOVE_SIGNATURE:=none}"

# The recipe repeats these checks, so a typo fails in seconds and not after
# a debootstrap run.
[[ $ADMIN_USER =~ ^[a-z_][a-z0-9_-]{0,31}$ ]] ||
    die "ADMIN_USER must be a lowercase Linux user name"
[[ $ADMIN_USER != root ]] || die "ADMIN_USER must not be root"
[[ $SUDO_MODE == agent || $SUDO_MODE == nopasswd ]] ||
    die "SUDO_MODE must be agent or nopasswd"
[[ $HOST_NAME =~ ^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$ ]] ||
    die "HOST_NAME is not a valid host name"
[[ $IMAGE_SIZE =~ ^[0-9]+GB$ ]] || die "IMAGE_SIZE must look like 34GB"
[[ $INSTALLER_SIZE =~ ^[0-9]+GB$ ]] || die "INSTALLER_SIZE must look like 8GB"
[[ $SHIM_REMOVE_SIGNATURE == none || $SHIM_REMOVE_SIGNATURE == 2011 || $SHIM_REMOVE_SIGNATURE == 2023 ]] ||
    die "SHIM_REMOVE_SIGNATURE must be none, 2011, or 2023"
[[ $CLAUDE_USER =~ ^[a-z_][a-z0-9_-]{0,31}$ ]] ||
    die "CLAUDE_USER must be a lowercase Linux user name"
[[ $CLAUDE_USER != root ]] || die "CLAUDE_USER must not be root"
[[ $CLAUDE_USER != "$ADMIN_USER" ]] || die "CLAUDE_USER and ADMIN_USER must differ"
[[ $CLAUDE_CODE_CHANNEL == stable || $CLAUDE_CODE_CHANNEL == latest ]] ||
    die "CLAUDE_CODE_CHANNEL must be stable or latest"
[[ $GUEST_NAME =~ ^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$ ]] ||
    die "GUEST_NAME is not a valid host name"
[[ $GUEST_IMAGE_SIZE =~ ^[0-9]+GB$ ]] || die "GUEST_IMAGE_SIZE must look like 32GB"
# Debian package names, separated by one space. A name does not start with a
# hyphen, so it cannot be an option of apt-get.
[[ -z $GUEST_EXTRA_PACKAGES || $GUEST_EXTRA_PACKAGES =~ ^[a-z0-9][a-z0-9.+-]*( [a-z0-9][a-z0-9.+-]*)*$ ]] ||
    die "GUEST_EXTRA_PACKAGES must be Debian package names, separated by one space"
# The recipe puts this value in a YAML file, and debos reads {{ }} as template
# syntax. Kernel options do not need these characters.
case $KERNEL_CMDLINE_EXTRA in
    *[\'\"\\\`\$\{\}]* | *$'\n'*)
        die "KERNEL_CMDLINE_EXTRA has a character that is not allowed: ' \" \\ \` \$ { } or a new line"
        ;;
esac

[[ -r $ADMIN_SSH_KEY_FILE ]] || die "cannot read $ADMIN_SSH_KEY_FILE"
admin_ssh_key=$(<"$ADMIN_SSH_KEY_FILE")
[[ $admin_ssh_key != *$'\n'* ]] ||
    die "$ADMIN_SSH_KEY_FILE must hold exactly one public key"
key_re='^(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp[0-9]+|sk-ssh-ed25519@openssh\.com|sk-ecdsa-sha2-nistp256@openssh\.com)[[:space:]]+[A-Za-z0-9+/=]+([[:space:]].*)?$'
[[ $admin_ssh_key =~ $key_re ]] ||
    die "$ADMIN_SSH_KEY_FILE does not look like an SSH public key"
# The recipe puts the key inside single quotes in a shell command, and debos
# reads {{ }} as template syntax. The comment must not hold these characters.
case $admin_ssh_key in
    *\'* | *\"* | *\\* | *\`* | *\$* | *\{* | *\}*)
        die "the comment of the key in $ADMIN_SSH_KEY_FILE has a character that is not allowed: ' \" \\ \` \$ { }"
        ;;
esac

command -v debos >/dev/null || die "debos is not installed"

build_host() {
    debos --artifactdir="$build_dir" \
        -t "admin_user:$ADMIN_USER" \
        -t "admin_ssh_key:$admin_ssh_key" \
        -t "sudo_mode:$SUDO_MODE" \
        -t "host_name:$HOST_NAME" \
        -t "image_size:$IMAGE_SIZE" \
        -t "mirror:$MIRROR" \
        -t "kernel_cmdline_extra:$KERNEL_CMDLINE_EXTRA" \
        -t "shim_remove_signature:$SHIM_REMOVE_SIGNATURE" \
        "$script_dir/host.yaml"
}

# By default, debos keeps the root file system tree in the RAM of its build
# machine (2 GB). The compressed host image does not fit there, and the kernel
# kills the copy. --scratchsize puts the tree on disk. The tree always fits in
# the installer image, so INSTALLER_SIZE is a safe size.
build_installer() {
    debos --artifactdir="$build_dir" \
        --scratchsize="$INSTALLER_SIZE" \
        -t "installer_size:$INSTALLER_SIZE" \
        -t "mirror:$MIRROR" \
        -t "kernel_cmdline_extra:$KERNEL_CMDLINE_EXTRA" \
        -t "shim_remove_signature:$SHIM_REMOVE_SIGNATURE" \
        "$script_dir/installer.yaml"
}

build_guest() {
    debos --artifactdir="$build_dir" \
        -t "admin_user:$ADMIN_USER" \
        -t "claude_user:$CLAUDE_USER" \
        -t "admin_ssh_key:$admin_ssh_key" \
        -t "sudo_mode:$SUDO_MODE" \
        -t "guest_name:$GUEST_NAME" \
        -t "guest_image_size:$GUEST_IMAGE_SIZE" \
        -t "guest_extra_packages:$GUEST_EXTRA_PACKAGES" \
        -t "claude_code_channel:$CLAUDE_CODE_CHANNEL" \
        -t "mirror:$MIRROR" \
        -t "kernel_cmdline_extra:$KERNEL_CMDLINE_EXTRA" \
        "$script_dir/guest.yaml"
}

mkdir -p "$build_dir"

if (($# == 0)); then
    set -- host installer guest
fi

for target in "$@"; do
    case $target in
        host) build_host ;;
        installer) build_installer ;;
        guest) build_guest ;;
        *) die "unknown target: $target" ;;
    esac
done
