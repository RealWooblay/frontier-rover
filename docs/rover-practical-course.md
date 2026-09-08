# Understand, Demonstrate, and Defend Frontier Rover

This is the starting point for the 8 September portfolio session and the
learning work to take overseas. It replaces neither the code nor the older
[long-form course](simulation-and-sim2real-course.md): it gives you an ordered
path through them, with experiments you can run and explain.

Today's achievable outcome is a truthful demonstration and a reproducible
engineering case study. Becoming an expert takes repeated prediction, measurement,
debugging, and explanation. Reading every page today is not the success criterion.

## 1. The System You Actually Built

There are three experiments, not one giant autonomous brain:

| Experiment | Input -> computation -> output | Current boundary |
| --- | --- | --- |
| Physical target approach | Camera image -> Jetson detector -> target controller -> Pi -> motor drivers | A controlled-floor target approach, not house-wide navigation |
| Real2Sim identification | Recorded motor commands and gyro samples -> fit a MuJoCo actuator model | Directional turning calibration, not a scanned room or a complete digital twin |
| Simulated navigation | Simulated range/motion observations -> baseline or learned policy -> simulated motors | Learned policy has not been accepted driving the physical rover |

The neural network that detects an orange and the small neural network that
drives in the simulated arena are DIFFERENT models. Neither is automatically
learning while the physical rover drives.

Physical data flow:

```text
Light -> camera sensor -> Pi camera software -> JPEG over HTTP
  -> Jetson decodes image -> TensorRT detector -> numerical bounding box
  -> controller chooses forward/turn or a relative-heading operation
  -> HTTP command -> Pi command validation and watchdog
  -> GPIO direction + PWM -> TB6612 switches motor battery -> wheel torque
  -> rover moves -> next camera frame and MPU gyro measurement
```

The Mac currently hosts the lab and an SSH tunnel used by the Jetson to reach
the Pi. Wi-Fi is a network link; SSH is an authenticated connection over that
link; an SSH tunnel forwards another service's traffic. They are not synonyms.
Your browser does not generate wheel voltages. It sends requests to the Pi's
Python server. The Pi continues running its own service when a browser closes,
but motion commands must expire when their sender stops refreshing them.

The Pi needs its own power, now supplied by your working-again Belkin. The
motor battery supplies motor current. The Jetson uses its own suitable power
adapter. Two motor drivers distribute power; GPIO carries control signals, not
the current that turns the wheels. Do not change wiring during this demo.

Source: `software/jetson/tensorrt_yolo.py`, `autonomy_service.py`,
`mission_runtime.py`, and `software/pi/remote_control.py`.

## 2. First Lab: A Picture Becomes a Motor Command

### What the detector computes

A camera frame is already a picture. The neural network does not translate
frames into pictures: it translates pixel values into predicted object classes
and locations. A convolution applies the same learned filter at many image
positions. A filter multiplies nearby pixel/feature values by weights and adds
them; successive layers combine local patterns into more useful features.
Those features need not have tidy human names.

A detection head turns the final features into numerical box locations and
class scores. The drawing code uses those coordinates to draw a rectangle;
drawing is not the recognition step. During detector training, labeled boxes
provide targets for location and class losses. Their gradients adjust the
filters AND detection head. Our physical detector uses pretrained YOLOv8
weights compiled for TensorRT; collecting lemon labels did not by itself train
or deploy a new lemon detector.

Our preprocessing rotates the camera image, resizes while preserving aspect
ratio, adds padding, changes BGR to RGB, and scales channels to 0..1. The decoder
maps predicted boxes back by undoing padding and scale. Forget that inverse
transform and a plausible detection can command a turn in the wrong direction.
Overlapping candidates are reduced with non-maximum suppression: keep a strong
box and discard sufficiently overlapping alternatives. A confidence score is
a model score, not a guaranteed, calibrated probability of being correct.

There is also a color-based fallback when YOLO finds no target. It thresholds
HSV color channels and filters regions by shape/size. That is classical image
processing, not another trained detector. A run must identify whether the box
came from `yolo` or `hsv`; a color fallback can mistake other orange objects for
the mandarin. The mapping simulator also uses an HSV detector on rendered RGB,
not the physical YOLO model.

### Work one example all the way through

Suppose a 640 x 360 image contains a box `(440,180)-(520,260)`:

