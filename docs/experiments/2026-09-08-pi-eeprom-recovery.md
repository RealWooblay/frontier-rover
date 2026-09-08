# Pi 4 Bootloader Recovery Card

## Objective and Authorization

Distinguish a recoverable onboard-startup firmware fault from the unresolved
Pi hardware/startup failure. The owner explicitly authorized erasing a spare
camera SD card, confirmed wanted photographs are on their phone, and wants the
card restored for camera use afterward. This is not permission to erase the
rover or Jetson cards.

## Card Identity

- Preparation device: `/dev/disk5`, external physical USB media, 127865454592 bytes.
- Original single partition: ExFAT, `sd-reader`, camera directories present.
- Original volume UUID: `6AC700FC-9955-3759-B227-EDB1AD3DCE5C`.
- Jetson USB virtual media remained `/dev/disk4`, 16.8 MB, `L4T-README`; untouched.
- Prepared card: MBR, one 512 MB FAT32 partition, `PIRECOVERY`, remainder free.
- Prepared volume UUID: `55FEAB7C-DA7E-3969-B25D-2798B7967A07`.

Disk numbers are not permanent identities. The spare camera and rover cards
have the same total capacity, so capacity alone is not sufficient identification.

## Source and Mechanism

The official Raspberry Pi Imager catalog's Pi 4 family SD Card Boot entry points
to the non-prerelease `v2026.05.17-2711-0138c0` recovery archive:

https://github.com/raspberrypi/rpi-eeprom/releases/download/v2026.05.17-2711-0138c0/rpi-boot-eeprom-recovery-2026-05-17-2711-vl805-000138c0-sd.zip

Archive SHA-256, matching GitHub's published asset digest:
`30546013001649d518d41ff8ce442e41eee2a81e2b215b9f0548e95c8bc78495`.

The ZIP contains a 270532608-byte disk image. It was extracted and mounted
read-only. Its six files were copied onto the spare card's small FAT32 partition,
following the official README's alternative file-copy recovery method. This
updates onboard EEPROM startup firmware with SD-first boot priority; it does
not install Ubuntu, start Wi-Fi, or run the rover controller.

## Preparation and Verification

`deploy/prepare-pi4-recovery-card.zsh` checks the exact original volume UUID,
size, label, filesystem, external/physical USB attributes and absence of a second
partition before formatting. It refuses the old rover layout and Jetson media.
macOS permitted preparation without a sudo prompt.

The first attempt formatted the card, then stopped because the new partition
was labelled `DOS_FAT_32`, while the read-only source image used
`Windows_FAT_32`. The validator was corrected to accept both FAT32 content names.
Preparation resumed using the exact newly recorded recovery-volume UUID; no
second format occurred. Script syntax validation passed.

All six files were read back after unmounting and remounting read-only, and their
SHA-256 values matched the official source. `diskutil verifyVolume` passed. The
card was safely ejected, and the source disk image detached.
Report: `/private/tmp/frontier-pi4-recovery-check.4LT5DB`.

Key verified firmware hashes:

- `recovery.bin`: `9ec8816886f3938d962a837347d65ccc1d03e811a84bf1ad4b608906b288d995`.
- `pieeprom.bin`: `8923d759f3b9583eec8b2316dc2652ba3be19d630ce2b23459cbc785e7bb4157`.

## Physical Test: No Success Indication

Keep peripherals and motor battery disconnected. With Pi power removed, insert
the prepared camera card, then power only from the proper Pi wall supply. Leave
power on for at least 60 seconds while observing the green ACT LED. The official
success signal is continuous rapid green flashing; other repeating patterns
must be recorded rather than assumed to indicate success. Wi-Fi is not expected.
Successful recovery is followed by power-off, swapping back to the original
rover card and testing a bare-Pi Linux boot before reconnecting the harness.

The owner subsequently reported "still no green light" after the instructed
recovery test. Recovery success has not been established. Together with the
earlier peripheral-disconnected test, this increases concern about the Pi
hardware or power delivery. It does not identify a failed component or establish
that the Belkin caused damage. Input/internal supply rails have not been
reliably measured; an ACT LED fault alone also cannot be excluded from this
observation. Further Linux or Wi-Fi changes are not justified by this result.

The owner returned the spare camera card to the Mac, and full-capacity
restoration was completed as recorded below.

## Return to Camera Use

After the diagnostic, re-identify this exact spare card and repartition the
whole card to full capacity, then format it in the camera. Do not merely format
the current 512 MB partition or give commands based on the old disk number.
Do not leave the recovery image in a normally operating Pi.

Completed using `deploy/restore-camera-card.zsh`, which refused any card without
the recorded recovery UUID, physical USB identity, original total size and
512 MB recovery partition. The card was still `/dev/disk5`, but that was checked
afresh rather than assumed. `diskutil eraseDisk ExFAT sd-reader MBRFormat`
replaced the recovery layout with one full-size partition. After remounting
read-only, capacity and filesystem checks passed and the card was ejected.

- Physical capacity: 127865454592 bytes (nominal 128 GB).
- ExFAT partition: 127864406016 bytes; usable filesystem: 127859294208 bytes.
- New volume UUID: `1C731B23-992A-373B-AA60-DB90EB924656`.
- Verification report: `/private/tmp/frontier-camera-card-restore.ZZLOqL`.
- Script syntax check and execution both exited zero.
- Original rover card and Jetson storage were not changed.

This verifies formatting and filesystem structure, not a full-surface endurance
test or camera recording. The owner should format the card from the camera's
menu before recording so the camera creates its preferred layout and folders.

Reference: https://github.com/raspberrypi/rpi-eeprom/blob/master/imager/README-2711.txt
