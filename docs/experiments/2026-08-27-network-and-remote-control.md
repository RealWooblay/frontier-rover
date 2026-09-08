# Network and Remote-Control Bring-Up

> Correction recorded 2026-08-28: this experiment proved the Belkin-powered
> boot and exposed genuine Pi networking faults, but its network diagnosis was
> incomplete. Later packet-level testing found both a Netplan-generated file
> permission fault on the Pi and disabled macOS Local Network access for
> ChatGPT. See `2026-08-28-network-permission-repair.md` for the final diagnosis
> and post-reboot acceptance tests.

Date: 2026-08-27

## Objective

Create a reliable headless recovery path and a browser remote that stops the
rover if commands stop arriving.

## Concept Being Learned

Network failures must be separated by layer. USB enumeration, interface
addressing, IP reachability, SSH, and the rover application are different
checks. A green activity LED proves storage activity; it does not prove that
Wi-Fi or SSH works.

## Architecture

```text
Old control:     Mac/phone -> Optus router -> Pi 192.168.0.87 -> HTTP :8765
New control:     Mac/phone -> Frontier-Rover 5 GHz AP -> Pi 10.42.0.1 -> HTTP :8765
Recovery:        Mac 10.55.0.1 -> USB Ethernet -> Pi 10.55.0.2 -> SSH/HTTP
Motor safety:    browser heartbeat -> 0.35 s watchdog -> TB6612 outputs
```

## Failure Observed

- The Pi associated with `Optus_8DC016_5GHz`, completed WPA authentication,
  and received `192.168.0.87`, but the Mac could not reach it through the
  router.
- The Mac detected the Pi as an RNDIS/Ethernet gadget and created `en10`, but
  ARP for `10.55.0.2` remained incomplete.
- Repeated hard power removal left errors in the Linux ext4 filesystem.
- After a later successful untethered test, the Mac powered off while the Pi
  remained powered. When the Mac restarted it could reach the Optus router,
  but ARP, ping, SSH, and the controller could no longer reach the Pi.

## Diagnosis

Boot logs proved that the Pi radio and 5 GHz credentials worked. The same logs
contained no undervoltage, kernel panic, or SD I/O errors during that boot.
There is therefore no evidence that physical proximity to the Belkin battery
caused the network failure.

USB enumeration proved the cable, Pi USB controller, `dwc2`, and `g_ether`
loaded. It did not prove that Linux had brought `usb0` up or assigned its
address. The missing deterministic startup action was the immediate USB fault.

The filesystem errors were a separate result of removing power without a clean
shutdown. `e2fsck` repaired them and a second check completed cleanly.

The later recurrence proved that the home-router path is not a dependable
control link. It did not prove that the laptop turned off or damaged the Pi:
the Pi has its own battery. It proved only that the Pi was no longer reachable
through the access point. Without Pi-side logs, the remaining causes are a
stalled Pi station association or router client forwarding. A rover should not
depend on either one for local control.

## Changes Made

- Pi 4 USB peripheral mode is enabled with `dwc2` and `g_ether`.
- Stable USB MAC addresses identify the Mac and Pi ends.
- The Mac uses `10.55.0.1/24`; the Pi uses `10.55.0.2/24`.
- `frontier-usb-recovery.service` waits for `usb0`, brings it up, and explicitly
  assigns `10.55.0.2/24` on every boot.
- The 5 GHz network configuration was preserved.
- The rover repository and the Ubuntu `gpiozero`/`lgpio` packages were restored
  after the clean OS flash.
- `frontier-rover-control.service` was enabled to start the stopped controller
  automatically.
- A replacement network design was prepared: the Pi hosts a WPA2-protected
  5 GHz `Frontier-Rover` access point on channel 36 with fixed address
  `10.42.0.1`. `hostapd` owns the radio, while `systemd-networkd` assigns the
  fixed address and leases client addresses. When Ethernet is attached, the
  Pi routes and masquerades client internet traffic through Ethernet. USB
  recovery remains available for maintenance.

## Acceptance Result

- Direct USB ping: 3/3 replies, 0% packet loss, about 1.4 ms average.
- SSH on `10.55.0.2:22`: reachable with key authentication.
- 5 GHz ping to `192.168.0.87`: 3/3 replies, 0% packet loss.
- SSH and the controller port are reachable through `192.168.0.87`.
- Pi interfaces: `usb0` at `10.55.0.2`; `wlan0` at `192.168.0.87`.
- USB recovery service: enabled and active.
- Rover controller service: enabled and active.
- Controller status over HTTP: `motion=stop`, `motor_active=false`.
- All 13 Pi-side unit tests pass.
- No failed systemd services were reported.
- After a clean shutdown, the Pi booted from the Belkin power bank with no Mac
  cable, reacquired `192.168.0.87`, and exposed SSH and the controller over
  5 GHz.
- That Belkin boot reported no undervoltage, SD I/O, kernel panic, or failed
  service evidence.

## Why Two Network Paths

The rover-hosted Wi-Fi is the normal untethered control path. It removes the
home router, its DHCP lease, and its client-forwarding behaviour from the
control loop. USB Ethernet is the maintenance path: it permits SSH repair
without a monitor or working radio. Ethernet remains a temporary package and
recovery path. Neither cable is needed during normal rover use.

The Pi has one Wi-Fi radio. In this simple, dependable design it operates as an
access point rather than simultaneously joining the home network. A laptop or
Jetson connected to `Frontier-Rover` always has local rover access. It also has
internet through the Pi while Ethernet is attached; normal untethered use has
no external internet unless another uplink is added later.

## Remaining Hardware Acceptance

With the rover in a clear test area and the motor battery connected:

1. Hold each browser direction and confirm the expected motion.
2. Release the control and confirm an immediate stop.
3. Interrupt the command stream and confirm a stop within 0.35 seconds.

## First Continuous Floor-Control Observation

The initial browser calibration used 8% left PWM and 40% right PWM. In forward,
the two front wheels moved, back-left moved only slightly, and back-right did
not move. In reverse, all four wheels moved, but overall motion was weak.

A back-right-only floor test at 40% moved weakly in reverse and did not move in
forward. That test is mechanically confounded because one powered wheel must
drag three unpowered geared wheels. It does not by itself prove a failed motor
or H-bridge direction.

The next software calibration was 30% left and 70% right. This raised both sides
above the likely starting-torque dead zone while preserving extra command for
the mechanically weaker right side. All 13 tests pass with that mapping. The
new values remain provisional until forward, reverse, and steering are observed
on the floor.

The back-right forward failure was then traced to wiring that was only slightly
touching rather than making a reliable connection. After fixing that contact,
all four wheels operated. The corrected observation is that the rover's path
curved left in both forward and reverse at 70% right PWM, and still curved left
at 75%. The earlier right-drift report was mistaken, so midpoint interpolation
was not justified. The next open-loop calibration reduces the right command to
60% while holding the left command at 30%.
