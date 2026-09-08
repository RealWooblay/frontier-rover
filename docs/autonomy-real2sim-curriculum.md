# Autonomy and Real2Sim Curriculum

This curriculum turns the Frontier Rover into a working autonomy project and a
technical apprenticeship. Each module must produce four things:

1. A plain-language explanation of the mechanism.
2. A runnable experiment.
3. Recorded measurements or tests.
4. A teach-back that explains what failed and what the evidence proves.

The objective is not merely to make the rover move. The objective is to be able
to defend the architecture, mathematics, measurements, and limitations to a
robotics engineer.

## The Complete System

```text
real or simulated world
        |
        v
camera and IMU observations
        |
        v
perception and state estimation
        |
        v
controller or learned policy
        |
        v
bounded forward/turn action
        |
        v
Pi safety controller -> motor drivers -> wheels
        |
        +-------------------- changes the world
```

The same observation and action definitions must be used in reality and in
simulation. This shared interface is the foundation of the Real2Sim work.

```text
Observation
  timestamp
  target_visible
  target_track_id
  horizontal_error
  apparent_target_size
  detector_confidence
  yaw_rate

Action
  forward   in [-1, +1]
  turn      in [-1, +1]

State used by the simulator
  x position
  y position
  heading
  forward velocity
  angular velocity
```

## The Five Different Kinds of Model

The word "model" is overloaded. Always identify which model is being discussed.

1. **Perception model:** image -> object boxes, classes, and confidence.
   YOLO is this kind of model.
2. **Tracking model or algorithm:** detections over time -> persistent object
   identity and estimated motion.
3. **Sensor model:** simulated world state -> simulated camera or IMU reading.
4. **Dynamics model:** current state plus motor action -> next rover state.
   MuJoCo implements this kind of model.
5. **Policy model:** observation -> action. A neural driving policy is this
   kind of model.

A deterministic controller is not necessarily a neural model. It may simply be
tested equations and state transitions.

## Module 1: Numbers, Signals, and Weight Updates

### Question

How can changing one stored number make a prediction more accurate?

### Concepts

- Input, target, prediction, error, and loss.
- A weight as a multiplier applied to an input signal.
- A gradient as the local slope of loss with respect to a weight.
- Learning rate as the fraction of the gradient used for an update.
- Training, validation, and inference as different execution modes.

For the one-weight rover example:

```text
prediction = weight * pwm_command
error = prediction - measured_turn_rate
loss = mean(error squared)
gradient = change in loss / change in weight
weight = weight - learning_rate * gradient
```

For a neural network, the same operation is applied to many weights connected
through many layers. Backpropagation applies the chain rule to calculate how
each weight contributed to the final loss.

### Practical lab

Run:

```sh
python3 software/learning/one_weight_training.py
python3 software/learning/one_weight_training.py --learning-rate 0.05
python3 software/learning/one_weight_training.py --learning-rate 3
```

Then add a mode that prints one real CNN parameter before the update, its
gradient, and its value after `optimizer.step()`.

### Pass condition

Explain why a negative gradient causes the example weight to increase, why a
large learning rate diverges, and why validation data must not update weights.

### Resources

- PyTorch Learn the Basics:
  <https://docs.pytorch.org/tutorials/beginner/basics/intro.html>
- PyTorch Autograd:
  <https://docs.pytorch.org/tutorials/beginner/basics/autogradqs_tutorial.html>

## Module 2: Images and Neural Perception

### Question

How does a camera image become object boxes and confidence scores?

### Concepts

- An image as a height x width x channels array.
- Pixel normalization and tensor shapes.
- Convolution weights, feature maps, activations, and receptive fields.
- Classification versus detection versus segmentation.
- Bounding boxes, intersection-over-union, confidence, and non-maximum
  suppression.
- Pretraining, fine-tuning, and training from scratch.
- Precision, recall, mAP, latency, and throughput.

The selected-object system starts with a pretrained detector. Pretraining means
another training process has already adjusted the weights using a large labelled
dataset. We initially perform inference only.

### Practical lab

1. Run a small pretrained YOLO detector on saved images.
2. Print every output tensor and decode one box manually.
3. Run it on the Pi camera stream.
4. Save detection confidence, class, box coordinates, and latency.
5. Export the detector to TensorRT and compare outputs and timing.

### Pass condition

