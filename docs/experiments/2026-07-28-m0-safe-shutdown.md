# M0 Safe Shutdown

## Objective

Establish and verify a shutdown procedure that protects the Raspberry Pi
filesystem before power is removed.

## Concept Being Learned

The power LED and storage-activity LED do not report whether Linux has safely
stopped. A safe shutdown asks services to stop, flushes buffered writes, and
unmounts filesystems before external power is removed.

## Hardware Used

- Raspberry Pi 4 Model B Rev 1.5, 4 GB
- 128 GB microSD card
- Raspberry Pi power supply
- Development Mac
- Home Wi-Fi

## Architecture / Signal Path

```text
Mac -> Wi-Fi -> SSH -> systemd shutdown -> filesystem sync -> power removal
```

## Assumptions

- SSH access is working before shutdown begins.
- The Pi remains powered until the operating system finishes shutting down.
- The microSD card and root filesystem are functional.

## Predicted Result

- SSH disconnects when shutdown starts.
- The Pi disappears from the network.
- The previous boot journal records filesystem synchronization.
- The next boot reports the root filesystem as clean.

## Procedure

1. Connected to `rover@frontier-pi.local`.
2. Ran `sudo shutdown -h now`.
3. Waited 20 seconds after SSH disconnected before removing power.
4. Restored power and waited for Wi-Fi to reconnect.
5. Checked system health, the previous boot journal, and the current root
   filesystem check.

## Measurements

| Measurement | Result |
| --- | --- |
| Shutdown command | Accepted; SSH closed normally |
| Network after shutdown | Host absent |
| Previous shutdown journal | `Syncing filesystems and block devices` |
| Root filesystem after restart | Clean |
| System state after restart | Running |
| Wi-Fi after restart | Up, `192.168.0.83/24` |
| Time synchronization | NTP enabled and synchronized |

## Actual Result

The prediction passed. The Pi shut down cleanly and restarted with a clean root
filesystem.

## Failure Observed

- During the first attempt, external power was removed without issuing an
  operating-system shutdown. The next boot recovered the filesystem journal.
- After the verified restart, Wi-Fi and `frontier-pi.local` took approximately
  five minutes to become reachable.
- Early boot journal entries used a stale date until network time synchronized.

## Diagnosis

- A stopped green activity LED only means the SD card is idle; it does not prove
  Linux is shut down.
- Journal recovery showed that the first power removal was unclean.
- The successful repeat produced a clean filesystem check, proving the command
  and wait procedure.
- The Pi has no configured battery-backed real-time clock, so early boot
  timestamps can be stale until NTP becomes available.
- Slow Wi-Fi availability is a startup behavior to measure separately; it does
  not invalidate the clean-shutdown result.

## Changes Made

- Established `sudo shutdown -h now` as the manual shutdown command.
- Established a 20-second wait after SSH disconnects before removing power.

## Acceptance Result

Pass. Safe shutdown is established and tested for M0.

## Transfer to Other Domains

Any computer controlling physical equipment needs a defined transition from
running to unpowered. The same evidence-based procedure applies to field robots,
industrial controllers, remote sensors, and embedded computers.
