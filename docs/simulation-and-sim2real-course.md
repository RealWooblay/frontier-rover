# Frontier Rover Simulation and Sim2Real Course

This course explains the simulation, learning, estimation, mapping, and
evidence pipeline that now exists in this repository. It is written so the
system can be explained from mechanism rather than memorized terminology.

## 1. The Complete Loop

A robot repeatedly executes one causal loop:

```text
world state x
  -> sensors produce observation z
  -> estimator produces estimated state x_hat
  -> policy or planner proposes action u
  -> safety layer accepts or changes u
  -> actuators apply forces
  -> physics produces the next world state
  -> repeat
```

The compact mathematical form is:

```text
x[t+1] = f(x[t], u[t], physical_parameters) + disturbance
z[t]   = h(x[t]) + sensor_noise
u[t]   = policy(z[t], x_hat[t], memory[t])
```

`f` is the dynamics model. In this project MuJoCo numerically integrates it.
`h` is the sensor model. Here it includes geometry rays, speed, gyro, and
rendered cameras. The policy never receives `x` directly. MuJoCo truth is kept
separately for sensor generation, reward, and evaluation.

That separation is the most important rule in simulation. If the policy sees
perfect simulator state that the physical rover cannot observe, the benchmark
is invalid for transfer.

## 2. Coordinate Frames and Signs

The world uses metres, seconds, radians, and these planar conventions:

```text
world x: horizontal room axis
world y: horizontal room axis
heading: rover orientation in the world plane
body forward: rover's local +x direction
positive turn action: clockwise/right
```

The goal bearing is calculated from estimated position:

```python
dx = goal_x - estimated_x
dy = goal_y - estimated_y
world_bearing = atan2(dy, dx)
body_bearing = wrap_angle(world_bearing - estimated_heading)
goal_error = -body_bearing / pi
```

The minus sign converts mathematical counter-clockwise angles into the rover's
positive-right action convention. A sign error here makes the rover turn away
from its goal while every individual value still appears reasonable.

The vertically mounted MPU-9250 has a different sensor frame. Physical tests
identified its Y gyroscope axis as rover yaw. Mounting orientation is therefore
configuration, not decoration.

## 3. What Makes This a Physics Simulation

The MuJoCo model is built in
`software/sim/mujoco_world.py` and driven through
`software/sim/mujoco_rover.py`.

It contains:

- A chassis with mass and inertia.
- Four rotating wheel joints.
- Wheel actuators that create torque.
- Floor and wheel friction.
- Obstacles with collision geometry.
- A contact solver that prevents bodies passing through each other.
- A numerical integrator advancing state in small time steps.
- Rover-attached and fixed cameras.

For each simulation step, MuJoCo solves a constrained rigid-body problem. In
plain language:

1. Motor commands request wheel torque.
2. Wheel-floor friction converts wheel torque into chassis force.
3. Gravity, inertia, damping, and contact constraints contribute forces.
4. MuJoCo calculates accelerations that satisfy the constraints.
5. The integrator updates velocity and position.

The browser does not calculate those positions. It receives frames and
telemetry generated after MuJoCo has advanced the model.

This is more real than a hand-coded animation, but it is not automatically a
digital twin. A digital twin requires enough measured parameters and validation
to predict the physical system inside stated error bounds. Only directional
yaw response has been physically fitted so far. Translation speed, mass,
friction, wheel slip, and motor deadband remain assumed or randomized.

## 4. The Gymnasium Contract

`software/sim/high_fidelity_env.py` wraps MuJoCo in the standard Gymnasium
environment interface.

```python
observation, info = env.reset(seed=seed)
observation, reward, terminated, truncated, info = env.step(action)
```

The terms mean:

- `observation`: information available to the controller.
- `action`: normalized `[forward, turn]` command in `[-1, 1]`.
- `reward`: a training/evaluation score for the last transition.
- `terminated`: the task reached its success condition.
- `truncated`: time expired before success.
- `info`: diagnostic truth and metrics unavailable to the policy.

Gymnasium does not make the simulation physical and does not train a model. It
standardizes how agents and environments exchange data. That lets training,
evaluation, replay, and later reinforcement learning use the same boundary.

## 5. The Observation Vector

The learned policy receives exactly nine normalized numbers:

```text
0 goal_distance      estimated distance / 3 m
1 goal_error         estimated bearing error / pi, positive means right
2 front_clearance    closest front ray / 2.2 m
3 left_clearance     closest left ray / 2.2 m
4 right_clearance    closest right ray / 2.2 m
5 forward_velocity   imperfect speed / 0.6 m/s
6 yaw_rate           imperfect gyro rate / 4 rad/s
7 collision          0 or 1
8 stuck              0 or 1
```

