# IMU Turn Dynamics Real2Sim Fit

## Objective

Use synchronized physical motor commands and IMU measurements to replace and
fit the MuJoCo rover's initial constant-torque actuator, then evaluate it on a
separate physical command sequence.

## Data Path

```text
experiment phase -> Pi HTTP motor API -> TB6612 PWM -> physical rotation
                 -> MPU-9250 gyro -> Pi I2C samples -> timestamped CSV
                 -> bias removal -> rate integration -> measured turn angle
                 -> MuJoCo parameter search -> minimum simulation error
```

The physical log is
`artifacts/physical/2026-09-06-imu-motion.csv`. It contains 530 samples at a
target rate of 50 Hz and records the experiment phase, requested motion,
reported left/right PWM, acceleration, gyro rate, and temperature on one Pi
monotonic timeline.

## Measurements

- Stationary gyro bias: `(0.699, 1.276, 0.618) degrees/second` for X, Y, Z.
- Rover yaw maps to positive sensor Y for a left turn.
- Physical turn plus coast: `+127.7/-112.3 degrees`.
- Fitted turn plus coast: `+126.3/-112.4 degrees`.
- Fitted left-turn gain: `0.90`.
- Fitted right-turn gain: `0.84`.
- Fitted wheel-velocity feedback: `0.004`.
- Training trajectory error: `2.33 degrees RMS`.

The machine-readable fit is
`artifacts/sim/2026-09-06-imu-turn-fit.json`.

## Interpretation

The original actuator applied constant torque, so a long command continued to
accelerate unrealistically and coasted too long after PWM stopped. The revised
affine actuator computes force from command gain minus a term proportional to
wheel velocity. This approximates DC-motor back-EMF and braking. Directional
turn gains retain the asymmetry the training data can identify without falsely
claiming which individual motor caused it.

The separate `+60/-120/+60` closed-loop sequence was never used by the fitter.
On that held-out log, the original model produced `36.51 degrees RMS` error and
the revised model produced `14.34 degrees RMS`, a `60.7%` reduction. The long
right turn remains overpredicted by `23.36 degrees`, so the model improved but
did not pass as an accurate general model.

The experiment identifies rotational response only. It does not identify
linear speed, distance, wheel slip, floor friction, control delay, or individual
motor parameters. Those require additional observable measurements rather than
more parameters fitted to this same gyro trace.
