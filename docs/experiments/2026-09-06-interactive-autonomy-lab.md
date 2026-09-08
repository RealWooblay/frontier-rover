# Interactive Autonomy Lab

## Objective

Expose the physical robot, learned policy, simulator, Real2Sim validation, and
claim evidence through one inspectable interface.

## System Path

```text
Browser :8780 -> local lab server
               +-> Pi :8765 camera, telemetry, watchdog, manual command
               +-> Jetson :8771 TensorRT detection and autonomy state
               +-> local MuJoCo, policy artifact, and evidence files
```

The lab does not bypass either robot controller. The Pi retains final motor
authority and its stale-command watchdog. The Jetson remains explicitly armed
or disarmed.

## Evidence

- LIVE rendered the real 640 x 360 forward view and a normalized YOLO box.
- Real Pi camera, IMU, motor, watchdog, and Jetson telemetry populated through
  `/api/live`.
- Manual STOP was relayed through the lab and the Pi reported zero outputs.
- PROBE executed real TensorRT perception with `sent:false`.
- The simulator endpoint executed the same MuJoCo and learned-policy runtime
  used by held-out evaluation, including an injected actuator-stall scenario.
- 33 focused Python tests pass in the project Python 3.12 environment.
- Browser JavaScript syntax validation passes.

## Limits

The current local lab depends on the Mac. Its top-down waypoint simulator uses
abstract goal and clearance observations; it is not yet a rendered virtual
camera or a house-scale SLAM simulator.
