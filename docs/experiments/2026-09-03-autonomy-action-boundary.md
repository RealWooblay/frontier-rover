# Autonomy Action Boundary

## Objective

Add continuous Jetson-to-Pi actions without moving final motor-safety authority
away from the Raspberry Pi.

## Interface

The new endpoint accepts normalized values:

```json
{"forward": 0.4, "turn": 0.2}
```

The Pi mixes these into left and right commands:

```text
left = forward + turn
right = forward - turn
```

If either magnitude exceeds one, both are scaled by the same amount. The Pi
then applies the saved left/right PWM calibration. Inputs outside `[-1, 1]`,
non-numeric inputs, and non-finite values are rejected.

## Safety Ownership

The autonomy sender must refresh a nonzero action faster than every 350 ms.
The existing Pi watchdog stops both motor-driver boards when the command is
stale. An explicit `{forward: 0, turn: 0}` is represented as `motion=stop` and
immediately lowers motor output.

The Jetson therefore proposes motion; the Pi validates, bounds, times, and
ultimately applies or stops it.

## Evidence

- 33 controller/API tests passed on the Mac and the Raspberry Pi.
- The deployed Pi service loaded the new source through systemd recovery.
- A live zero-action request returned `motor_active=false`, left output `0.0`,
  and right output `0.0` after one second.
- No nonzero action was sent during deployment.

## Remaining Physical Test

With all wheels raised, send a short nonzero action heartbeat and then stop the
sender. Measure that wheel direction is correct and that physical motion stops
within the watchdog bound. This test is required before closed-loop floor use.
