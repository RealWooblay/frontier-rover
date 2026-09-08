# Network Permission Repair

Date: 2026-08-28

## Objective

Restore dependable Wi-Fi control and a deterministic USB recovery path without
reflashing the Raspberry Pi.

## Concept Being Learned

Network connectivity is a chain of independently testable layers:

```text
USB or Wi-Fi hardware
  -> Linux interface
  -> interface address
  -> route and neighbour discovery
  -> SSH or HTTP listener
  -> rover controller
```

Seeing a USB Ethernet device or an mDNS advertisement proves only the layer
that produced that observation. It does not prove that an IPv4 address exists
or that unicast packets can reach an application.

## Architecture / Signal Path

```text
Normal:   Mac -> Optus 5 GHz -> Pi wlan0 (DHCP) -> SSH / controller :8765
Recovery: Mac 10.55.0.1 -> USB Ethernet -> Pi usb0 10.55.0.2
```

## Failure Observed

- The Pi initially joined 5 GHz Wi-Fi and advertised `frontier-pi.local`, but
  its intended Networkd configuration was not being used.
- `frontier-usb-recovery.service` was enabled, active, and had exited
  successfully, yet `usb0` had no IPv4 address.
- The one-time `frontier-network-bootstrap.service` had timed out and remained
  enabled and failed.
- After the Pi configuration was repaired, commands launched by ChatGPT on the
  Mac still received `No route to host` over both direct Wi-Fi and USB.
- The Pi could ping the Mac over USB, but a packet capture on the Pi saw zero
  packets when the Mac tried to initiate a connection.

## Diagnosis

### Pi permission fault

The USB service assigned `10.55.0.2` successfully at startup. Thirteen seconds
later, `systemd-networkd` reconfigured `usb0` with
`zzzz-dracut-default.network` and removed that static address.

The decisive journal evidence was:

```text
Failed to open /run/systemd/network/10-netplan-usb0.network: Permission denied
```

The setup script had set `umask 077` to protect a Netplan source file containing
the Wi-Fi password, then left that mask active. Netplan consequently generated
all `10-netplan-*.network` files with mode `0600`. Those files belonged to
`root`, while the running Networkd process used the `systemd-network` account.
Networkd could not read the intended configuration and selected Dracut's
generic DHCP fallback instead.

### Mac permission fault

macOS **Privacy & Security > Local Network** showed **ChatGPT** switched off.
macOS rejected direct local-link connections before sending a packet, which is
why changing Pi services, addresses, batteries, and physical placement could
not fix the remaining `No route to host` error. Turning that permission on
immediately restored direct USB and Wi-Fi traffic.

Battery proximity and router isolation were earlier hypotheses, not causes.
Router isolation was disabled, and both direct paths worked after the two
permission repairs.

## Changes Made

- Scoped `umask 077` only around the secret Netplan source file.
- Explicitly restored `umask 022` before `netplan generate`.
- Regenerated Networkd files with group-readable permissions. A clean boot
  produced mode `0640`, owned by `root:systemd-network`.
- Reloaded Networkd and reconfigured only `usb0` during recovery.
- Restored and enabled `frontier-usb-recovery.service`.
- Disabled and reset the completed failed bootstrap service.
- Removed the bootstrap's temporary Wi-Fi credential files.
- Preserved Wi-Fi power saving as disabled.
- Enabled macOS Local Network access for ChatGPT.
- Removed the temporary Wi-Fi gateway route and temporary USB neighbour entry.

## Acceptance Result

- A genuine reboot produced a new boot ID and both network paths returned
  automatically.
- With the Mac USB network service disabled, Wi-Fi completed a five-minute
  stability run with 300/300 controller requests and 30/30 SSH checks passing.
- USB ping: 5/5 replies, approximately 0.9 ms average.
- Direct Wi-Fi ping: 5/5 replies after removing the gateway workaround.
- After the Wi-Fi-only run, USB recovery was restored and again returned 5/5
  replies plus successful SSH and controller checks.
- The Mac power cable was then removed before the intended shutdown command
  had executed. The next boot log reported EXT4 orphan cleanup, proving this
  was an abrupt power loss rather than a clean shutdown. The journal recovered
  successfully, with no subsequent SD I/O errors.
- On that new Belkin-only boot, the Pi reacquired `192.168.0.87`, synchronized
  internet time, returned 5/5 Wi-Fi replies, started every required service,
  reported zero failed units, and logged no undervoltage warning.
- USB and Wi-Fi SSH ports: reachable.
- USB and Wi-Fi controller port `8765`: reachable.
- Controller state: `motion=stop`, `motor_active=false`.
- Pi Wi-Fi: 5 GHz, approximately -44 dBm, power saving off.
- Pi gateway and DNS resolution: working.
- Required services: active and enabled.
- Failed systemd units: zero.
- Pi-side test suite: 13 tests passed.

## Transfer to Other Domains

This is a general robotics reliability lesson: a service can report success and
still have its state overwritten by a later owner. Diagnose the final observed
state and the timeline of changes, not merely each command's exit code. Also
test both endpoints: an operating-system privacy policy can stop traffic before
the remote device has any opportunity to respond. Recovery interfaces should
remain independent of the primary control network.
