# Resume Claim Validation

The resume claims are completion targets, not evidence by themselves. Each is
accepted only when the repository contains reproducible code, measurements,
held-out evaluation, and an explicit failure demonstration.

## Claim 1: Real2Sim/Sim2Real Training Loop

Resume wording: physics-based simulation, domain randomization, rover telemetry,
and driving-policy transfer to hardware.

Acceptance evidence:

- Synchronized real action, camera, and IMU logs.
- A MuJoCo rover using the real controller's observation/action interface.
- Fitted physical parameters and a documented calibration loss.
- Before/after errors on held-out real trajectories.
- Domain-randomized policy training with fixed evaluation seeds.
- Physical deployment compared against the deterministic controller.

Status: laptop simulation and Real2Sim evidence complete; physical learned-policy
transfer pending. A synchronized 530-sample motor/IMU trajectory fitted
directional actuator gains and velocity feedback. On a separate held-out
`+60/-120/+60` physical sequence, the revised model reduced final-yaw endpoint
RMSE across three turns from `36.51` to `14.34 degrees` (`60.7%`). It did not
measure full-trajectory validation RMSE. The accepted contact-world `9 -> 32 -> 2`
policy used 29,380 samples, behavior cloning, two DAgger rounds, randomized
dynamics, imperfect sensors, dead reckoning, and a deterministic observation-
only safety shield. It completed 33/40 held-out MuJoCo missions with zero
contact episodes versus 32/40 and 36 contact episodes for the deterministic
expert. During a forced one-second actuator stall it completed 10/12 worlds
with zero contact episodes. Physical closed-loop transfer is not accepted
because the rover cannot yet measure wheel velocity or obstacle clearances
used by the policy. The earlier 39/40 result used a simplified analytic
environment and is retained only as historical baseline evidence.

The original policy benchmark compares different stacks: only the learned side
has the safety filter. On 2026-09-08, an untuned fresh 12-world comparison found:
baseline 12 successes/10 contact events; baseline+filter 10/0; bounded neural
policy 10/48; neural+filter 11/0. Both families benefit from the filter. Different
action bounds and the small sample prevent strong architecture-only claims.
Contact and stuck inputs include ideal simulator information; physical sensor
equivalents are unimplemented. See the practical course and dated ablation JSON.

## Claim 2: Vision-to-Control Models

Resume wording: autonomous waypoint following, obstacle avoidance, and recovery.

Acceptance evidence:

- Defined observation, action, episode, reward, and failure conditions.
- Versioned training and validation datasets or simulation seeds.
- Deterministic-controller baseline.
- Separate metrics for waypoint completion, collisions, and recovery.
- Real-world trials with unsuccessful runs retained in the report.

Status: simulation accepted; physical generalization pending. MuJoCo now has
single-goal contact-world missions (the older analytic environment uses two
waypoints), obstacles, collision detection, actuator-stall
fault injection, deterministic expert behavior, and a trained neural policy.
Held-out contact-world metrics separately report success, contact episodes,
recoveries, reward, elapsed time, pose error, and path length; all seven learned
policy timeouts remain in the artifact. TensorRT YOLO
plus SEARCH -> REACQUIRE -> ALIGN -> APPROACH -> ARRIVED has executed against
the physical camera/motors, but physical waypoint and obstacle trials are not
accepted because the corresponding real observations are not available.
The second simulation milestone adds a hidden target, dead-reckoned pose,
MuJoCo 200-degree geometry rays, a log-odds occupancy grid, frontier selection,
A* planning, target memory, delayed/noisy sensors, rendered RGB perception,
and contact-solver recovery. Its upgraded canonical run arrived in 33.932
simulated seconds with zero contacts and a 0.4303 m final pose-estimation error.
A 12-trial rendered-camera randomized evaluation completed 10/12 missions and
10/12 without contact; both timeouts remain in the artifact. This is accepted
as simulation evidence, not physical mapping: the physical rover still lacks
metric range and wheel odometry observations, and most translation/sensor
parameters remain assumptions rather than a calibrated digital twin.

## Claim 3: Onboard Closed-Loop TensorRT Autonomy

Resume wording: TensorRT on Jetson Orin with Raspberry Pi safety control.

Acceptance evidence:

- Camera-to-action loop runs on the Jetson without the development Mac.
- TensorRT inference latency and complete loop frequency are measured.
- Pi accepts bounded continuous actions while retaining final motor authority.
- Target loss, stale frame, network loss, and process failure all stop motion.
- A repeatable physical mission completes under documented conditions.

Status: partially accepted. A physical mandarin mission produced SEARCHING,
ALIGNING, APPROACHING, and ARRIVED states. Median TensorRT perception pipeline
time was 53.63 ms and median action transport time was 20.57 ms. A persistent
Jetson `systemd` service now owns explicit arming, live status, target/config
changes, perception-only probing, stale-frame rejection, ordered disarm, and
safe-stop behavior. A live probe processed a Pi frame in 102.77 ms total with
60.63 ms TensorRT inference and sent no motor command. Three failed missions
were retained; they timed out after intermittent or absent orange detections,
then automatically disarmed. After adding a floor-object bottom-edge proximity
signal and distance-scaled motion pulses, mission 13 aligned, reacquired,
approached, and stopped while the mandarin was still fully visible. Terminal
geometry was 0.923 normalized box-bottom and 0.081 area ratio, followed by
verified zero Pi motor output. Mission 14 then began with the target outside
the camera view and completed SEARCH, ALIGN, APPROACH, REACQUIRE, and ARRIVED;
its terminal geometry was 0.930 box-bottom and 0.113 area, again followed by
zero Pi motor output. A later measured-search revision replaced blind 45 ms
search pulses with MPU-9250-controlled 30-degree steps. Its physical hidden-
target acceptance mission completed a bounded sweep, viewpoint recovery,
opposite-direction reacquisition, approach, and ARRIVED at 0.990 box-bottom
and 0.122 area, followed by independently verified zero Pi motor output. The
current camera/action transport still depends on the development Mac's SSH
tunnel. Independent operation requires connecting
the Pi USB host directly to the Jetson USB device-mode port and repeating the
acceptance test.

The Jetson service additionally runs ORB feature extraction, Hamming feature
matching, and RANSAC homography estimation. A Jetson-native check on two saved
physical frames found 159 matches and 107 inliers and estimated a
`(-2.74, -2.47)` pixel image displacement. This proves image-motion execution
on the Jetson, but monocular metric scale and a physical map remain unproven.

## Defensible Current Wording

Implemented a Raspberry Pi/Jetson rover with watchdog-bounded PWM control,
TensorRT target perception, IMU-closed-loop relative turns, physically fitted
MuJoCo yaw dynamics, domain-randomized policy evaluation, and a sensor-driven
simulated occupancy/frontier planning stack. Physical metric mapping and
learned-policy transfer remain explicitly pending sensor and transport work.

The machine-verifiable claim ledger is
`artifacts/sim/offline-autonomy-evidence.json`. It binds the accepted model,
training report, evaluation, physical IMU source, fitted dynamics, mapping
benchmark, and implementation files by SHA-256.

## First Baseline

`software/jetson/autonomy_controller.py` implements the first deterministic
visual-target controller. `software/jetson/autonomy_dry_run.py` connects it to
the real camera perception path but contains no motor-command transport. This
lets controller sign, bounds, target-loss behavior, and stale-frame behavior be
validated before physical movement is possible.
