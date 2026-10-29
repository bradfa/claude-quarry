#!/usr/bin/env bash
# Build the claude-quarry images with debos, in a fixed order.
#
# Each setting comes from the first of these sources that has a value:
#   1. an environment variable
#   2. image/build.conf (KEY=value lines, see build.conf.example)
#   3. a prompt, only when stdin is a terminal
# A required setting with no value stops the script before debos starts.
#
# Usage: image/build.sh [host]

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
            ADMIN_USER | ADMIN_SSH_KEY_FILE | SUDO_MODE | HOST_NAME | IMAGE_SIZE | MIRROR | KERNEL_CMDLINE_EXTRA) ;;
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
: "${MIRROR:=http://deb.debian.org/debian/}"
: "${KERNEL_CMDLINE_EXTRA:=}"

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
        "$script_dir/host.yaml"
}

mkdir -p "$build_dir"

if (($# == 0)); then
    set -- host
fi

for target in "$@"; do
    case $target in
        host) build_host ;;
        *) die "unknown target: $target" ;;
    esac
done
