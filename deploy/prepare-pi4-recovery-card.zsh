#!/bin/zsh
# One-time preparation for the specifically identified, owner-approved camera card.
emulate -LR zsh
set -eu
set -o pipefail
export PATH=/usr/bin:/bin:/usr/sbin:/sbin
umask 077

fail() { print -u2 -- "$*"; exit 1; }
(( $# == 1 || $# == 3 )) || fail 'Usage: /bin/zsh prepare-pi4-recovery-card.zsh /dev/diskN [--resume RECOVERY_VOLUME_UUID]'
[[ "$1" == /dev/disk<-> ]] || fail 'Expected /dev/diskN.'
if (( $# == 3 )); then
  [[ "$2" == --resume && -n "$3" ]] || fail 'Expected --resume RECOVERY_VOLUME_UUID.'
fi
DISK="$1"
SOURCE='/Volumes/NO NAME'
OUT=$(/usr/bin/mktemp -d /private/tmp/frontier-pi4-recovery-check.XXXXXX)
field() { /usr/libexec/PlistBuddy -c "Print :$2" "$OUT/$1.plist"; }
digest() { /usr/bin/shasum -a 256 "$1" | /usr/bin/awk '{print $1}'; }

typeset -A HASHES
HASHES=(
  README.txt b94257bb3ce01203fc9b48376811ae06177789c7af7cfa9c09b222b3cea99058
  pieeprom.bin 8923d759f3b9583eec8b2316dc2652ba3be19d630ce2b23459cbc785e7bb4157
  pieeprom.sig 36f7f09d8d02eb527257cb469ab0be3c462d8eeb4e12eca66734de3afa7a37d7
  recovery.bin 9ec8816886f3938d962a837347d65ccc1d03e811a84bf1ad4b608906b288d995
  vl805.bin 548581c70a71d4da17a8d0eb314db518a1d3592249e893e42c020c0a8f53a75f
  vl805.sig e5c51ed5c78abd8a054d4afea7b2104fcfb687412ac1e649c128709dda7e428a
)
for FILE in ${(k)HASHES}; do
  [[ -f "$SOURCE/$FILE" && "$(digest "$SOURCE/$FILE")" == "${HASHES[$FILE]}" ]] || fail "Unverified recovery source: $FILE"
done

/usr/sbin/diskutil info -plist "$DISK" > "$OUT/disk.plist"
/usr/sbin/diskutil info -plist "${DISK}s1" > "$OUT/before.plist"
[[ "$(field disk Internal)" == false ]] || fail 'Refusing internal storage.'
[[ "$(field disk WholeDisk)" == true ]] || fail 'Expected a whole disk.'
[[ "$(field disk BusProtocol)" == USB ]] || fail 'Expected the USB card reader.'
[[ "$(field disk VirtualOrPhysical)" == Physical ]] || fail 'Refusing a disk image.'
[[ "$(field disk TotalSize)" == 127865454592 ]] || fail 'Camera card size differs.'
[[ "$(field before ParentWholeDisk)" == "${DISK#/dev/}" ]] || fail 'Partition/disk mismatch.'
if /usr/sbin/diskutil info "${DISK}s2" >/dev/null 2>&1; then
  fail 'Unexpected second partition; refusing to erase.'
fi

if (( $# == 3 )); then
  [[ "$(field before VolumeUUID)" == "$3" ]] || fail 'Resume volume UUID does not match.'
  [[ "$(field before VolumeName)" == PIRECOVERY ]] || fail 'Not the recovery volume.'
  [[ "$(field before FilesystemType)" == msdos ]] || fail 'Expected the formatted recovery filesystem.'
  print -- '1/4 Resuming the identified recovery volume; no further formatting.'
else
  [[ "$(field before VolumeUUID)" == 6AC700FC-9955-3759-B227-EDB1AD3DCE5C ]] || fail 'Wrong card: original camera-volume UUID does not match.'
  [[ "$(field before VolumeName)" == sd-reader ]] || fail 'Wrong volume label.'
  [[ "$(field before FilesystemType)" == exfat ]] || fail 'Expected the original camera filesystem.'
  print -- "1/4 Erasing only the identified camera card: $DISK (127.9 GB, sd-reader)."
  /usr/sbin/diskutil partitionDisk "$DISK" 2 MBRFormat FAT32 PIRECOVERY 512M 'Free Space' unused 0
fi
/usr/sbin/diskutil info -plist "${DISK}s1" > "$OUT/after.plist"
[[ "$(field after ParentWholeDisk)" == "${DISK#/dev/}" ]] || fail 'New partition/disk mismatch.'
[[ "$(field after VolumeName)" == PIRECOVERY ]] || fail 'Unexpected recovery volume.'
[[ "$(field after Content)" == (Windows_FAT_32|DOS_FAT_32) ]] || fail 'Recovery partition is not FAT32.'
(( $(field after TotalSize) > 100000000 && $(field after TotalSize) < 1000000000 )) || fail 'Unexpected recovery partition size.'
DEST="$(field after MountPoint)"
[[ -n "$DEST" && -d "$DEST" ]] || fail 'Recovery volume was not mounted.'

print -- '2/4 Copying official Pi 4 SD-boot recovery files.'
for FILE in ${(k)HASHES}; do
  /bin/cp -X "$SOURCE/$FILE" "$DEST/$FILE"
done
/bin/sync

print -- '3/4 Remounting read-only and verifying every recovery file.'
/usr/sbin/diskutil unmountDisk "$DISK"
/usr/sbin/diskutil mount readOnly "${DISK}s1"
/usr/sbin/diskutil info -plist "${DISK}s1" > "$OUT/verify.plist"
[[ "$(field verify VolumeUUID)" == "$(field after VolumeUUID)" ]] || fail 'Recovery-volume identity changed.'
[[ "$(field verify WritableVolume)" == false ]] || fail 'Verification mount is not read-only.'
DEST="$(field verify MountPoint)"
for FILE in ${(k)HASHES}; do
  ACTUAL="$(digest "$DEST/$FILE")"
  [[ "$ACTUAL" == "${HASHES[$FILE]}" ]] || fail "Read-back verification failed: $FILE. Do not boot this card."
  print -- "$ACTUAL  $FILE" >> "$OUT/verified-sha256.txt"
done
/usr/sbin/diskutil verifyVolume "${DISK}s1" > "$OUT/filesystem-check.txt" 2>&1 || fail "Filesystem verification failed; see $OUT/filesystem-check.txt"

print -- '4/4 Safely ejecting the verified recovery card.'
/usr/sbin/diskutil eject "$DISK"
print -- "Pi 4 recovery card prepared, verified and ejected. Report: $OUT"
print -- 'The card is temporarily 512 MB. Repartition it to full capacity before normal camera use.'
