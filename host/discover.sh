#!/bin/bash
# Read facts about the host that the design and the runbook depend on.
#
# The script only reads. It runs sudo for the commands that need root, so run
# it as the admin user. Run it again after a hardware change (for example after
# the xHCI card is in the host) and compare the two outputs.
#
# Usage: host/discover.sh [OUTPUT_FILE]
#
# Without OUTPUT_FILE, the output goes to host/discovery/ with the host name and
# the date in the name.

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
output="${1:-$script_dir/discovery/$(hostname)-$(date +%Y%m%d-%H%M%S).txt}"
mkdir -p "$(dirname "$output")"

# Run a command as root. A command that fails shows its error in the output, and
# the script goes on, because a missing tool is also a fact about the host.
as_root() {
    if [[ $EUID -eq 0 ]]; then
        "$@"
    else
        sudo "$@"
    fi
}

section() {
    echo "== $1"
}

discover() {
    section "os/kernel"
    head -3 /etc/os-release
    uname -r
    cat /proc/cmdline

    section "cpu/kvm"
    lscpu | grep -E 'Model name|Virtualization' || true
    ls -l /dev/kvm || true

    section "dmesg"
    as_root dmesg | grep -Ei 'DMAR|IOMMU|RMRR|x2apic|vmx' || true

    section "iommu groups"
    local group device
    for group in /sys/kernel/iommu_groups/*; do
        echo "group ${group##*/}:"
        for device in "$group"/devices/*; do
            echo -n "  "
            lspci -nns "${device##*/}"
        done
    done

    section "iommu reserved regions"
    for group in /sys/kernel/iommu_groups/*; do
        echo "group ${group##*/}:"
        cat "$group/reserved_regions"
    done

    section "pci reset methods"
    for device in /sys/bus/pci/devices/*; do
        if [[ -r "$device/reset_method" ]]; then
            echo "${device##*/}: $(cat "$device/reset_method")"
        fi
    done

    section "pci tree"
    lspci -tv

    section "usb"
    lsusb -t

    section "net"
    ip -br link
    ip -br addr
    ip route

    section "memory/disk"
    free -h
    lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT
    df -h /

    section "storage"
    lsblk -d -o NAME,MODEL,SIZE,ROTA,TRAN
    as_root vgs -o vg_name,vg_size,vg_free || true
    as_root lvs || true

    section "boot"
    if [[ -d /sys/firmware/efi ]]; then
        echo "firmware: UEFI"
    else
        echo "firmware: BIOS"
    fi
    as_root bootctl status 2>&1 | head -30 || true
    cat /etc/kernel/cmdline 2>&1 || true

    section "packages"
    dpkg-query -W -f '${Package} ${Version}\n' \
        | grep -E '^[^ ]*(qemu|libvirt|virtiofsd|nftables|iptables|tailscale|network-manager|wpasupplicant|iwd|systemd-resolved|unattended-upgrades|claude-code|shim|systemd-boot)' || true

    section "firewall"
    command -v nft iptables || true
    as_root nft list ruleset 2>&1 | head -80 || true

    section "tailscale"
    if command -v tailscale > /dev/null; then
        tailscale status --peers=false 2>&1 | head -5 || true
        tailscale debug prefs 2>&1 | grep -E 'RouteAll|AdvertiseRoutes|ExitNode|RunSSH|ShieldsUp' || true
    else
        echo "tailscale is not installed"
    fi

    section "network services"
    systemctl is-active NetworkManager systemd-networkd wpa_supplicant iwd || true

    section "user"
    id
    getent group kvm libvirt || true

    section "modules"
    lsmod | grep -E '^(kvm|vfio)' || true
}

discover 2>&1 | tee "$output"
echo "Written to $output" >&2
