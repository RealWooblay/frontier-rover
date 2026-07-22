# ADR 0001: Raspberry Pi operating system

## Context

The existing SD card ran Raspbian Bullseye with a 64-bit kernel and 32-bit
`armhf` user space. It also contained obsolete TI projector configuration.
The rover needs a supported ARM64 base that can later use a current ROS 2 LTS
without building the platform from source.

## Options Considered

- Keep the Bullseye projector image.
- Install Raspberry Pi OS 64-bit.
- Install Ubuntu Server 24.04 LTS for ROS 2 Jazzy.
- Install Ubuntu Server 26.04 LTS for ROS 2 Lyrical.

## Decision

Use Ubuntu Server 26.04 LTS ARM64 on the Raspberry Pi 4.

Do not install ROS 2 during M0. First understand and test the raw Linux,
networking, GPIO, bus, and safety boundaries.

## Why

- Canonical supports Ubuntu 26.04 on Raspberry Pi 4.
- ROS 2 Lyrical supports Ubuntu 26.04 ARM64 and is supported until May 2031.
- Kernel and user space use the same 64-bit architecture.
- Ubuntu provides signed package updates and standard server tooling.

References:

- https://ubuntu.com/hardware/docs/boards/how-to/ubuntu_supported/raspberry-pi/
- https://docs.ros.org/en/lyrical/Releases/Release-Lyrical-Luth.html

## Consequences

- Raspberry Pi OS-specific utilities may behave differently. For example,
  `vcgencmd` is installed but cannot currently access `/dev/vcio`.
- Hardware interfaces will be tested through standard Linux interfaces before
  any robotics framework is introduced.
- The new LTS release may expose packaging defects that require evidence-based
  diagnosis.

## Evidence That Would Cause Reconsideration

- Required Raspberry Pi hardware interfaces are unsupported or unreliable.
- A required motor, sensor, or camera driver only supports another maintained
  platform.
- ROS 2 Lyrical ARM64 packages prove unsuitable for the planned Pi-Jetson
  architecture.
