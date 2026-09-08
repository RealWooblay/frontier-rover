# Operator Console and Safe Shutdown

Date: 2026-08-28

## Objective

Replace the basic direction pad with a useful rover console while preserving
the Pi's local motor-safety boundary.

## Implementation

- Added a speed multiplier around the confirmed 40% left / 60% right trim.
- Added real Pi telemetry for temperature, uptime, memory, Wi-Fi, camera
  detection, and Jetson Ethernet carrier.
- Added explicit motor-output and watchdog state to the UI.
- Added a camera-first viewport that reports no camera until hardware is
  actually detected.
- Added emergency stop and a confirmed clean-shutdown action.
- Kept the controller unprivileged. Shutdown crosses a single-purpose systemd
  path unit rather than granting the web process `sudo`.

## Verification

- All 22 Pi-side tests passed.
- Invalid throttle returned HTTP 400.
- An unconfirmed shutdown returned HTTP 400 and did not create the marker.
- Controller and poweroff path services were active.
- Controller ran as `rover` with `NoNewPrivileges=yes`.
- Runtime request directory was owned by `rover:rover` with mode `0750`.
- Live telemetry reported Pi temperature, Wi-Fi signal and address, memory,
  uptime, camera not detected, and Jetson offline.
- Final motor state was STOP with left and right output at zero.

## Result

The browser is now an operator interface, while the Pi remains the actual
motor controller and safety authority. Camera and Jetson panels expose honest
integration states without pretending those subsystems are already installed.

## Follow-up: Editable Calibration

The next console revision was prepared while the Pi was powered off. It keeps
the complete controller within one viewport and adds left/right straight PWM
fields. Applying a change stops motion, validates both values, and persists the
calibration in systemd's `/var/lib/frontier-rover` state directory. API,
persistence, invalid-input, and motor-stop tests pass locally. This follow-up
still requires deployment and live Pi verification after the Pi is powered.