Normalization makes values similar in scale. It does not add information. A
normalized clearance of `0.25` means approximately:

```text
0.25 * 2.2 m = 0.55 m
```

The goal values use the dead-reckoned pose, not true pose. Speed and yaw rate
are scaled, biased, and noisy before they enter both the estimator and policy.
An earlier implementation accidentally gave the policy perfect MuJoCo speed
and yaw while the estimator used imperfect measurements. Tests now explicitly
prevent that truth leak.

## 6. Sensor Modeling

### Geometry rays

MuJoCo `mj_ray` casts rays into collision geometry. It returns the distance to
the first intersected body. Forty-one rays cover `-100` to `+100` degrees.
They are grouped into front, left, and right sectors by taking each sector's
minimum distance.

The simulation then adds three real-system effects:

```text
noise:   measured distance differs slightly from geometric distance
dropout: a reading is replaced by maximum range
latency: a reading is delivered after a queue delay
```

Latency matters because the rover moves while data waits. At `0.4 m/s`, a
`100 ms` delay means the rover travels about `4 cm` before reacting.

### Gyroscope

A MEMS gyroscope measures angular velocity, not heading. Heading is obtained
by integration:

```text
heading[t+1] = heading[t] + yaw_rate[t] * dt
```

A constant bias also integrates. A `0.2 deg/s` bias becomes roughly `12 deg`
of heading error after one minute.

### Odometry speed

The simulated speed observation has scale error and random noise:

```python
measured_speed = true_speed * odometry_scale + random_noise
```

The physical rover currently has no wheel encoders, so it cannot produce this
metric translational observation. That is the main reason the learned
navigation policy is not deployable on hardware yet.

### Cameras

The exploration environment renders RGB pixels through a MuJoCo camera. An HSV
detector finds orange pixels and estimates target geometry. The policy arena
renders a chase camera and onboard camera for evidence, but its nine-input
navigation policy does not consume those images.

## 7. State Estimation

The estimator integrates imperfect speed and gyro:

```text
heading += measured_yaw_rate * dt
x += measured_speed * cos(heading) * dt
y += measured_speed * sin(heading) * dt
```

This is dead reckoning. It estimates motion from previous state plus measured
change. It drifts because every error is accumulated.

The simulator maintains two states:

```text
ground_truth: MuJoCo body position and velocity
estimate:     position and heading reconstructed from imperfect sensors
```

Pose error is their Euclidean separation and is used only for evaluation:

```text
pose_error = sqrt((x_hat - x_true)^2 + (y_hat - y_true)^2)
```

Production localization adds observations that constrain accumulated drift:
wheel encoders, visual-inertial odometry, lidar scan matching, landmarks, GPS,
or loop closure. The exact source depends on the operating environment.

## 8. Mapping and Planning

`software/sim/exploration_scenario.py` implements a full classical stack:

```text
delayed/noisy rays
  -> inverse sensor model
  -> log-odds occupancy grid
  -> obstacle inflation
  -> frontier selection or remembered target
  -> A* path
  -> local path tracking
```

### Occupancy grid

The room is divided into cells. Each cell stores belief about occupancy.
Log-odds let repeated evidence be added:

```text
L(cell) = log(P(occupied) / (1 - P(occupied)))
L_new = L_old + sensor_evidence
```

A ray contributes free evidence along its path and occupied evidence at its
endpoint. Repeated consistent observations increase confidence. Contradictory
observations reduce it.

### Obstacle inflation

A point path could pass beside an obstacle while a real chassis collides.
Inflation expands occupied cells by approximately the rover radius plus margin.
Then a point planned through the inflated map represents a finite-size rover.

### Frontiers

A frontier is a boundary between known free space and unknown space. Selecting
a frontier gives the rover somewhere informative to explore when the target is
not currently observed.

### A star

A* searches grid cells using:

```text
priority = cost_from_start + estimated_cost_to_goal
```

The heuristic directs search toward the goal while accumulated cost preserves
the shortest known collision-free route.

The current randomized rendered-camera mapping benchmark completed `10/12`
missions. The two timeouts are retained. This proves the software path in the
virtual observation model; it does not prove physical mapping.

## 9. Deterministic Expert

The expert in `software/sim/navigation_env.py` is a reactive controller. It
aligns to the estimated goal, advances when clear, avoids low front clearance,
and reverses after collision or lack of progress.

