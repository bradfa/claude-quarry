cat <<'EOF'

claude-quarry installer

Disks that the installer sees:

EOF
lsblk -d -o NAME,SIZE,MODEL,SERIAL,TRAN
cat <<'EOF'

To write the host image to a disk, run:

    quarry-install /dev/DISK

THIS ERASES THE WHOLE DISK. The script asks you to confirm the disk name.

EOF
