# Pi Card Read-Only Inspection

## Objective and Mechanism

Determine whether the Pi's loss of access is preceded by a boot/storage problem,
before changing its network configuration. Boot firmware loads the Linux kernel
and initial RAM filesystem from FAT. Linux then mounts its ext4 root filesystem
and starts networking and the controller. Failure earlier in this chain can
look like a Wi-Fi failure from the Mac.

## Evidence Collected

- The inserted Pi card is `/dev/disk5`, external USB, 127865454592 bytes.
- Its FAT boot-volume UUID is `BDFDE5B3-A7DB-3688-9420-F13710AC609C`.
- `/dev/disk4` is the Jetson's 16.8 MB `L4T-README` USB device, not the Pi card.
- Boot configuration selects `current/vmlinuz`, `current/initrd.img`, and
  `root=LABEL=writable`. Those files, the Pi 4 device tree and the configured
  camera/USB/graphics overlays are present.
- `gzip -t current/vmlinuz` and `zstd -t current/initrd.img` both exited zero.
  Compression integrity is not a complete boot or hardware acceptance test.
- The saved network report records Wi-Fi at `192.168.0.87`, SSH and controller
  active, and `throttled=0x0`. It is historical, not proof of this restart.
- Direct read-only `debugfs` access was denied by macOS; `sudo -n` reports
  that an administrator password is required. The Linux partition has not yet
  been inspected at that point. The authenticated results are below.

## Changes and Boundaries

No SD configuration changes, repairs, reflashes or motor commands were made.
The old offline installers hardcode `/dev/disk4` and must not be run here.

`deploy/inspect-pi-card-readonly.zsh` is a new diagnostic, not a repair script.
It takes an explicit device argument and checks size, external-disk status,
boot UUID and partition layout. It unmounts the card, uses `fsck_msdos -n` and
`e2fsck -f -n`, and uses debugfs without its write option to copy selected
configuration and current logs to a private Mac temporary directory. It does
not expose network credentials in its terminal summary. File dumps are limited
to 128 MiB each because the Mac currently has little free space.

Syntax checking and unprivileged/missing-argument rejection were tested.
The privileged inspection was subsequently run by the owner; see below.
An unclean journal can affect a no-repair ext4 check; its output must be
interpreted before diagnosing card failure or attempting a repair.

## Lesson and Next Measurement

Device numbers reflect connection order, not hardware identity. Verify the
actual disk every time. A dark activity LED is not a Wi-Fi diagnosis. The next
measurement is the read-only filesystem report plus the last available Linux
boot journal. Neither a missing log nor a failed network probe alone proves
that the power bank, card or Wi-Fi hardware is broken.

Teach-back: why could failure to mount Linux's root filesystem make a healthy
Wi-Fi radio appear unreachable?

## Authenticated Inspection Results

The owner ran the diagnostic and produced
`/private/tmp/frontier-card-inspect.jhRYck`. Both filesystem tools returned zero.
Reading their detailed output qualifies that result:

- FAT has no reported structural error.
- ext4 skipped journal recovery because the check was read-only. Its superblock
  has `needs_recovery` and `orphan_present`; the check reports a 233-block and
  six-inode free-count discrepancy. No repair was performed. These differences
  may reflect pending transactions after an unclean stop; they do not establish
  defective flash. Earlier wording that both checks simply "passed" was too
  strong. The script now explicitly warns about these details in its summary.
- Root label `writable` matches the boot command line. Root hostname is
  `frontier-pi`; UUID is `009c3fa3-7cad-413a-bac4-b4d45c2fbaf5`.
- There is one saved Netplan configuration, targeting the existing 5 GHz SSID.
  No credentials were changed or stored in the repository.

The text logs contain a successful boot taking 21.935 seconds, Wi-Fi key
negotiation, DHCP address `192.168.0.87`, and controller startup. Boot initially
uses a July date until chrony corrects it to September 8 at 18:01:43 AEST. That
explains the old-looking boot-report timestamp; it is not proof of an old OS.