Explain what the detector was trained to predict, what a confidence score does
and does not prove, and why TensorRT changes execution without retraining the
weights.

### Resources

- Stanford CS231n:
  <https://cs231n.stanford.edu/2025/>
- Ultralytics Jetson guide:
  <https://docs.ultralytics.com/guides/nvidia-jetson>
- TensorRT first engine:
  <https://docs.nvidia.com/deeplearning/tensorrt/latest/getting-started/build-your-first-engine.html>

## Module 3: Object Selection and Tracking

### Question

How does the rover continue following the same object instead of choosing a new
detection every frame?

### Concepts

- Detection is frame-local; tracking connects detections across time.
- Track identity, association, intersection-over-union, and motion prediction.
- Occlusion, lost targets, reacquisition, and identity switches.
- Click-to-select as an operator prompt.
- Detector-based tracking versus promptable segmentation such as SAM 2.

### Practical lab

1. Draw live YOLO boxes in the operator UI.
2. Click a box and store its track ID.
3. Log the selected track through movement and brief occlusion.
4. Measure identity switches and lost-target duration.
5. Add SAM 2 later for click-any-object segmentation if Jetson performance is
   acceptable.

### Pass condition

Demonstrate that detection and tracking are different operations and explain
what the rover does when the selected track disappears.

## Module 4: Feedback Control and Safety

### Question

How does an object position become stable physical motion?

### Concepts

- Open-loop versus closed-loop control.
- Observation, reference, error, action, and feedback.
- Proportional gain, saturation, deadband, delay, and oscillation.
- Differential or skid-steer kinematics.
- State machines and safety invariants.
- Watchdogs, manual arming, emergency stop, and stale-data rejection.

The first controller is deterministic:

```text
turn = turn_gain * horizontal_error
forward = speed selected by controller state
```

The Pi owns motor calibration, output limits, and the watchdog. The Jetson never
receives direct GPIO authority.

### Practical lab

1. Feed synthetic object positions into the controller.
2. Print state transitions and proposed actions without moving motors.
3. Replay recorded detections.
4. Test wheels raised.
5. Test on the floor at bounded speed.
6. Deliberately stop frames or commands and prove the Pi stops the rover.

### Pass condition

Explain why too much gain oscillates, why delay reduces stability margin, and
why a watchdog belongs on the Pi rather than the Jetson.

### Resource

- MIT Underactuated Robotics:
  <https://underactuated.mit.edu/>

## Module 5: IMU Measurement and State Estimation

### Question

What is the rover actually doing between camera frames?

### Concepts

- Accelerometer specific force, gyroscope angular velocity, and magnetometer
  magnetic field.
- Sensor bias, noise, scale error, sampling rate, and drift.
- Coordinate frames and unit conversions.
- Integration and why small errors accumulate.
- Filtering and sensor fusion.
- Monotonic timestamps and synchronized logs.

### Practical lab

1. Detect the MPU-9250 on I2C.
2. Log the stationary sensor and estimate mean bias and standard deviation.
3. Rotate the rover through a measured angle and integrate gyro rate.
4. Record motor command, camera frame, detection, and IMU data together.
5. Compare camera-derived turning with gyro-derived turning.

### Pass condition

Explain why an IMU measures motion but does not provide reliable long-term
position by itself.

## Module 6: System Identification

### Question

How do real input-output measurements become a dynamics model?

### Concepts

- Excitation experiments and repeatability.
- Parameters versus states.
- Static motor gain, deadband, first-order response, time delay, and slip.
- Least-squares parameter fitting.
- Train/validation experiments for physical models.
- Identifiability: different parameters can sometimes produce similar outputs.

Example:

```text
real trajectory = run physical rover with recorded action sequence
sim trajectory = run simulator with the same actions and candidate parameters
loss = mean squared difference between real and simulated trajectories
optimizer changes motor gain, delay, friction, and slip parameters
```

This resembles neural-network training, but the parameters have physical
meanings and there are far fewer of them.

### Practical lab

Run repeated straight, in-place-turn, and curved PWM step tests. Fit parameters
on some runs and validate them on different runs.

### Pass condition

Explain which parameters were measured directly, which were fitted, how the
loss was defined, and whether the parameters generalize to held-out runs.

## Module 7: MuJoCo Digital Twin

### Question

How do we reproduce the rover's geometry, contacts, actuators, and sensors in a
physics simulator?

### Concepts

