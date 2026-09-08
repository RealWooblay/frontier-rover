# Mandarin Search and Approach

## Objective

Run pretrained TensorRT object perception and the shared deterministic
controller in a physical camera-to-motor loop.

## System Path

```text
Pi camera -> Mac SSH relay -> Jetson TensorRT YOLO -> TargetController
-> Mac SSH relay -> Pi action API/watchdog -> TB6612 -> four motors
```

The Mac relay is a development dependency and prevents this run from proving
fully onboard autonomy.

## Configuration

- Target class: COCO `orange`
- Confidence threshold: 0.20
- Effective area-only arrival threshold: 0.103
- Floor-object bottom-edge arrival threshold: 0.920
- Minimum area for bottom-edge arrival: 0.030
- Alignment tolerance: 0.40
- Maximum forward command: 0.70
- Turn range: 0.30 to 0.35
- Search turn pulse: 45 ms
- Alignment pulse: 35 ms
- Approach pulse: 50-150 ms, shortened as apparent area increases
- Stale-frame limit: 500 ms
- Pi motor calibration: 0.80 left, 1.00 right

## Evidence

- TensorRT perception accepted the physical mandarin.
- The controller entered SEARCHING, ALIGNING, APPROACHING, and ARRIVED.
- Run 3 recorded 67 updates: 48 search, 10 alignment, 8 approach, 1 arrival.
- Maximum detected target area was 0.140.
- Median perception pipeline time was 53.63 ms.
- Median action transport time was 20.57 ms.
- The current controller passes 27 focused unit/simulation tests.
- The current randomized simulation evaluation passed 20/20 scenarios.
- Mission 13 completed with 7 ALIGNING, 8 REACQUIRING, 6 APPROACHING,
  and 1 ARRIVED control updates.
- The terminal detection remained visible at 0.923 bottom-edge ratio and 0.081
  area ratio; ARRIVED sent zero motion before the floor target entered the
  camera blind zone.
- The post-mission Pi status reported `motor_active:false` and both outputs at
  zero.
- Mission 14 began with the mandarin outside the camera view. It completed 72
  SEARCHING, 6 ALIGNING, 9 APPROACHING, 7 REACQUIRING, and 1 ARRIVED control
  updates. The terminal detection measured 0.113 area and 0.930 bottom-edge
  ratio, and the post-mission Pi status again reported zero motor output.
- Missions 13 and 14 are consecutive accepted physical runs from visible and
  hidden-target starting conditions.

Physical telemetry is stored in `artifacts/physical/`. Seeded simulation output
is stored in `artifacts/sim/mandarin-search-calibrated-seed-7.jsonl`.

## Failures And Corrections

1. Continuous `0.40` alignment commands overshot because real observations
   arrived more slowly than the simulator's 50 ms control period.
2. Pulsed `0.20` commands were too weak after drivetrain calibration and barely
   overcame motor/gearbox stiction.
3. Higher-amplitude 70 ms pulses produced effective rotation without retaining
   a command between observations.
4. A 0.08 alignment threshold caused limit-cycle oscillation. The measured
   actuator resolution supports a 0.15 threshold.
5. Noisy apparent area caused motion after the first ARRIVED update. ARRIVED is
   now latched for the remainder of a controller run.
6. Area alone was not a reliable stopping signal for a floor object. The
   camera could lose the mandarin below its field of view before the selected
   area threshold. Normalized box-bottom position is now a second proximity
   signal, gated by minimum area to reject tiny edge detections.
7. Fixed-duration approach pulses moved too far per observation when close.
   Pulse duration now decreases from 150 ms toward 50 ms as apparent area
   approaches the area target.

## Remaining Acceptance Work

- Repeat across additional lighting, floor, bearing, and distance conditions.
- Remove the Mac relay from the onboard data path.
- Correct or synchronize the Jetson clock before combining device logs.
- Record MPU-9250 motion and Pi PWM with camera/actions on one timeline.
- Fit and validate MuJoCo motor, friction, delay, and slip parameters.
- Train and evaluate a policy before claiming learned driving control.