It is called an expert because it provides demonstration labels, not because it
is optimal. On the accepted contact-physical held-out set it completed `32/40`
missions and recorded `36` contact episodes. Those weaknesses matter: behavior
cloning can inherit teacher errors.

## 10. What a Neural-Network Weight Is

The policy is a `9 -> 32 -> 2` multilayer perceptron in
`software/sim/mlp_policy.py`.

For one hidden neuron:

```text
hidden_j = tanh(
    observation_0 * weight_0j
  + observation_1 * weight_1j
  + ...
  + observation_8 * weight_8j
  + bias_j
)
```

The output layer repeats the operation using the 32 hidden activations:

```text
forward = tanh(sum(hidden_j * output_weight_j_forward) + forward_bias)
turn    = tanh(sum(hidden_j * output_weight_j_turn) + turn_bias)
```

A weight is therefore a stored coefficient controlling how strongly one value
affects a later value. It is not a rule by itself. The behavior emerges from
all coefficients and nonlinear activations together.

There are 386 trainable parameters:

```text
9 * 32 input weights
+ 32 hidden biases
+ 32 * 2 output weights
+ 2 output biases
= 386
```

### How training changes a weight

For a demonstration with expert target `y` and network output `y_hat`, the loss
is mean squared error:

```text
loss = mean((y_hat - y)^2)
```

Backpropagation applies the chain rule to calculate how much changing each
weight would change the loss:

```text
gradient = d(loss) / d(weight)
```

An optimizer then moves the weight in the direction expected to reduce loss:

```text
weight = weight - learning_rate * adjusted_gradient
```

This happens for batches of examples across many epochs. Adam keeps moving
averages of each gradient and squared gradient so noisy or differently scaled
parameters receive more stable updates.

The model is not told the sentence “avoid the obstacle.” It is shown observation
vectors and desired actions. Gradient descent adjusts coefficients so those
inputs produce outputs closer to the labels.

## 11. Behavior Cloning and DAgger

### Behavior cloning

The expert drives randomized MuJoCo worlds. Each sample stores:

```text
(nine observed values, expert forward action, expert turn action)
```

The MLP minimizes error on those samples. The problem is distribution shift:
the learned policy makes small errors, reaches states the expert dataset did not
contain, and may not know how to recover.

### DAgger

Dataset Aggregation addresses that problem:

1. Let the current learned policy drive.
2. Record the observations it actually visits.
3. Ask the deterministic expert what it would do at those same observations.
4. Add those labeled states to the training set.
5. Retrain.

The accepted training run used initial expert demonstrations plus two DAgger
rounds and produced `29,380` samples. Validation MSE fell from about `0.2844`
to `0.01749`.

Lower imitation error is not enough. Closed-loop evaluation is mandatory
because tiny action errors can accumulate over hundreds of steps.

## 12. Training, Validation, and Held-Out Evaluation

These datasets answer different questions:

```text
training:   adjusts weights
validation: monitors imitation error while developing the model
evaluation: untouched scenarios used for final comparison
```

Using evaluation scenarios to tune repeatedly turns them into validation data.
For a stronger portfolio result, create a final hidden seed set after design is
frozen and report it once.

The current accepted held-out comparison uses the same 40 randomized worlds,
dynamics, sensors, and seeds for both controllers:

```text
deterministic expert: 32/40 success, 36 contact episodes
learned MLP + shield:  33/40 success,  0 contact episodes
```

With a complete actuator stall from `1.5` to `2.5 s`:

```text
deterministic expert: 10/12 success, 13 contact episodes
learned MLP + shield:  10/12 success,  0 contact episodes
```

The learned policy is not described as solved. Seven nominal scenarios still
time out. Zero contact in this finite test set also does not prove universal
safety.

## 13. Reward Versus Demonstration Loss

This model is trained by supervised imitation loss, not reinforcement learning.
The environment reward scores closed-loop behavior:

```text
reward = 7 * progress
       - 0.01 per step
       - 1.2 during contact
       - 0.012 * absolute turn command
       + 10 on arrival
```

Reward can compare trajectories, but it does not update this model. In RL, an
algorithm would use accumulated reward to update a policy without requiring an
expert action for every state.

Reward design can be exploited. For example, a badly designed progress reward
may encourage oscillation. Always inspect success, contacts, timeouts, and
trajectories separately rather than trusting one total score.

## 14. The Safety Shield

`SafetyShield` in `software/sim/mlp_policy.py` wraps the network proposal.

