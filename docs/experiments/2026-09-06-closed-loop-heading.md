# Closed-Loop Relative Heading

## Objective

Close the motor-to-motion loop by commanding relative turn angles and stopping
from MPU-9250 feedback rather than a fixed duration.

## Controller

```text
target angle - integrated gyro angle = heading error
heading error sign                    = turn direction
large error                           = continuous turn
near target                           = stop and settle
remaining error                       = bounded correction pulse
```

The Pi first collected 1.5 seconds of stationary gyro data. Sensor Y bias was
`1.288 degrees/second` and noise standard deviation was `0.373 degrees/second`.
It sampled at 50 Hz, integrated bias-corrected yaw with the trapezoidal rule,
and refreshed motor commands at 10 Hz, faster than the 350 ms watchdog limit.
Every exit path issued `stop`.

## Physical Result

| Relative target | Measured | Absolute error | Corrections |
| ---: | ---: | ---: | ---: |
| `+60 degrees` | `+60.33 degrees` | `0.33 degrees` | 1 |
| `-120 degrees` | `-117.98 degrees` | `2.02 degrees` | 1 |
| `+60 degrees` | `+59.24 degrees` | `0.76 degrees` | 1 |

The three requested turns sum to zero; measured turns sum to approximately
`+1.60 degrees`. This demonstrates short-term relative heading control. It is
not global localization: gyro bias still drifts over long periods, and the
controller forgets absolute orientation when restarted.

Data: `artifacts/physical/2026-09-06-closed-loop-turn.csv`.

## Failure Boundaries

- Calibration aborts if stationary gyro noise exceeds `2 degrees/second`.
- Every turn is limited to `[-180, 180] degrees` and has a time limit.
- Corrections are limited to eight attempts.
- The Pi motor watchdog independently stops stale commands after 350 ms.
