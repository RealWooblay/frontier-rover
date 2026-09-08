# Domain-Randomized Navigation Policy

## Objective

Train and independently evaluate a policy that maps rover observations to
bounded forward/turn actions in MuJoCo, then execute the unchanged artifact on
the Jetson.

## Interface

Inputs are goal distance/error, front/left/right clearance, forward velocity,
yaw rate, collision, and stuck state. Outputs are normalized forward and turn.
The network shape is `9 -> 32 tanh -> 2 tanh`, totaling 386 parameters.

## Training

- Seed: `23`
- Final training examples: `45,727`
- Validation examples excluded from updates: `4,263`
- Initial validation MSE: `0.194319`
- Final validation MSE: `0.005468`
- Dataset aggregation: three learner-state collection and relabel rounds
- Artifact: `artifacts/models/navigation-policy.npz`
- SHA-256: `34f500938035ee080e5993dab95bf37c45702d07037084b44998c77f4e7ec7a4`

## Held-Out Simulation

Forty seed-101 worlds randomized floor friction, asymmetric motor gains, and
velocity feedback. The deterministic expert completed 35/40 (`87.5%`); the
learned policy plus safety guard completed 39/40 (`97.5%`). Both recorded zero
collisions. Under a forced one-second actuator stall, the learned system
recovered in 8/8 worlds.

## Transfer Boundary

The same artifact and checksum were verified on the Jetson. A centered,
clear-path observation produced `forward=0.606495` and `turn=-0.000879` there.
This proves artifact transfer and inference, not physical policy control. The
physical rover still lacks wheel-velocity and obstacle-clearance observations.