- Bodies, joints, actuators, contacts, friction, mass, inertia, and timestep.
- Numerical integration and solver stability.
- Sensor models and observation noise.
- Determinism and seeded experiments.
- Interface parity between simulation and reality.

### Practical lab

1. Create the chassis and four wheels in MJCF.
2. Apply left/right motor actions.
3. Add simulated gyro and accelerometer observations.
4. Run the real deterministic controller unchanged in simulation.
5. Replay real action logs in MuJoCo.

### Pass condition

Explain every important MJCF parameter, the simulation timestep, and where the
simulator intentionally simplifies the physical rover.

### Resource

- Official MuJoCo project and tutorials:
  <https://github.com/google-deepmind/mujoco>

## Module 8: Real2Sim Calibration

### Question

How close is the simulator to the physical rover, and what evidence supports
that claim?

### Concepts

- Reality gap and model mismatch.
- Calibration objective functions.
- Trajectory alignment and comparable coordinate frames.
- Parameter optimization and held-out validation.
- Sensitivity analysis and uncertainty.

### Practical lab

1. Replay identical action sequences in reality and MuJoCo.
2. Compare distance, heading, yaw rate, response delay, and stopping distance.
3. Fit simulator parameters on calibration runs.
4. Evaluate untouched validation runs.
5. Produce before/after plots and an error table.

### Pass condition

Report trajectory RMSE and heading error before and after calibration without
claiming that a visually similar animation proves physical accuracy.

## Module 9: Sim2Real and Learned Policies

### Question

Can a controller learned from simulated experience work safely on the rover?

### Concepts

- Markov decision process: observation, action, transition, reward, episode.
- Policy and value function.
- Imitation learning versus reinforcement learning.
- Reward design and reward hacking.
- Domain randomization over friction, motor gain, mass, delay, and sensor noise.
- Evaluation seeds and held-out scenario distributions.
- Safety filters and fallback deterministic controllers.

### Practical lab

1. Wrap MuJoCo with a Gymnasium-compatible environment.
2. First run the deterministic controller as the baseline.
3. Train a small policy for target approach.
4. Test it on unseen randomized environments.
5. Export the policy to ONNX or TensorRT.
6. Deploy behind the Pi's limits, arming, watchdog, and emergency stop.

### Pass condition

Compare the policy against the deterministic baseline, show failure cases, and
explain why simulation reward alone is not evidence of real-world safety.

## Module 10: Robotics Systems Engineering

### Question

Can another engineer reproduce, observe, and safely operate the complete system?

### Concepts

- Pi versus Jetson responsibility boundaries.
- Network transport, sequencing, timeouts, and stale messages.
- Configuration, versioning, and model artifact provenance.
- Structured telemetry, logs, plots, and experiment manifests.
- Unit tests, integration tests, hardware tests, and fault injection.
- Latency budgets and compute profiling.

### Practical lab

For each physical or simulated run, record:

```text
software commit
model checksum
configuration
hardware state
start conditions
random seed if simulated
timestamped observations and actions
metrics
failure notes
```

### Pass condition

Reproduce a previous result from the repository alone and explain every safety
response when the camera, Jetson, network, or motor command stream fails.

## Portfolio Deliverables

The finished project should contain:

1. A system architecture diagram with ownership and safety boundaries.
2. Live selected-object detection and autonomous following footage.
3. A synchronized real-world telemetry dataset.
4. A documented system-identification experiment.
5. A MuJoCo digital twin using the same controller interface.
6. Before/after Real2Sim calibration plots and held-out metrics.
7. A deterministic-controller baseline.
8. An optional learned-policy comparison.
9. Failure demonstrations: target loss, stale frames, network loss, and
   emergency stop.
10. A short technical video that explains evidence rather than only showing a
    successful run.

## Ordered Execution Checklist

Do not skip ahead simply because a later topic sounds more advanced. The
credibility comes from connecting the layers and measuring them.

1. Inspect weight updates with the one-weight lab and one real CNN parameter.
2. Run and benchmark pretrained object detection on Jetson.
3. Add target selection and tracking.
4. Dry-run the deterministic autonomy controller.
5. Complete bounded physical object following.
6. Add synchronized MPU and control logging.
7. Identify real dynamics parameters.
8. Build the MuJoCo twin with the same interfaces.
9. Calibrate and validate Real2Sim.
10. Add policy learning only after the deterministic baseline is measured.
