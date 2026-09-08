#!/bin/zsh
# Restore only the owner-approved camera card used for Pi recovery.
emulate -LR zsh
set -eu
set -o pipefail
export PATH=/usr/bin:/bin:/usr/sbin:/sbin
umask 077

fail() { print -u2 -- "$*"; exit 1; }
(( $# == 1 )) || fail 'Usage: /bin/zsh restore-camera-card.zsh /dev/diskN'
[[ "$1" == /dev/disk<-> ]] || fail 'Expected a whole /dev/diskN.'
DISK="$1"
OUT=$(/usr/bin/mktemp -d /private/tmp/frontier-camera-card-restore.XXXXXX)
field() { /usr/libexec/PlistBuddy -c "Print :$2" "$OUT/$1.plist"; }

/usr/sbin/diskutil info -plist "$DISK" > "$OUT/disk-before.plist"
/usr/sbin/diskutil info -plist "${DISK}s1" > "$OUT/volume-before.plist"
[[ "$(field disk-before Internal)" == false ]] || fail 'Refusing internal storage.'
[[ "$(field disk-before WholeDisk)" == true ]] || fail 'Expected a whole disk.'
[[ "$(field disk-before BusProtocol)" == USB ]] || fail 'Expected the USB card reader.'
[[ "$(field disk-before VirtualOrPhysical)" == Physical ]] || fail 'Refusing a disk image.'
[[ "$(field disk-before WritableMedia)" == true ]] || fail 'Card is not writable.'
[[ "$(field disk-before TotalSize)" == 127865454592 ]] || fail 'Camera card size differs.'
[[ "$(field volume-before ParentWholeDisk)" == "${DISK#/dev/}" ]] || fail 'Partition/disk mismatch.'
[[ "$(field volume-before VolumeUUID)" == 55FEAB7C-DA7E-3969-B25D-2798B7967A07 ]] || fail 'Wrong card: recovery volume UUID differs.'
[[ "$(field volume-before VolumeName)" == PIRECOVERY ]] || fail 'Wrong volume label.'
[[ "$(field volume-before FilesystemType)" == msdos ]] || fail 'Expected the recovery FAT filesystem.'
[[ "$(field volume-before IOKitSize)" == 512000000 ]] || fail 'Unexpected recovery partition size.'
if /usr/sbin/diskutil info "${DISK}s2" >/dev/null 2>&1; then
  fail 'Unexpected second partition; refusing to erase.'
fi

print -- "1/3 Restoring only the identified camera card to full capacity: $DISK."
/usr/sbin/diskutil eraseDisk ExFAT sd-reader MBRFormat "$DISK"
/bin/sync
/usr/sbin/diskutil unmountDisk "$DISK"
/usr/sbin/diskutil mount readOnly "${DISK}s1"
/usr/sbin/diskutil info -plist "$DISK" > "$OUT/disk-after.plist"
/usr/sbin/diskutil info -plist "${DISK}s1" > "$OUT/volume-after.plist"
[[ "$(field disk-after TotalSize)" == 127865454592 ]] || fail 'Device size changed.'
[[ "$(field disk-after Content)" == FDisk_partition_scheme ]] || fail 'Expected MBR partition table.'
[[ "$(field volume-after ParentWholeDisk)" == "${DISK#/dev/}" ]] || fail 'Restored partition/disk mismatch.'
[[ "$(field volume-after FilesystemType)" == exfat ]] || fail 'Expected ExFAT.'
[[ "$(field volume-after VolumeName)" == sd-reader ]] || fail 'Unexpected restored label.'
[[ "$(field volume-after WritableVolume)" == false ]] || fail 'Verification mount is not read-only.'
(( $(field volume-after TotalSize) > 127000000000 )) || fail 'Full capacity was not restored.'
if /usr/sbin/diskutil info "${DISK}s2" >/dev/null 2>&1; then
  fail 'Unexpected extra partition after restoration.'
fi

print -- '2/3 Checking the restored ExFAT filesystem.'
/usr/sbin/diskutil verifyVolume "${DISK}s1" > "$OUT/filesystem-check.txt" 2>&1 || fail "Filesystem check failed; see $OUT/filesystem-check.txt"
print -- "Verified volume capacity: $(field volume-after TotalSize) bytes."
print -- "Restored volume UUID: $(field volume-after VolumeUUID)."
print -- '3/3 Safely ejecting the camera card.'
/usr/sbin/diskutil eject "$DISK"
print -- "Camera card restored and ejected. Report: $OUT"
