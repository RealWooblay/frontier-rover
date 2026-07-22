# M0 Headless Raspberry Pi Bring-Up

## Objective

Create a supported 64-bit Raspberry Pi system that can be administered without
a monitor and can reach the internet.

## Concept Being Learned

Separate boot, local network reachability, SSH authentication, internet routing,
DNS, and operating-system health into independently measurable layers.

## Hardware Used

- Raspberry Pi 4 Model B Rev 1.5, 4 GB
- 128 GB microSD card
- Raspberry Pi power supply
- Development Mac
- Home Wi-Fi

## Architecture / Signal Path

```text
Mac -> Wi-Fi access point -> Raspberry Pi wlan0 -> sshd -> Ubuntu user rover
```

The router assigns the Pi an address with DHCP. Avahi advertises
`frontier-pi.local` using multicast DNS. SSH authenticates the Mac using its
Ed25519 public key.

## Assumptions

- The Pi 4 and microSD card are functional.
- The power supply can sustain the Pi at idle.
- The selected 5 GHz network is compatible with Pi 4.
- The development Mac retains the private half of the installed SSH key.

## Predicted Result

- Ubuntu boots and expands its root filesystem.
- `wlan0` receives a local IPv4 address.
- SSH accepts `rover` using the Mac's key without a login password.
- The Pi reaches an internet IP and resolves DNS names.
- The system reports ARM64 for both kernel and packages.

## Procedure

1. Verified the target removable disk was the 127.9 GB SD card.
2. Downloaded Canonical's Raspberry Pi ARM64 image and its SHA-256 list.
3. Matched the computed and published image checksums.
4. Wrote and read-back verified the image with Raspberry Pi Imager.
5. Configured cloud-init for hostname, user, SSH key, Wi-Fi, timezone, and
   locale.
6. Booted the Pi and discovered its DHCP address.
7. Verified SSH, system identity, storage expansion, network, internet, DNS,
   temperature, cloud-init, and package state.
8. Applied Ubuntu security and firmware updates and rebooted.
9. Installed Avahi and verified `frontier-pi.local`.

## Measurements

| Measurement | Result |
| --- | --- |
| OS | Ubuntu Server 26.04 LTS |
| Architecture | ARM64 / AArch64 |
| Updated kernel | 7.0.0-1014-raspi |
| Root filesystem | 117 GB, approximately 3% used |
| Memory | 3.7 GiB |
| Wi-Fi | Up, DHCP address 192.168.0.83 during test |
| Internet ICMP | 3/3 replies |
| DNS | Successfully resolved Ubuntu and ROS package hosts |
| Temperature | 46-50 degrees C during setup |
| Cloud-init | Done, zero errors |
| System state | Running |
| Pending updates | 0 |
| Kernel voltage warnings | None in the tested boot journal |

## Actual Result

The prediction passed. The Pi is reachable with:

```sh
ssh rover@frontier-pi.local
```

## Failure Observed

- The first network check occurred before the old image had finished booting.
- The initial Ubuntu image did not advertise a `.local` hostname.
- Direct raw-disk writing was blocked by macOS privacy controls.
- The automatic updater temporarily held the package-manager lock.
- `vcgencmd` cannot access `/dev/vcio` on this Ubuntu installation.
- Kernel update scripts printed missing optional `flash-kernel` paths.

## Diagnosis

- Readiness must be measured rather than inferred from the power LED.
- IP connectivity and multicast hostname discovery are separate services.
- Raspberry Pi Imager's signed writer is the correct macOS disk-access path.
- Package locks prevent concurrent database mutation and must not be deleted.
- Pi OS-specific diagnostics cannot be assumed to work unchanged on Ubuntu.
- Boot success on kernel `7.0.0-1014-raspi` showed the update warnings were
  non-fatal for this Pi 4, but they remain useful evidence.

## Changes Made

- Replaced the obsolete Bullseye projector image with Ubuntu Server 26.04.
- Created user `rover` with key-only SSH login.
- Enabled Wi-Fi through cloud-init and installed Avahi for stable local naming.
- Applied all available Ubuntu updates.

## Acceptance Result

Pass for M0 headless operating-system and networking bring-up.

Security debt: the temporary local `sudo` password is intentionally weak and
must be replaced before physical deployment.

## Transfer to Other Domains

The same layered bring-up applies to remote underwater, space, industrial, and
disaster-response systems: prove power, boot, link, addressing, authentication,
routing, naming, and application health separately so one failure cannot be
misdiagnosed as another.
