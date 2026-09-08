#!/bin/zsh
# Inspect this Pi card without filesystem repair or configuration writes.
emulate -LR zsh
set -eu
set -o pipefail
export PATH=/usr/bin:/bin:/usr/sbin:/sbin
umask 077

fail() { print -u2 -- "$*"; exit 1; }
[[ $# == 1 && "$1" == /dev/disk<-> ]] || fail 'Usage: sudo /bin/zsh inspect-pi-card-readonly.zsh /dev/diskN'
[[ $EUID == 0 && -n "${SUDO_UID:-}" && -n "${SUDO_GID:-}" ]] || fail 'Run with sudo from your normal Mac account.'
DISK="$1"
ROOT="${DISK}s2"
RAW_ROOT="/dev/r${ROOT#/dev/}"
RAW_BOOT="/dev/r${DISK#/dev/}s1"
DEBUGFS=/opt/homebrew/opt/e2fsprogs/sbin/debugfs
E2FSCK=/opt/homebrew/opt/e2fsprogs/sbin/e2fsck
DUMPE2FS=/opt/homebrew/opt/e2fsprogs/sbin/dumpe2fs
for TOOL in "$DEBUGFS" "$E2FSCK" "$DUMPE2FS" /sbin/fsck_msdos; do
  [[ -x "$TOOL" ]] || fail "Missing tool: $TOOL"
done

OUT=$(/usr/bin/mktemp -d /private/tmp/frontier-card-inspect.XXXXXX)
trap '/usr/sbin/chown -R "$SUDO_UID:$SUDO_GID" "$OUT"' EXIT
/usr/sbin/diskutil info -plist "$DISK" > "$OUT/disk.plist"
/usr/sbin/diskutil info -plist "${DISK}s1" > "$OUT/boot.plist"
/usr/sbin/diskutil info -plist "$ROOT" > "$OUT/root.plist"
field() { /usr/libexec/PlistBuddy -c "Print :$2" "$OUT/$1.plist"; }
[[ "$(field disk Internal)" == false ]] || fail 'Refusing an internal disk.'
[[ "$(field disk WholeDisk)" == true ]] || fail 'Expected a whole disk.'
[[ "$(field disk TotalSize)" == 127865454592 ]] || fail 'This is not the identified 127.9 GB Pi card.'
[[ "$(field boot VolumeUUID)" == BDFDE5B3-A7DB-3688-9420-F13710AC609C ]] || fail 'Pi boot-volume identity does not match.'
[[ "$(field boot VolumeName)" == system-boot ]] || fail 'Wrong boot label.'
[[ "$(field root Content)" == Linux ]] || fail 'Second partition is not Linux.'
[[ "$(field root MountPoint)" == '' ]] || fail 'Linux partition is mounted; refusing inspection.'

print -- '1/4 Saving small boot configuration files to the Mac.'
BOOT_MOUNT="$(field boot MountPoint)"
if [[ -n "$BOOT_MOUNT" ]]; then
  /bin/mkdir "$OUT/boot"
  for REL in config.txt autoboot.txt current/cmdline.txt current/state frontier-network-status.txt; do
    if [[ -f "$BOOT_MOUNT/$REL" ]]; then
      /bin/cp "$BOOT_MOUNT/$REL" "$OUT/boot/${REL//\//_}"
    fi
  done
fi

print -- '2/4 Unmounting, then checking both filesystems with repairs DISABLED.'
/usr/sbin/diskutil unmountDisk "$DISK"
FAT_EXIT=0
/sbin/fsck_msdos -n "$RAW_BOOT" > "$OUT/boot-fsck.txt" 2>&1 || FAT_EXIT=$?
EXT4_EXIT=0
"$E2FSCK" -f -n "$RAW_ROOT" > "$OUT/linux-fsck.txt" 2>&1 || EXT4_EXIT=$?
"$DUMPE2FS" -h "$RAW_ROOT" > "$OUT/linux-header.txt" 2>&1 || true

# debugfs does not report all read errors through its exit status. Preserve its
# messages for inspection; never interpret an exit status alone as success.
readfs() { "$DEBUGFS" -R "$1" "$RAW_ROOT" >> "$OUT/debugfs.txt" 2>&1; }
dump_small() {
  local SRC="$1" DEST="$2" SIZE
  SIZE=$("$DEBUGFS" -R "stat $SRC" "$RAW_ROOT" 2>/dev/null | /usr/bin/sed -nE 's/^.*Size: *([0-9]+).*$/\1/p' | /usr/bin/head -n 1)
  if [[ "$SIZE" == <-> ]] && (( SIZE <= 134217728 )); then
    readfs "dump $SRC $OUT/$DEST"
  else
    print -- "Skipped missing/unreadable/oversize file: $SRC" >> "$OUT/debugfs.txt"
  fi
}

print -- '3/4 Copying selected Linux configuration and current boot logs to the Mac.'
for SRC in /etc/hostname /usr/lib/os-release /etc/fstab /etc/machine-id /var/log/syslog /var/log/kern.log /var/log/cloud-init.log; do
  dump_small "$SRC" "${SRC//\//_}"
done
for DIR in /etc/netplan /etc/systemd/network /etc/systemd/system /var/log/journal /home/rover/frontier-rover/software/pi; do
  readfs "ls -l $DIR"
done
/bin/mkdir "$OUT/config"
for DIR in /etc/netplan /etc/systemd/network /etc/cloud/cloud.cfg.d; do
  readfs "rdump $DIR $OUT/config"
done
for UNIT in frontier-rover-control.service frontier-network-bootstrap.service frontier-network-report.service frontier-usb-recovery.service; do
  dump_small "/etc/systemd/system/$UNIT" "$UNIT"
done
if [[ -f "$OUT/_etc_machine-id" ]]; then
  MACHINE_ID="$(/usr/bin/tr -d '\n\r' < "$OUT/_etc_machine-id")"
  if [[ ${#MACHINE_ID} == 32 && "$MACHINE_ID" != *[^0-9a-f]* ]]; then
    readfs "ls -l /var/log/journal/$MACHINE_ID"
    dump_small "/var/log/journal/$MACHINE_ID/system.journal" system.journal
  fi
fi

print -- '4/4 Inspection finished. No repairs or network changes were made.'
print -- "FAT check exit: $FAT_EXIT; Linux check exit: $EXT4_EXIT"
if /usr/bin/grep -Eq 'needs_recovery|orphan_present' "$OUT/linux-header.txt"; then
  print -- 'Linux has pending journal/orphan state. Exit 0 is NOT a fully clean-filesystem verdict.'
fi
if /usr/bin/grep -Eq 'Free (blocks|inodes) count wrong|Fix\? no|Clear\? no' "$OUT/linux-fsck.txt"; then
  print -- 'The read-only check reported uncorrected bookkeeping differences. Review linux-fsck.txt.'
fi
print -- "Report directory: $OUT"
print -- 'Leave the card connected while the report is reviewed. It is unmounted.'
print -- 'A dirty journal can affect a read-only check; errors alone do not prove failed hardware.'
