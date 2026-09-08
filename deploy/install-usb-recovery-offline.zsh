#!/bin/zsh
set -euo pipefail

export PATH=/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:/opt/homebrew/sbin

readonly WHOLE_DISK=/dev/disk4
readonly BOOT_DEVICE=/dev/disk4s1
readonly ROOT_DEVICE=/dev/disk4s2
readonly EXPECTED_SIZE='127.9 GB'
readonly DISKUTIL=/usr/sbin/diskutil
readonly DEBUGFS=/opt/homebrew/opt/e2fsprogs/sbin/debugfs
readonly E2FSCK=/opt/homebrew/opt/e2fsprogs/sbin/e2fsck
readonly SOURCE=/Users/jackcoleman/Developer/frontier-rover/deploy/frontier-usb-recovery.service
readonly REMOTE=/etc/systemd/system/frontier-usb-recovery.service
readonly ENABLED=/etc/systemd/system/multi-user.target.wants/frontier-usb-recovery.service

[[ $EUID -eq 0 ]] || {
    echo "Run this script with sudo."
    exit 1
}

for required_path in "$DISKUTIL" "$DEBUGFS" "$E2FSCK" "$SOURCE"; do
    [[ -e $required_path ]] || {
        echo "Required file is missing: $required_path"
        exit 1
    }
done

[[ -b $WHOLE_DISK && -b $BOOT_DEVICE && -b $ROOT_DEVICE ]] || {
    echo "The expected Raspberry Pi card is not /dev/disk4. Nothing was changed."
    exit 1
}

disk_info=$("$DISKUTIL" info "$WHOLE_DISK")
print -r -- "$disk_info" | grep -q 'Device Location:.*External'
print -r -- "$disk_info" | grep -q "Disk Size:.*${EXPECTED_SIZE}"

disk_layout=$("$DISKUTIL" list "$WHOLE_DISK")
print -r -- "$disk_layout" | grep -q 'Windows_FAT_32 system-boot'
print -r -- "$disk_layout" | grep -q 'Linux.*disk4s2'

stamp=$(date +%Y%m%d-%H%M%S)
backup=/private/tmp/frontier-usb-recovery-backup-$stamp
verify=/private/tmp/frontier-usb-recovery-verify-$stamp
mkdir -m 0700 "$backup"

echo "1/4 Unmounting and checking the Pi filesystem."
"$DISKUTIL" unmountDisk "$WHOLE_DISK"
set +e
"$E2FSCK" -fy "$ROOT_DEVICE"
fsck_result=$?
set -e
if (( fsck_result > 1 )); then
    echo "Filesystem repair failed with status $fsck_result. Nothing was installed."
    exit 1
fi

echo "2/4 Backing up and installing the USB recovery service."
"$DEBUGFS" -R "dump -p $REMOTE $backup/frontier-usb-recovery.service" \
    "$ROOT_DEVICE" >/dev/null 2>&1 || true
"$DEBUGFS" -w -R "rm $REMOTE" "$ROOT_DEVICE" >/dev/null 2>&1 || true
"$DEBUGFS" -w -R "write $SOURCE $REMOTE" "$ROOT_DEVICE" >/dev/null
"$DEBUGFS" -w -R "set_inode_field $REMOTE mode 0100644" "$ROOT_DEVICE" >/dev/null
"$DEBUGFS" -w -R "set_inode_field $REMOTE uid 0" "$ROOT_DEVICE" >/dev/null
"$DEBUGFS" -w -R "set_inode_field $REMOTE gid 0" "$ROOT_DEVICE" >/dev/null

"$DEBUGFS" -w -R "rm $ENABLED" "$ROOT_DEVICE" >/dev/null 2>&1 || true
"$DEBUGFS" -w -R \
    "symlink $ENABLED ../frontier-usb-recovery.service" \
    "$ROOT_DEVICE" >/dev/null

echo "3/4 Verifying the installed file, boot link, and filesystem."
"$DEBUGFS" -R "dump -p $REMOTE $verify" "$ROOT_DEVICE" >/dev/null
cmp -s "$SOURCE" "$verify" || {
    echo "Verification failed: installed service differs from its source."
    exit 1
}
"$DEBUGFS" -R "stat $ENABLED" "$ROOT_DEVICE" 2>&1 | \
    grep -q 'frontier-usb-recovery.service' || {
        echo "Verification failed: USB recovery is not enabled."
        exit 1
    }

set +e
"$E2FSCK" -fn "$ROOT_DEVICE"
verify_result=$?
set -e
if (( verify_result != 0 )); then
    echo "Post-write filesystem verification failed. Do not boot the card."
    exit 1
fi

echo "4/4 Ejecting the card safely."
sync
"$DISKUTIL" eject "$WHOLE_DISK"

echo "USB recovery installed and verified."
echo "Backup: $backup"
echo "After boot, the Pi will always use USB address 10.55.0.2."