```text
center_x = (440 + 520) / 2 = 480 pixels
horizontal_error = (480 - 320) / 320 = +0.5
area_ratio = (80 * 80) / (640 * 360) = 0.027778
bottom_edge_ratio = 260 / 360 = 0.722222
```

`+0.5` means halfway from image center to the right edge. It is NOT 0.5 degrees,
not a neural weight, and not a measured position in the room. The controller
uses it as a visual alignment error. With the checked-in runtime defaults this
example requests an alignment pulse: forward `0`, right-turn `0.3`, for `35 ms`.

The Pi mixes forward and turn, then applies motor calibration:

```python
left = forward + turn
right = forward - turn
scale = max(1.0, abs(left), abs(right))
left_pwm = left / scale * left_calibration
right_pwm = right / scale * right_calibration
```

Assuming calibration `0.8` left and `1.0` right, the result is `+0.24, -0.30`.
The sign selects rotation direction; the magnitude is PWM duty fraction. PWM
rapidly switches power on and off. It is not a measured wheel speed: friction,
load, battery voltage, motor variation and contact with the floor change speed
for the same duty. At low duty a motor may stall, explaining why minimum drive
effort exists and why a mathematically small turn can still be abrupt.

### Run and predict

These commands contact NO hardware and use actual project functions. Their
boxes are classroom inputs, not new detections. Runtime defaults and explicitly
supplied calibration are not a claim about today's live Pi settings.

```bash
cd /Users/jackcoleman/Developer/frontier-rover
.venv/bin/python software/learning/rover_workshop.py vision
.venv/bin/python software/learning/rover_workshop.py vision --box 280 180 360 260
.venv/bin/python software/learning/rover_workshop.py vision --box 270 250 370 350
.venv/bin/python software/learning/rover_workshop.py vision --frame-age-ms 1000
.venv/bin/python software/learning/rover_workshop.py vision --lost
```

Before each run, predict align, approach, arrive, stop, or search. The centered
box should command forward motion; the lower, larger box should trigger arrival;
the stale frame should stop. Missing target requests a gyro-controlled heading
turn, so the exercise reports no single fixed PWM for that operation.

Why it can still overshoot: a frame shows the past, recognition can blink out,
the rover coasts after power changes, and a close object can leave the bottom
of the image. The controller needs fresh observations, target memory and
arrival latching. A lost image alone cannot distinguish 'under the camera',
'behind an obstacle' and 'never present'. Those need different evidence, not
just a more confident neural network.

Area is a proximity heuristic, not a distance sensor. With a calibrated focal
length `f` and a known object width `D`, a simplified front-facing estimate is
`distance ~= f * D / image_width`. Without those assumptions, pixel size does
not uniquely determine distance. Similarly, bearing can be estimated as
`atan((center_x-cx)/fx)` after calibration; our normalized error is not that
calibrated bearing calculation.

**Explain back:** Where did `0.5` come from, and why can two wheels receiving
60% duty turn at different speeds?