The latest system journal was decoded with the existing Dissect JournalFile
parser in a temporary Mac tools directory. Jetson's older journalctl could not
read its newer compact format. No Jetson software was upgraded. The current
journal contains 201 entries, one boot ID
`106fe250268d40deb986593880179279`, ending at September 8 18:40:10 AEST.
SSH over wlan0 worked at 18:39:25; the text log records HTTP controller/camera
responses through 18:39:46. No later boot or full-system shutdown is present in
the collected current logs. User-session shutdown records are NOT Pi poweroffs.

Two wait-online errors occurred during APT background tasks at 18:02 and 18:03.
They precede successful SSH/HTTP access, so they do not demonstrate why access
was later lost. No undervoltage, kernel panic, storage I/O error or Wi-Fi
disassociation explaining the final loss was found in the collected logs.
Absent records do not exclude power loss, a hang or failure before log saving.

## Decision

Do not reflash, rewrite networking or use debugfs to modify the dirty root
filesystem. Pending filesystem journal replay normally happens during Linux
mounting. A read-only check has not proved all hardware healthy or found a
software root cause. Safely eject the unchanged card and use the existing Pi
wall supply for the next observed boot, with no autonomous motion. This removes
the Belkin power path as a variable; it does not declare the Belkin faulty.

Parser reference: [Dissect JournalFile API](https://docs.dissect.tools/en/latest/api/dissect/target/plugins/os/unix/log/journal/index.html).

## Wall-Power Follow-Up

At approximately 21:38 AEST the owner reported wall power and a solid red LED.
The Mac could ping the home router (2.09 ms), but the Pi's previous IPv4 address
did not answer ping or HTTP, and `frontier-pi.local` did not resolve. No Pi
Wi-Fi MAC was present among resolved neighbours during discovery. This does
not prove the Pi is damaged or that Linux never booted. Whether the green ACT
LED showed any startup activity is still awaiting the owner's observation.
No Pi configuration or motor commands were changed during this follow-up.

The owner subsequently confirmed no green activity on wall power. The next
physical test is a no-SD-card power-on: disconnect Pi power, confirm its LEDs
are out, remove the card, then power from the Pi wall supply and observe ACT
for 20 seconds. Do not insert/remove the card while powered. This changes no
software and leaves GPIO wiring undisturbed. Pi 4 has an onboard EEPROM
bootloader, so it can report missing boot media without loading Linux. LED
activity would establish some onboard startup execution, not a healthy OS or
proof of card failure. No activity would leave the power/board/attached-circuit
and bootloader paths unresolved; it is not authorization for an EEPROM reflash.

References: [Pi boot diagnostics](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html#boot-diagnostics)
and the [Pi boot troubleshooting sticky](https://forums.raspberrypi.com/viewtopic.php?t=58151).

## No-Card Result and Electrical Isolation

The owner reports no green activity even with the SD card removed and wall
power connected. Changing Linux/network files cannot address this no-media
symptom. This does not distinguish boot EEPROM problems, onboard power faults,
external loading/shorts, or an LED fault by itself.

The next requested test is a bare Pi: disconnect wall and motor-battery power,
record the Pi header connections, unplug only the Pi-end GPIO connectors and
camera ribbon, and leave SD/USB/HDMI/Ethernet disconnected. Place the Pi on dry
nonconductive material and apply only its proper wall supply for 20 seconds.
No desoldering is needed; the pin map is in
`hardware/wiring/m2-four-motor-wiring.md`. Do not reconnect anything powered.
If ACT returns, connected hardware or its power interaction becomes the focus;
if not, measure the isolated board supplies before considering EEPROM recovery.
No board failure or short has yet been measured, and no EEPROM write was made.

## Wiring Retained: Ambiguous Supply Reading

The owner declined unplugging the GPIO/camera harness and has approximately
one hour available. Bare-board isolation was not performed; do not describe
external loading as ruled out or repeatedly request dismantling.

A VCC-to-GND voltage measurement at an accessible TB6612 was requested as a
less disruptive check. The owner reported 7.5 V but could not identify whether
the red probe touched VM or VCC, and reported a momentary green Pi LED. This is
not a verified 3.3 V rail measurement or a successful boot. Approximately 7.5 V
is plausible at the motor supply VM; it would be an overvoltage at the Pi-fed
VCC connection. No causal link between probing and LED activity is established.

The instruction is to remove Pi and motor-battery power, retain the signal
wiring, and identify the printed VCC/VM pads before another measurement.
Recorded wiring uses a thin red Pi wire for VCC and the thick red barrel lead
for VM, but printed labels must confirm the pad; colour alone is insufficient.
Power removal and pad identification are not yet confirmed. No hardware command,
firmware recovery, filesystem repair or network change was performed.

The owner subsequently reported about 0.05 V while checking "the 2", with
difficult probe access and another green LED observation. Exact pads, reliable
probe contact and meter setup remain unconfirmed, so this is not a confirmed
logic-supply failure. Further cramped live probing was discouraged. Fresh Mac
checks found SSH and controller HTTP at 192.168.0.87 unavailable; resolving
frontier-pi.local timed out. No software was changed on the Pi. SD reinsertion
has not been confirmed since the no-card test and must be clarified before
interpreting LED activity as an attempt to start the installed OS.

The owner then explicitly confirmed multiple attempts with the SD card both in
and out. Do not keep asking whether the card was reinserted or treat that as an
untried explanation. Exact power sequencing during those attempts is unknown;
do not assume the card was hot-plugged. The instruction is to stop powered
probing and connection changes. A subsequent HTTP check at 192.168.0.87 still
failed. With uncertain voltage readings and no isolated-board test, startup
firmware, board supplies and attached-circuit faults remain unresolved. No
further network rewrite or destructive card operation is justified by this
evidence alone.

## Owner Agrees to Peripheral Isolation

The owner now permits unplugging the wiring as a final useful diagnostic, not
as a guaranteed repair. The requested procedure is to remove Pi and motor-pack
power, photograph the header wiring, then disconnect only the Pi ends of the
GPIO harness and camera ribbon. Preserve solder joints and the driver-end
connections. Test with the existing SD card installed and the proper Pi wall
supply, with no other attached cables or conductive contact underneath.

Observe startup for two minutes and then check network reachability. Successful
boot would implicate the removed hardware/connections or their power interaction
without identifying a specific wire. Failure would not by itself prove a dead
Pi or bad SD; supply and firmware diagnosis would remain open. Do not reconnect
peripherals while powered. No isolation result has yet been reported.

The owner reports "unplugged wires, still nothing" after this procedure. Record
that observation without assuming a verified internal-rail measurement or
independently confirming every connector. Fresh HTTP/SSH checks at 192.168.0.87
failed and frontier-pi.local resolution timed out. Removing the wiring has not
restored access or reported ACT activity; it does not prove SD-reader failure
or exclude previous damage. Official Pi 4 EEPROM bootloader recovery remains a
possible firmware-only diagnostic, not a guaranteed fix. A separately identified
spare card and authorization to erase that specific card are required before
preparing recovery media; never overwrite the rover or Jetson card for this.

## Continuous Motor-Battery Connection Report

The owner reports that the motor battery and attached electronics were left
connected for the past couple of weeks, including Pi power-bank interruptions.
This is not a measured two-week continuous runtime or evidence that motors were
continuously turning. In the recorded design the motor battery supplies TB6612
VM; the Pi supplies driver VCC and MPU power. Leaving VM energized does not by
itself prove that motor voltage back-fed into Pi logic. A wiring fault or damaged
component could provide an unintended path, but none has been established.

Continuous operation alone should not be treated as a normal cause of Pi death.
The prototype's unattended operation and partial-power states have not been
validated. Disconnect both energy sources for storage/travel; a replacement Pi
must not be connected to the old harness before power paths are verified.

Reference: [Toshiba TB6612FNG datasheet](https://toshiba.semicon-storage.com/info/datasheet_en_20141001.pdf?did=10660),
which distinguishes VM motor supply, VCC logic supply, standby, and electrical
limits. This source does not diagnose the assembled rover.
