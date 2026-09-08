# Mapping, Runtime Parity, and Jetson Visual Motion

> Historical baseline. The contact-physics and rendered-camera replacement is
> documented in `2026-09-06-high-fidelity-mujoco-exploration.md`.

## Objective

Connect the physical Jetson mission service and MuJoCo target scenario through
one execution contract, add honest state-estimation/mapping/planning behavior,
and expose the result in an interactive engineering UI.

## Architecture

```text
Jetson: camera -> TensorRT + ORB -> controller -> shared MissionCommand -> Pi
Sim:    camera/range model -> controller/map -> shared MissionCommand -> MuJoCo
```

The hidden-target mapper receives an estimated pose, occupancy grid, simulated
range scan, and camera detection. Simulator ground truth is isolated for
sensor generation, collision scoring, and visualization.

## Prediction and Acceptance

- Both execution paths should use measured heading-turn and bounded-pulse
  semantics from `mission_runtime.py`.
- The simulated rover should construct a map, select frontiers, plan around
  obstacles, find the initially hidden target, and stop without collision.
- Imperfect odometry should create a visible, measurable estimate/truth gap.
- The deployed Jetson should compile and execute ORB/RANSAC on physical frames.
- The physical rover must remain disarmed during software acceptance.

## Result

- Full suite: 152 tests passed in 34.052 seconds.
- Canonical mapping run: ARRIVED in 14.49 simulated seconds.
- Replans: 8.
- Collisions: 0.
- Final target distance: 0.496 m.
- Final estimate-to-ground-truth position error: 0.2208 m.
- Runtime modes exercised: exploration, obstacle avoidance, target tracking,
  and target-memory planning.
- Jetson deployment checksums exactly matched the tested Mac files.
- Jetson service restarted active and disarmed.
- Saved physical-frame ORB check: 159 matches, 107 RANSAC inliers, 0.673 inlier
  ratio, `(-2.74, -2.47)` pixel displacement, and `0.044 degrees` image rotation.

Replayable evidence:

```text
artifacts/sim/2026-09-06-mapping-exploration.json
SHA-256 bef3979f60a7934ea1fe92ce20df25453efb15f58a7993d0179b9b463b3c0043
```

## Failure Evidence and Limits

Early simulated routes treated the rover as a point and collided with obstacle
edges. Inflating occupied cells by the rover clearance fixed the model error.
Target-memory motion initially tried a direct line and also collided; it now
routes the remembered target through the occupancy map.

The live Pi was unreachable at `192.168.0.87` during final deployment, while
the Jetson remained reachable at `192.168.55.1`. Therefore live-camera ORB in
the restarted service and a new physical target mission were not accepted in
this experiment. Existing physical frames proved Jetson execution without
claiming a live end-to-end run.

The physical rover lacks metric range and wheel-velocity observations. The
simulated occupancy map and hidden-target exploration are therefore genuine
MuJoCo software results but not physical SLAM or whole-house autonomy.

## Lesson

A simulator becomes useful when the controller consumes the same interfaces
and its hidden truth is used only for sensor generation and scoring. Sim2Real
is not the visual resemblance of the UI; it is the measured agreement of
observations, commands, dynamics, and failure behavior across the boundary.