It uses only observable values. It can:

- Reverse and pivot after contact.
- Pivot instead of advancing when front clearance is low.
- Steer away from low side clearance.
- Reduce speed as front clearance shrinks.
- Latch a fault so one persistent fault does not restart a timer every cycle.

The data path is:

```text
observation -> MLP proposal -> deterministic shield -> delayed actuator command
```

The shield does not prove physical safety. Its thresholds depend on simulated
range inputs not present on the rover. The transferable design principle is to
separate performance optimization from constraints that must remain explicit,
testable, and fail-closed.

## 15. Domain Randomization

Every training/evaluation world varies parameters such as:

- Floor friction.
- Left and right drive gain.
- Turn gain and actuator feedback.
- Range noise, dropout, and latency.
- Command latency.
- Odometry scale and noise.
- Gyro scale, bias, and noise.

Randomization trains against a family of systems rather than one exact nominal
model. It helps only when the physical rover lies within a plausible training
distribution. Randomizing arbitrary values does not create realism.

A parameter distribution needs evidence:

```text
physical tests -> estimate range/distribution -> randomize inside it
```

Until measured, this repository labels values as assumptions.

## 16. Real2Sim

Real2Sim means using real measurements to improve simulator parameters.

The implemented turn workflow is:

```text
physical motor command + MPU samples
  -> identify yaw axis and stationary bias
  -> integrate angular rate into angle trace
  -> vary MuJoCo turn gains and velocity feedback
  -> minimize trace error
  -> freeze parameters
  -> replay a separate physical command sequence
```

The fitted parameters reduced RMSE across three held-out final-yaw endpoints
from `36.51` to `14.34 degrees`, a `60.7%` reduction. The validator does not
compare every trajectory sample. The remaining error is large enough
that the model must not be called fully calibrated.

Real2Sim is not reconstructing the room from a camera. It is system
identification: selecting model parameters that make simulated outputs better
match measured physical outputs under the same inputs.

## 17. Sim2Real

Sim2Real means deploying behavior developed in simulation and measuring it on
the physical system.

A valid transfer requires interface parity:

```text
same observation meanings and units
same action meanings and limits
same control frequency
same reset and safety semantics
```

The action interface is already aligned: normalized forward/turn commands. The
observation interface is not. The physical rover lacks metric obstacle ranges
and translational velocity. Therefore copying the `.npz` model to the Jetson
would execute code but would not constitute valid policy transfer.

The correct physical sequence is:

1. Add wheel encoders and a metric range or depth sensor.
2. Calibrate axes, units, timing, and frame transforms.
3. Record physical observations without allowing the policy to control motors.
4. Run the policy in shadow mode and inspect proposed actions.
5. Compare observation distributions against simulation.
6. Start wheels-up with bounded low-power actions.
7. Run controlled floor trials with the Pi watchdog active.
8. Retain failures and update randomization from measurements.

## 18. What the Policy Arena Shows

The `Policy arena` tab calls `/api/run-policy-arena` in
`software/sim/lab_server.py`.

The server:

1. Generates a deterministic held-out scenario.
2. Samples dynamics and sensor fidelity from a fixed seed.
3. Loads the selected expert or exact MLP artifact.
4. Steps the Gymnasium/MuJoCo environment until arrival or timeout.
5. Captures chase and onboard RGB frames.
6. Returns every observation, proposed action, delayed executed action, reward,
   estimated pose, truth pose, contacts, and model parameters.

The browser replays that record. Moving the timeline does not rerun physics; it
selects a prior evidence row and its nearest captured camera frame.

The `Mapping` tab runs a different policy stack. It demonstrates occupancy
mapping, frontier exploration, A*, target memory, and rendered target detection.
The `Policy arena` isolates learned reactive navigation. Keeping them separate
makes each claim inspectable.

## 19. Reproduce the Laptop Evidence

Create the environment:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-sim.txt
```

Train the contact-world policy:

```sh
PYTHONPATH=software/sim .venv/bin/python \
  software/sim/train_high_fidelity_policy.py
```

Evaluate expert and learned policies on the same held-out worlds:

```sh
PYTHONPATH=software/sim .venv/bin/python \
  software/sim/evaluate_high_fidelity_policy.py
```

Verify hashes, metrics, and claim boundaries:

```sh
PYTHONPATH=software/sim .venv/bin/python \
  software/sim/build_offline_evidence.py
```

Run the lab on macOS:

```sh
MUJOCO_GL=cgl PYTHONPATH=software/sim \
  .venv/bin/python software/sim/lab_server.py --port 8780
