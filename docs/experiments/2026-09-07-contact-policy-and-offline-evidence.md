# Contact-World Policy and Offline Evidence

## Objective

Replace the simplified analytic policy benchmark with a Gymnasium environment
that uses MuJoCo contacts, imperfect observations, delayed actions, rendered
cameras, and auditable laptop-only evidence.

## Concept Being Learned

A trained policy is credible only when its observation boundary matches the
claimed interface and it is evaluated closed-loop on untouched scenarios. A
physics engine is useful only when physical parameters and assumptions are
distinguished.

## Architecture / Signal Path

```text
MuJoCo truth
  -> delayed/noisy rays, speed, and gyro
  -> dead-reckoned pose and nine-value observation
  -> deterministic expert or 9-32-2 MLP
  -> observation-only safety shield
  -> delayed normalized action
  -> wheel forces and MuJoCo contacts
```

Truth is retained for sensor generation, reward, and scoring. It is absent from
the policy observation.

## Assumptions

- Directional yaw gains and velocity feedback come from physical MPU fitting.
- Translation, friction, wheel slip, mass, and range-sensor behavior are not
  physically calibrated.
- Randomized ranges are engineering assumptions, not measured distributions.

## Predicted Result

Training should reduce held-out imitation error. Closed-loop learned-policy
success should at least match the expert, while the safety shield should reduce
contact episodes. A forced actuator stall should be visible as requested action
without executed action.

## Procedure

1. Build a Gymnasium wrapper around the contact MuJoCo rover.
2. Add delayed/noisy ranges, command delay, imperfect speed/gyro, and dead
   reckoning.
3. Train by behavior cloning and two DAgger rounds.
4. Compare expert and learned policy on the same 40 seeded randomized worlds.
5. Repeat 12 worlds with a complete actuator stall from 1.5 to 2.5 seconds.
6. Bind sources, models, artifacts, and metrics in an evidence manifest.

## Failure Observed

The first implementation leaked perfect MuJoCo speed and yaw rate into the
policy while using imperfect values only for pose estimation. This was fixed
and covered by a regression test.

The first safety branch still drove forward at roughly 15 cm clearance. One
scenario accumulated 34 contact episodes. A stateful observation-only shield
replaced the single threshold.

The first shield restarted its recovery timer every 50 ms while a fault stayed
active. A latched rising-edge transition fixed that behavior.

A larger 120-scenario, four-DAgger-round candidate did not improve held-out
success and reduced fault success. It was rejected rather than promoted based
on dataset size.

## Measurements

Training:

- Samples: 29,380
- Network: 9 inputs, 32 hidden tanh units, 2 outputs, 386 parameters
- Initial validation MSE: 0.28442
- Final validation MSE: 0.01749
- Model SHA-256:
  `782a3b40d5bc45bf3bdf71629c75ae8a3a20d7aa06187e3e1a53a0800fbf3c6e`

Nominal held-out evaluation:

- Deterministic expert: 32/40 success, 36 contact episodes
- Learned MLP plus shield: 33/40 success, 0 contact episodes
- Mean successful learned time: 8.087 s
- Mean learned final pose error: 0.1643 m

Injected actuator stall:

- Deterministic expert: 10/12 success, 13 contact episodes
- Learned MLP plus shield: 10/12 success, 0 contact episodes

Rendered smoke test:

- 49 paired chase/onboard JPEG frames from one timeout episode
- First chase frame: 9,708 base64 characters
- First onboard frame: 10,860 base64 characters

## Acceptance Result

All laptop-only acceptance checks pass in
`artifacts/sim/offline-autonomy-evidence.json`. Physical policy transfer is not
accepted because the rover cannot produce metric range or translational-speed
observations.

## Transfer to Other Domains

The same separation applies to robot arms, drones, underwater vehicles, and
industrial autonomy: the simulator owns truth, controllers receive realizable
observations, safety remains explicit, and transfer claims require matched
interfaces plus physical acceptance data.
