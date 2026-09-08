# Straight-Line Heading Hold

## Objective

Replace fixed-PWM straight driving with an optional observable feedback loop
that rejects small rotational disturbances during manual forward and reverse
commands.

## System Path

```text
MPU-9250 gyro Y at 50 Hz
  -> bias-corrected yaw rate
  -> integrated relative yaw
  -> PD heading controller at 100 Hz
  -> corrected left/right PWM
  -> two TB6612 boards
  -> four motors
```

The camera and neural navigation policy are not part of this loop. The browser
continues refreshing the selected motion every 100 ms, and the independent Pi
watchdog stops motor output after 350 ms without a fresh command.

## Control Law

At button press, `reference_yaw` is set to the current relative yaw. During the
same held command:

```text
error = reference_yaw - measured_yaw
correction = clamp(0.012 * error - 0.004 * yaw_rate, -0.18, +0.18)
left = base_left - correction
right = base_right + correction
```

The reference is not reset by each browser heartbeat. It is reset when motion
stops or changes direction. Forward and reverse use the same differential-turn
correction sign.

## Safety Boundaries

- Heading hold is opt-in and persisted separately from motor calibration.
- It applies only to manual `forward` and `reverse` commands.
- A missing, non-streaming, or older-than-150-ms IMU sample stops output.
- Correction is bounded and cannot reverse either side.
- The 350 ms command watchdog remains authoritative.
- Intermittent wiring is a hardware fault, not a tuning condition.

## Software Evidence

The complete project suite passed 136 tests on 2026-09-06. Focused tests prove
forward correction, reverse correction, reference retention across heartbeats,
stale-IMU stopping, setting persistence, and API behavior.

## Physical Acceptance Pending

1. Rigidly secure and insulate the MPU board in its existing vertical
   orientation; sensor Y is the experimentally identified chassis-yaw axis.
2. Leave heading hold off and record baseline heading error over a marked run.
3. Enable heading hold and repeat the same run at the same throttle.
4. Compare final absolute heading error and inspect correction saturation.
5. Reject the controller if the first correction increases yaw error; that
   indicates a sign or physical-axis mismatch.
