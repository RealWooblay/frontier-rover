# Practical Workshop and Four-Way Controller Comparison

## Question

Can the owner reproduce the path from detection to PWM and inspect a real
neural gradient? How much of the simulated navigation result comes from the
deterministic safety filter rather than the learned model?

## Method

- Added `software/learning/rover_workshop.py`: pure classroom box geometry,
  actual mission/controller/mixer functions, saved-network gradient check,
  and four-way contact-world comparison. No hardware connections.
- Compared baseline, baseline+filter, bounded neural output, neural+filter.
- Used 12 worlds generated with seed 260908, new for this comparison, fixed
  saved model, no retraining or threshold tuning.
- Each controller gets the same scenario, dynamics/fidelity settings and seed.
  Actions change trajectories and resulting observations; this does not imply
  identical sensor histories after trajectories diverge.
- Preserved the full episode results at
  `artifacts/sim/2026-09-08-controller-ablation.json` with the model SHA-256.

## Measurements

| Stack | Successes | Contact events | Missions containing contact |
| --- | ---: | ---: | ---: |
| Baseline | 12/12 | 10 | 5 |
| Baseline plus filter | 10/12 | 0 | 0 |
| Bounded neural policy | 10/12 | 48 | 5 |
| Bounded neural policy plus filter | 11/12 | 0 | 0 |

The gradient's analytic and finite-difference values agree:
`-0.0559373916644` versus `-0.0559373916728`. One in-memory update reduces
weighted example loss from `0.0033195173` to `0.0031481802`. The model's saved
bytes are verified unchanged. Four focused tests cover the gradient check,
alignment, approach, arrival, stale-frame stop and search operation.

Full verification: 171 tests passed in 13.773 seconds. The initial restricted
run could not bind the local HTTP test servers; rerunning with loopback access
enabled passed. Those tests use simulated motor drivers, not the physical rover.
The live lab's offline motor status was corrected from `stopped` to `unknown`:
missing telemetry cannot confirm a physical stop.

## Interpretation

The filter prevents observed contact events in both controller families on
this suite. This does not demonstrate collision-free behavior generally.
Baseline and neural action bounds differ, and one extra success among twelve
does not establish robust superiority. The original 40-world comparison
attributed performance to different full stacks, not isolated neural learning.

Sensor truth boundary: the policy does not directly see the simulator's x/y
pose, but contact and stuck flags include ideal simulator state. Initial pose
and goal coordinates are known in the arena. These assumptions must be met or
replaced before physical policy transfer.

Separate audit correction: `validate_closed_loop_turn.py` validates three
final-yaw endpoints. The 36.51 -> 14.34 degree RMSE improvement is not an error
metric over all time samples. The reference is the gyro, not external metrology.

## Physical Status

The owner reports that the Belkin works again. The local lab responded but
reported Pi no route and Jetson timeout during this session. No motion, device
configuration changes or physical acceptance run occurred. Today's recording
and physical demo remain pending fresh readiness and operator preparation.

## Teaching Outcome

The new practical course explains image preprocessing and decoding, controller
geometry and motor duty, gradient arithmetic, MuJoCo state/observations/actions,
system identification, behavioral cloning/DAgger, safety attribution, mapping
versus SLAM and travel exercises. Each has code, expected measurements and
primary-source resources. Owner understanding remains to be demonstrated by
predicting an experiment and explaining its outcome; passing tests is not proof
of understanding.