**Read next:** [CS231n convolutional networks](https://cs231n.github.io/convolutional-networks/),
starting with local connectivity and shared weights; then
[YOLOv8 detection documentation](https://docs.ultralytics.com/models/yolov8/) and
[OpenCV camera calibration](https://docs.opencv.org/4.13.0/dc/dbb/tutorial_py_calibration.html).
Tie each reading to preprocessing, output coordinates, or a measured failure.

## 3. Second Lab: Watch a Weight Change

### One weight, with arithmetic

Take an intentionally tiny teaching model `prediction = weight * input`.
If input is `0.5`, desired output is `0.3`, and weight is `0.2`:

```text
prediction = 0.2 * 0.5 = 0.1
loss = (prediction - desired)^2 = (0.1 - 0.3)^2 = 0.04
loss slope with respect to weight = 2*(0.1 - 0.3)*0.5 = -0.2
new weight = old weight - learning_rate * slope
           = 0.2 - 0.1*(-0.2) = 0.22
new prediction = 0.11; new loss = 0.0361
```

The slope says how sensitively the error changes when that particular weight
changes. Subtracting the slope moves downhill for a sufficiently small step.
Backpropagation computes these slopes efficiently through every layer using
the chain rule. It is not a random guessing loop. An optimizer uses the slopes
to choose updates; our training uses Adam, which tracks moving averages of
gradients and squared gradients. Our one-step lesson uses simpler SGD so that
the arithmetic is directly visible.

### Use the ACTUAL saved navigation network

Our arena model has nine numbers in, 32 hidden activations, and two numbers
out. It is not an image model. A hidden activation is:

```python
hidden = tanh(observation @ W1 + b1)
output = tanh(hidden @ W2 + b2)
```

`W1` has 9 x 32 weights, `b1` has 32 biases, `W2` has 32 x 2 weights and `b2`
has 2 biases: 386 learned parameters total. A bias is an additive offset.
The same input generally produces the same output with fixed weights. Memory
in the safety/recovery wrapper is separate from this feed-forward network.

The nine inputs are normalized goal distance, goal bearing error, front/left/
right clearance, forward velocity, yaw rate, contact flag and stuck flag.
They are measurements or estimates defined by the environment, not numbers
invented by the training software. The outputs are normalized forward and turn
requests. Bounds and a safety filter are applied after prediction.

```bash
.venv/bin/python software/learning/rover_workshop.py gradient
```

On the saved model and the classroom input, this experiment reports:

| Quantity | Before | After one small step |
| --- | ---: | ---: |
| Selected weight `W1[3,16]` | 0.82832645 | 0.82838239 |
| Predicted forward | 0.09659415 | 0.09623940 |
| Predicted turn | 0.07792469 | 0.07961909 |
| Weighted example loss | 0.00331952 | 0.00314818 |

The baseline's label here is `(0.05, 0.1375)`. Both predictions move closer to
that label. The selected weight connects input 3, left clearance, to hidden
unit 16. Its meaning is distributed through other weights; it is not a named
'turn left' switch. The step updates all parameters in memory and displays one.

The calculated derivative is approximately `-0.05593739`. The script also
nudges that weight up and down by `0.00001`, measures the change in loss and
checks that this numerical slope matches backpropagation. It verifies that the
saved model file is unchanged. This is a gradient check, a useful debugging
technique when implementing a learning algorithm.

Source: `software/sim/mlp_policy.py::TinyMLP.fit` and
`software/learning/rover_workshop.py::gradient`.

**Explain back:** Why did subtracting a negative gradient increase the weight?
Why does lower training loss not prove the rover will navigate safely?

**Read next:** [CS231n backpropagation](https://cs231n.github.io/optimization-2/).
Work through its computational-graph example, then match each derivative to
`d_output`, `d_z2`, and `d_z1` in our workshop. The lesson concerns mechanics,
not a claim that this small model rivals a general-purpose vision model.

## 4. Third Lab: What Is Physically Simulated?

### Physics is a prediction, not a recording

MuJoCo maintains positions and velocities of bodies and joints. At each small
time step it calculates acceleration from applied forces, gravity, mass,
inertia and contacts, then integrates forward. In compact notation:

```text
M(q) * acceleration + C(q, velocity) = applied_force + contact_force
```

`q` describes configuration; `M` describes resistance to acceleration from
mass/inertia; `C` collects gravity and velocity-dependent effects. The solver
handles wheel-floor and obstacle contact constraints. The displayed rover is
rendered from this evolving state, rather than moved along a pre-drawn path.

Our actuator approximates drive force and speed-dependent resistance. It is
not a complete electrical motor, gearbox, tire and battery model. Mass, friction,
actuator strength, damping, latency and noise can be represented, but a parameter
in a file is not proof it was measured accurately on our chassis.

The model is useful for a question such as 'Does this policy collide more when
range readings arrive 100 ms late?' It is not evidence that your actual room
has these walls, that your actual motors produce this acceleration, or that a
policy works on sensors you do not own.

### State, observation, action, score

| Name | Concrete example | Who sees it? |
| --- | --- | --- |
| True state | Simulated x/y position and actual heading | Physics and evaluation |
| Observation | Delayed range clearance and biased yaw estimate | Policy input |
| Action | Forward 0.3, turn -0.1 | Actuator interface |
| Reward | Progress bonus minus contact/time penalties | Environment score; not used to train our imitation model |

Gymnasium supplies the `reset()` and `step(action)` contract around the physics.
It is the experiment interface, not the physics engine or the learning method.
One policy decision spans multiple physics time steps. Command delay can make
the requested action differ from the action currently applied to the motors.

Important audit: our nine-input policy does not directly receive x/y truth,
but its contact flag comes from ideal simulator contacts and its stuck flag
uses actual movement/injected-fault state. These are idealized sensor inputs.
Initial pose and goal coordinates are known in the arena. We must build and
validate physical equivalents before claiming input parity or physical transfer.

### Use the visual lab as an instrument

Open [the policy arena](http://127.0.0.1:8780/?view=sim). Run the same seed
with the baseline and learned policy. Observe the camera render, action, elapsed
time and contacts. Success with contact is not contact-free success.

Then use Mapping. Change one of the existing odometry/gyro settings, rerun the
same scenario, and predict whether estimated pose will drift away from truth.
That gap is estimation error, not a rendering bug. Do not describe a simulated
sensor's clean output as a real sensor measurement.

Source: `software/sim/mujoco_rover.py`, `high_fidelity_env.py`,
`simulation/mujoco/`, and `software/shared/grid_mapping.py`.

**Explain back:** Why does adding noise improve an experiment's usefulness
without making the simulator a verified replica of our rover?

**Read next:** [MuJoCo computation](https://mujoco.readthedocs.io/en/stable/computation/index.html),
focusing first on state, force and integration; and
[Gymnasium environment design](https://gymnasium.farama.org/introduction/create_custom_env/).
Trace one of our `env.step()` calls before learning another framework.

## 5. Fourth Lab: Real2Sim Is an Identification Experiment

We logged motor commands and gyro rates from the physical rover, then replayed
those commands in MuJoCo. Fitting searches for parameters that reduce the
difference between measured and simulated yaw. This is system identification.
It does not reconstruct the room; that would be a different reconstruction task.

The MPU contains microscopic moving structures. An accelerometer senses forces
through their displacement; gravity contributes to the stationary reading. A
gyroscope drives a microscopic structure to vibrate and measures rotation-related
Coriolis deflection. Electronics digitize those signals; the Pi reads registers
over I2C. The gyro measures angular rate, not position directly.

For a physical explanation with sensor diagrams, see
[Analog Devices on accelerometer and gyroscope operation](https://www.analog.com/en/resources/technical-articles/accelerometer-and-gyroscopes-sensors-operation-sensing-and-applications.html).
This explains the MEMS sensing principle, not a claim that our MPU uses that
manufacturer's exact circuit implementation.

Our fixed vertical mounting uses sensor Y as yaw. Mounting orientation determines
which sensor axis corresponds to a turn of the chassis. If the sensor wobbles,
it records its own movement as well as the rover's. The board must be rigidly
attached, not necessarily flat.

```text
yaw_increment_degrees = (gyro_y_degrees_per_second - stationary_bias) * dt_seconds
yaw = previous_yaw + yaw_increment
```

An uncorrected bias of 1 degree/second accumulates 60 degrees in a minute.
Gyro integration can guide a short relative turn but is not permanent absolute
heading. It also cannot tell us reliable traveled distance by itself. Double
integrating accelerometer readings magnifies bias and gravity-estimation error.

### What our result ACTUALLY says

The fit used physical motion data to tune left gain, right gain and velocity
feedback. Validation used three separate physical turns not used in that fit.
The validator compares their final yaw endpoints, not every trajectory sample:

| Turn | Measured yaw | Fitted simulated yaw | Fitted minus measured |
| --- | ---: | ---: | ---: |
| 1 | +60.334 deg | +59.274 deg | -1.060 deg |
| 2 | -117.976 deg | -141.333 deg | -23.357 deg |
| 3 | +59.243 deg | +50.850 deg | -8.393 deg |

`RMSE = sqrt(mean(error^2))`. Across these THREE endpoints, error fell from
36.51 to 14.34 degrees: a 60.7% relative reduction. That is not 60.7% improvement
in every aspect of the robot, nor proof of an accurate full trajectory. The
largest remaining endpoint error is about 23.36 degrees. Earlier wording
describing this result as full trajectory RMSE was too broad.

The gyro is the reference used here, not an independent motion-capture system.
Good agreement can still contain shared sensor bias. Three similar maneuvers
provide narrow evidence. Broader validation would include different surfaces,
loads, battery states, directions, speeds and independent angle measurements.

Open the Real2Sim tab. Explain fitted versus original prediction and point to
one residual error rather than only announcing the percentage. Sources:
`artifacts/physical/2026-09-06-imu-motion.csv`,
`artifacts/sim/2026-09-06-closed-loop-turn-validation.json`, and
`software/sim/validate_closed_loop_turn.py`.

**Explain back:** Why can a fitted model be better and still be inadequate for
precise navigation? What measurement would detect gyro bias shared by both sides?

**Read next:** [MIT system identification](https://underactuated.mit.edu/sysid.html).
Focus on excitation, fitting a model from data, and validating predictions on
new experiments. Relate each idea to the narrow set of turns we measured.

## 6. Fifth Lab: Training, Safety, and Sim2Real Are Different

Behavior cloning treats a controller's decisions as supervised labels:
`observation -> expert forward/turn`. 'Expert' here means our rule-based baseline,
not a human professional or a perfect planner. Training minimizes disagreement
with its labels. A poor teacher can teach poor behavior.

DAgger adds examples from states the learned policy actually visits. We run the
learner, ask what the baseline would do in those states, append those examples,
and train again. This addresses distribution shift: small mistakes take the
learner into situations absent from clean demonstrations. Two such rounds are
recorded for our model. This is not reinforcement learning; the simulator's
reward was not the optimization objective for this training.

The policy then runs through a stateful safety filter. It can slow, reverse or
pivot based on clearance/contact/stuck observations. Our previous 40-world
report compared baseline alone with learned policy PLUS this filter. Therefore
33/40 successes and zero contact events cannot be attributed to the neural
network alone. Also, the benchmark informed development; do not retrospectively
call it a never-seen, blind final test.

### Measure the missing comparison

The workshop runs four conditions on fresh, identically configured worlds:

1. The baseline controller alone.
2. The baseline with the safety filter.
3. The bounded neural output alone.
4. The bounded neural output with the safety filter.

```bash
.venv/bin/python software/learning/rover_workshop.py compare \
  --episodes 12 --seed 260908 \
  --output /private/tmp/frontier-controller-ablation.json
```

The saved run for this date is
`artifacts/sim/2026-09-08-controller-ablation.json`. Preserve it; choose a new
output filename to repeat. The script refuses to overwrite evidence or retrain
the model. A seed fixes world generation so results can be reproduced, not
so that different actions experience identical sensor histories.

Measured result, seed 260908, 12 worlds per condition, fixed saved model:

| Controller | Reached goal | Contact events | Missions with contact |
| --- | ---: | ---: | ---: |
| Baseline | 12/12 | 10 | 5 |
| Baseline + filter | 10/12 | 0 | 0 |
| Bounded neural policy | 10/12 | 48 | 5 |
| Bounded neural policy + filter | 11/12 | 0 | 0 |

This is a useful result precisely because it is not a simple AI victory. The
baseline reaches every goal but makes contact. The neural policy alone also
makes contact. Adding the filter removes observed contacts in both families,
with a completion tradeoff. One contact event is a transition into contact,
not necessarily a new obstacle hit; repeated contact can raise the count.
The 11 versus 10 successes with filters is too small a sample to claim robust
superiority. No tuning was performed on this new comparison.

Compare success AND contact counts. Within each family the on/off comparison
tests the filter's effect. Baseline and neural outputs have different limits,
so their comparison is still not a pure neural-architecture experiment. Twelve
scenarios are a small check, not a reliability guarantee or statistical proof.

Physical Sim2Real would additionally require producing the same nine input
quantities on the rover, preserving units/signs/timing, checking prediction
without motion, then testing bounded physical behavior. Loading a model onto a
Jetson and running inference proves execution compatibility, not physical transfer.
Our rover does not yet supply the arena's metric clearance/velocity observations.

**Explain back:** If adding the filter improves both controllers, why is 'AI
learned to avoid all collisions' an unsupported summary?

**Read next:** [The original DAgger paper](https://proceedings.mlr.press/v15/ross11a.html).
Compare its data-collection loop with `collect_demonstrations()` in
`software/sim/train_high_fidelity_policy.py`; do not start by memorizing the title.

## 7. Mapping Is Not Automatically SLAM

In the simulated mapping experiment, geometry rays act as virtual range sensors.
Each ray marks cells along its path as probably free and its hit cell as probably
occupied. Repeated observations accumulate evidence in a grid. The rover's
estimated position determines where those observations are placed on the map.

A frontier is the boundary between known free space and unknown space. The
planner chooses a reachable frontier and A* finds a route through the current
free-cell map. A local controller follows it and checks for the target. This
is a classical exploration pipeline, not the small neural arena policy.

Our pose estimate integrates motion observations: dead reckoning. Drift can
place a wall in the wrong cells. True SLAM would jointly estimate pose and map,
including constraints from revisiting known places. Our present mapping demo
does not implement that correction. ORB/RANSAC image-motion work on the physical
camera measures pixel motion, not metric room position.

Consequently you can hide the simulated target behind simulated obstacles.
You cannot yet hide a mandarin anywhere in a house and claim the physical rover
will search reliably. No amount of UI polish supplies missing physical range,
localization, collision sensing, or validated exploration behavior.

## 8. Build a Credible Demo Today

Use the [demo runbook](portfolio-demo-runbook.md). Keep a camera shot of the real
rover distinct from screen recordings of simulation. Retain failed runs too.
Do not edit a simulated success into footage implying it happened physically.

Record four short chapters: hardware/control, live perception and bounded
approach, measured Real2Sim fitting, and simulated policy/mapping evaluation.
Show one failure and its explanation. A technically honest limitation is more
credible than saying 'fully autonomous' without acceptance evidence.

The day's finish line is a reproducible artifact, measurements, source links,
and your ability to explain a complete command path. Whole-house autonomy,
physical learned-policy transfer and a validated full digital twin are not
secretly complete. They remain clearly scoped future experiments.

## 9. Your Travel Learning Plan

Keep the laptop, Jetson, compatible camera/cable, storage and suitable power
with you if you want continued edge deployment work. The laptop can run this
small MuJoCo environment, analyze data and train the tiny policy. The Jetson
adds ARM/Linux and NVIDIA GPU deployment constraints: memory transfers,
precision, thermals and latency under load. It is not required to understand
simulation. The Pi is useful for hardware I/O or keeping the rover intact at
home; without an actuator project abroad it is optional. Do not desolder the
MPU merely to make a learning kit.

| Week | Three practical sessions | Evidence you produce |
| --- | --- | --- |
| 1: Vision | Trace preprocessing; annotate a fresh positive/negative image set; evaluate boxes and runtime | Failure gallery, precision/recall at stated thresholds, latency distribution |
| 2: Dynamics | Reproduce the yaw fit; inspect residuals per turn; perturb a parameter and predict its effect | Fit/validation plot, assumptions, independent test proposal |
| 3: Learning | Reproduce the gradient check; collect demonstrations in a separate output location; compare baseline/MLP with matched safety | Learning curves and a fixed-seed ablation report |
| 4: Systems | Trace timing boundaries; replay delayed/dropout inputs; package a reproducible demo and explain its limits aloud | Architecture drawing, failure test, five-minute portfolio presentation |

For vision evaluation, a ground-truth box is your human annotation, not the
detector's own output. Use separate capture sessions for evaluation so nearly
identical adjacent frames do not leak across training and evaluation. Include
images with no target and confusing objects. Match predicted/annotated boxes
with a stated intersection-over-union threshold (for example 0.5). Precision
asks what fraction of predicted targets were correct; recall asks what fraction
of actual targets were found. Detection quality is separate from driving safety.

For deployment timing, warm up the engine, record many calls and report median
and p95 rather than only a best case. Our `inference_ms` includes host/device
copies and synchronization around execution; it is not a pure GPU-kernel time.
Frame acquisition, network transfer and command transport add further delay.
Cold-start overhead is not evidence that every CPU/GPU transfer is slower.
Read [TensorRT performance practices](https://docs.nvidia.com/deeplearning/tensorrt/10.x.x/performance/best-practices.html)
alongside our actual timing boundaries before quoting a speedup.

Learn C++ by porting one tested, pure component such as box geometry or motor
mixing and matching Python test vectors. Later apply it to a measured timing
need. Learn ROS 2 when you can map nodes/messages/transforms onto these existing
boundaries. Adding either name to the repo without an engineering purpose does
not make the portfolio stronger.

## 10. Notes That Build Understanding

Use paper for a system drawing and a worked equation; keep durable notes,
commands, plots and evidence in the repository. For each experiment write:

```text
Question:
My prediction and why:
Input, units and exact code path:
What I changed (one variable):
Measured output and artifact:
Why the result agrees/disagrees:
What this does NOT prove:
My explanation without looking at the notes:
```

You are ready to discuss this project when you can trace a frame into a wheel
command, calculate a gradient step, explain a simulator assumption and residual,
separate model performance from its safety wrapper, and name the missing
observations that prevent physical transfer. That is a concrete competency
target, not a claim of expertise from having run a notebook once.
