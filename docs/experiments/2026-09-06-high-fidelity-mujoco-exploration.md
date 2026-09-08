# High-Fidelity MuJoCo Exploration

## Objective

Replace the simplified hybrid mapping demo with an auditable environment in
which MuJoCo owns obstacle contact, wall contact, range geometry, wheel motion,
and onboard camera pixels. Quantify robustness under explicit sensor, actuator,
and timing variation without claiming unmeasured parameters are physical facts.

## System Path

```text
desired action
  -> command-latency queue
  -> left/right drive scaling
  -> MuJoCo wheel actuators
  -> wheel/floor/wall/obstacle contact solver
  -> true simulated chassis motion

MuJoCo geometry -> 41 mj_ray intersections -> noise/dropout/latency -> occupancy grid
MuJoCo RGB      -> HSV target pixels       -> latency/dropout       -> target controller
simulated speed + gyro -> scale/bias/noise -> dead reckoning        -> estimated pose

estimated pose + occupancy grid + target memory -> frontier/A* planner -> desired action
true pose                                       -> scoring and optional white UI overlay only
```

The planner never receives target coordinates, obstacle coordinates, or true
pose. MuJoCo necessarily owns truth because a simulator needs it to compute
physics and generate sensor observations.

## Interfaces and Units

| Boundary | Data | Units / rate |
|---|---|---|
| Planner to actuator | `forward`, `turn` | normalized `[-1, 1]`, nominal 20 Hz |
| Actuator to physics | four wheel controls | normalized motor command, 2 ms physics step |
| Geometry to range head | 41 ray distances | metres, 200 degree field, 5 degree spacing |
| Renderer to detector | RGB frame | 320 x 180, nominal 10 Hz |
| Detector to controller | visible, horizontal error, area, bottom edge | booleans and normalized ratios |
| Motion sensor to estimator | forward speed, yaw rate | m/s and rad/s |
| Estimator to mapper/planner | planar pose and uncertainty | metres and radians |

The simulated range head is 0.10 m in front of the chassis origin. Its rigid
transform is applied before occupancy updates. Omitting that transform caused
the first high-fidelity run to create inconsistent cells around the rover and
made A* repeatedly fail.

## Contact Physics

Walls and obstacles are MuJoCo geoms. The chassis and wheels can create solver
contacts with them. A collision is counted from a new contact episode and the
controller commands a turn-in-place recovery. The old implementation checked
circle overlap analytically and teleported the rover to its previous pose; that
path has been removed.

`mj_ray` intersects the compiled wall and obstacle geometry. It does not call
the analytic circle-distance helper used by the original demo. Noise, dropped
beams, and delivery latency are applied only after the ideal physical ray is
computed.

## Camera Perception

The rover camera is rigidly attached to the MuJoCo chassis. The target is an
orange sphere. MuJoCo renders an RGB image, then OpenCV converts RGB to HSV and
segments orange pixels. The detector returns a box, horizontal image error,
pixel area, bottom edge, and an approximate monocular range from apparent box
width.

Two interface faults were found during acceptance:

1. Image-left was initially encoded as a positive error, while the shared
   controller defines positive as image-right. The rover turned away from the
   target and projected target memory outside the room.
2. A three-pixel target fragment visible around an occluder produced a false
   9.38 m range. The detector now rejects boxes narrower than six pixels.

These were coordinate and observability errors, not failures of MuJoCo itself.

## Timing and Imperfection Model

The simulator includes separate FIFO delays for range measurements, camera
frames, and motor commands. Seeded Gaussian noise affects range, speed, and
gyro observations. Seeded Bernoulli dropout affects range beams and camera
updates. Left/right drive scaling and floor friction can be varied per run.

This matters because delay changes the closed loop: the controller acts on an
older world state, and its command takes additional time to affect motion. A
visually plausible animation without these queues would not test that failure
mode.

## Evidence

Canonical rendered-camera run:

- Result: ARRIVED
- Simulated time: 33.932 s
- Contact episodes: 0
- Final truth target distance: 0.508 m
- Final estimate/truth position error: 0.4303 m
- Artifact: `artifacts/sim/2026-09-06-mapping-exploration.json`
- SHA-256: `595dc5947299107ed7a6a2cadac5aba373028c264bec11a424f2ed21248103f7`

Domain-randomized rendered-camera evaluation:

- Trials: 12
- Successes: 10
- Collision-free trials: 10
- Mean final pose error: 0.1882 m
- Mean successful elapsed time: 7.3752 s
- Artifact: `artifacts/sim/2026-09-06-high-fidelity-exploration.json`
- SHA-256: `baa8f30b4b268f3f48bd9e3f93bef1f1f63a43df777f876e4ac6f4feace2533c`

Trials 0 and 8 timed out after seeing the target. They combine approximately
176-180 ms camera latency, 81-94 ms command latency, dropout, motor asymmetry,
and other randomized parameters. They remain replayable failures.

## Parameter Truth

Measured from the physical rover:

- Directional yaw gains and velocity feedback fitted from MPU-9250 turn logs.
- Held-out yaw fit error and physical heading-control error.

Configured or assumed, not physically identified:

- 0.8 kg chassis mass.
- Floor friction and wheel slip.
- Forward motor response and left/right drive-scale distribution.
- Camera extrinsic pose and optical model.
- Range noise/dropout/latency because the real rover has no range sensor.
- Pi/Jetson command-latency distribution.
- Exact room and obstacle geometry.

The result is a higher-fidelity development environment, not a complete
digital twin. Accuracy can only improve by measuring these quantities on the
assembled rover and fitting or validating them against held-out physical logs.

## Reproduction

```bash
.venv/bin/python software/sim/run_mapping_exploration.py
.venv/bin/python software/sim/evaluate_exploration_fidelity.py --count 12 --seed 907
.venv/bin/python -m unittest tests.test_mujoco_world tests.test_exploration_scenario
```

The rendered commands require a macOS graphical session. In a headless test
environment the runtime explicitly reports a geometric-camera fallback.

## Transferable Lesson

Simulation fidelity is interface agreement plus measured error, not visual
detail. A useful simulator preserves coordinate frames, sensor origins,
latency, noise, actuation, contacts, and observation boundaries. Real2Sim fits
unknown parameters from physical logs. Sim2Real then tests whether behavior
developed over a distribution of those parameters still works on hardware.

Teach-back: why did the image-sign bug make target memory wrong even though the
renderer and detector both produced valid outputs?
