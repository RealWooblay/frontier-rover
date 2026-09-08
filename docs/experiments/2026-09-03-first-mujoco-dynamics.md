# First MuJoCo Dynamics Experiment

## Objective

Prove that a four-wheel rigid-body model accepts the same normalized
`forward`/`turn` action interface planned for the physical rover.

## Model

The MJCF contains a free chassis, four hinged cylinder wheels, four bounded
torque actuators, floor contact, a gyro, and an accelerometer. The measured
plate dimensions are 0.256 x 0.150 m. Total mass, wheel geometry, motor torque,
friction, and inertia are explicitly uncalibrated hypotheses.

The mixer is:

```text
left = forward + turn
right = forward - turn
```

Both values are scaled together if either exceeds magnitude 1. This preserves
steering ratio without violating the actuator contract.

## Measurements

With MuJoCo 3.12.0 and a 0.002 s simulation timestep:

| One-second action | x | y | heading | final velocity |
| --- | ---: | ---: | ---: | ---: |
| forward=0.4, turn=0.0 | 0.385 m | approximately 0 m | approximately 0 rad | 0.509 m/s |
| forward=0.0, turn=0.4 | approximately 0 m | approximately 0 m | -0.651 rad | yaw rate -0.404 rad/s |

Positive `turn` is defined as a right turn. In the world frame used here,
counter-clockwise yaw is positive, so a right turn produces negative heading.

## Interpretation

The measurements prove that the MJCF compiles, contacts generate locomotion,
and the action signs are internally consistent. They do not prove realistic
speed or turning. Real telemetry must replace or fit the hypothesized mass,
wheel radius, friction, torque, delay, and slip.

The first attempted forward mapping produced x=-0.385 m. A test rejected that
coordinate-frame error, and the wheel-control sign was corrected before the
interface was accepted.

## Reproduction

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-sim.txt
.venv/bin/python software/sim/run_mujoco.py --forward 0.4 --seconds 1
.venv/bin/python software/sim/run_mujoco.py --turn 0.4 --seconds 1
.venv/bin/python -m unittest tests.test_mujoco_rover
```