```

Open `http://127.0.0.1:8780/?view=sim`.

## 20. Practical Labs

### Lab A: Observe command latency

Set command latency in a small environment test. Apply a forward action and
inspect requested, applied, and executed actions. The requested action changes
first. The executed action changes only after the queue delay.

### Lab B: Create pose drift

In Mapping, change odometry scale from `0.97` to `1.10`. Prediction: estimated
path length grows relative to truth and final pose error increases.

### Lab C: Inject a stall

In Policy arena, enable actuator stall. Prediction: requested actions continue,
executed actions become zero during the fault, `stuck` becomes true, and the
safety shield enters a recovery mode after actuation returns.

### Lab D: Inspect a weight's effect

In Policy, move one observation slider while holding the others fixed. Record
output changes. The result is local sensitivity of the whole network, not the
meaning of one individual weight.

### Lab E: Compare controllers fairly

Run expert and learned policy with the same scenario ID and seed. Their world,
dynamics, fidelity, and initial state are identical. Differences then come from
controller decisions.

### Lab F: Prove a truth boundary

Read one arena trace row. `observation` contains nine values. `ground_truth`
appears beside it only in diagnostics. Tests assert truth is absent from the
policy input.

## 21. What Is Complete and What Is Not

Complete on the laptop:

- MuJoCo contact world with four-wheel actuation.
- Gymnasium environment.
- Imperfect range, speed, gyro, command timing, and pose estimation.
- Behavior cloning and DAgger training.
- Deterministic safety shield.
- Held-out policy and actuator-stall evaluation.
- Rendered chase and onboard policy replay.
- Occupancy mapping, frontiers, A*, and target memory simulation.
- Physical-IMU-to-MuJoCo directional yaw fitting and replay.
- Hash-bound evidence manifest and claim ledger.

Not complete without hardware:

- Physical metric translational odometry.
- Physical metric obstacle sensing.
- Physical learned-policy shadow mode and controlled transfer.
- Translation/friction/deadband/battery parameter identification.
- Mac-independent Pi-to-Jetson acceptance test.
- Physical mapping and localization benchmark.

## 22. Interview-Quality Explanation

A concise defensible description is:

> I wrapped a four-wheel MuJoCo contact model in a Gymnasium environment with
> delayed and noisy range, odometry, gyro, and command channels. I trained a
> 386-parameter policy by behavior cloning and DAgger, retained an observation-
> only deterministic safety shield, and compared it with the expert on the
> same seeded randomized worlds. The learned stack completed 33 of 40 held-out
> missions with zero contact episodes, versus 32 of 40 and 36 contacts for the
> expert. I separately fitted directional yaw dynamics from physical MPU logs,
> reducing three held-out final-yaw endpoints' RMSE by 60.7%. Physical policy transfer is
> deliberately pending because the rover lacks the metric range and wheel-speed
> observations used in simulation.

## 23. Teach-Back Questions

September 8 audit: the original policy comparison added a safety filter only to
the learned side. A fresh four-way comparison shows this filter contributes
strongly to avoiding contacts. Also, contact/stuck observation flags include
ideal simulator state; the nine-input vector is not wholly hardware-equivalent.
Use [the practical course](rover-practical-course.md) for the measured ablation,
the corrected evidence boundary, and executable teaching exercises.

1. Why is MuJoCo truth allowed for reward but forbidden in policy observations?
2. What does a `100 ms` sensor delay physically mean while the rover moves?
3. Why can validation MSE improve while closed-loop success becomes worse?
4. What problem does DAgger solve that behavior cloning alone does not?
5. Why does domain randomization need physically plausible ranges?
6. What exactly changed during the Real2Sim yaw fit?
7. Why is a model copied to the Jetson not automatically a Sim2Real result?
8. What new measurements would make physical transfer defensible?

## 24. Primary Learning Resources

- MuJoCo documentation: <https://mujoco.readthedocs.io/>
- Gymnasium custom environments: <https://gymnasium.farama.org/introduction/create_custom_env/>
- MIT Underactuated Robotics: <https://underactuated.csail.mit.edu/>
- Modern Robotics course and text: <https://modernrobotics.northwestern.edu/>
- Isaac Lab domain randomization concepts: <https://isaac-sim.github.io/IsaacLab/main/source/features/domain_randomization.html>

Use these resources to deepen the mechanisms implemented here. Do not replace
the repository's measured claim boundaries with generic framework terminology.
