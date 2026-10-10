# Frontier Rover

A hands-on apprenticeship in building a reliable autonomous 4WD rover.

## Archive checkpoint: 10 October 2026

This is a documented robotics prototype, not a completed autonomous household
robot. Historical driving, vision, IMU experiments and laptop simulation are
preserved. Reliable physical hidden-object navigation and validated deployment
of the simulation-trained policy remain unfinished; the Pi fault below remains
unresolved. No new hardware acceptance test was performed for this archive.

The updated [two-hour class](docs/two-hour-robotics/study.md) includes worked
control, vision, learning and simulation lessons. Open its adjacent `study.html`
locally for the interactive exercises. These lessons and their verification
outputs are now versioned alongside the original source and experiment data.

## Status on 8 September 2026

The Pi is currently out of service with a suspected hardware or power fault.
Peripheral isolation and a verified official EEPROM recovery card did not
produce the expected ACT indication. The failed component and cause are not
identified. The results below describe historical experiments, not a live rover.

The project progresses one measured subsystem at a time. The headless Pi,
mobile power, four-motor drive, Wi-Fi recovery, browser controller, camera,
Jetson TensorRT autonomy service, MPU-9250 acquisition, gyro-controlled
relative turns, measured Real2Sim actuator fitting, MuJoCo navigation, and a
trained domain-randomized policy have been implemented and tested within the
boundaries below. The laptop simulation remains usable without the Pi. The engineering lab also
contains a sensor-driven hidden-target mapping experiment with dead reckoning,
an occupancy grid, frontier exploration, A* planning, and explicit comparison
between estimated pose and simulator ground truth.

## Current Platform

- Raspberry Pi 4 Model B Rev 1.5, 4 GB
- Ubuntu Server 26.04 LTS, ARM64
- Hostname: `frontier-pi`
- Remote user: `rover`
- SSH: public-key authentication from the development Mac

Connect from the development Mac:

```sh
ssh rover@frontier-pi.local
```

When Codex runs these commands, macOS must allow **ChatGPT** under **System
Settings > Privacy & Security > Local Network**. If that switch is off, macOS
returns `No route to host` before any packet reaches the Pi.

Normal browser control uses the home 5 GHz network:

```text
http://frontier-pi.local:8765/
```

The operator console provides hold-to-drive controls, a speed multiplier,
live Pi telemetry, camera and Jetson link state, an emergency stop, and a
confirmed clean-shutdown control. Straight travel is currently calibrated to
80% left PWM and 100% right PWM at full slider speed. Left and right calibration
can be changed with the console's numeric controls and is saved on the Pi.

When Wi-Fi is unavailable, connect the Pi USB-C data/power port to the Mac and
use the fixed recovery address:

```sh
ssh rover@10.55.0.2
```

From the development Mac, shut down before removing Pi power:

```sh
ssh -t rover@frontier-pi.local 'sudo shutdown -h now'
```

Enter the Pi password when prompted. Wait at least 20 seconds after SSH
disconnects before unplugging power. The red power LED may remain on because
the supply is still connected; the controller and SSH must become unreachable.

## Working Method

Start the travel study with [the offline field guide](docs/offline-field-guide.md).
The independent learning export includes a Word manual, a browser workbook,
source and evidence copies, and a laptop simulation launcher. See
[backup scope](docs/backup-and-offline.md) before deleting a local checkout.

Read [AGENTS.md](AGENTS.md) before contributing. Experiments belong in
`docs/experiments/`; architecture decisions belong in `docs/decisions/`. The
verified and unknown physical components are tracked in
[`docs/hardware-inventory.md`](docs/hardware-inventory.md).

The living explanation of how the rover works is
[`docs/learning-guide.md`](docs/learning-guide.md). Update it whenever a new
concept becomes understood or a measurement changes the design.

Start today's portfolio and travel learning work with the
[practical course](docs/rover-practical-course.md) and
[recording runbook](docs/portfolio-demo-runbook.md). The course includes runnable
box-to-PWM and gradient-check exercises, a fresh four-way controller comparison,
worked explanations, source readings, and a four-week travel study plan.

The ordered technical syllabus for selected-object autonomy, system
identification, MuJoCo, Real2Sim, and later policy learning is
[`docs/autonomy-real2sim-curriculum.md`](docs/autonomy-real2sim-curriculum.md).
The implemented simulation, neural-policy, mapping, Real2Sim, and transfer
mechanisms are taught end to end in
[`docs/simulation-and-sim2real-course.md`](docs/simulation-and-sim2real-course.md).

Launch the interactive simulator, neural-policy inspector, Real2Sim plots, and
evidence checklist:

```sh
MUJOCO_GL=cgl PYTHONPATH=software/sim:software/shared:software/jetson .venv/bin/python \
  software/sim/lab_server.py --port 8780
```

Then open `http://127.0.0.1:8780/`. The Jetson autonomy console is served from
`http://192.168.55.1:8771/` while its USB device-mode network is connected.
The Jetson service starts disarmed and requires an explicit ARM request.

Generate the replayable mapping evidence without the browser:

```sh
.venv/bin/python software/sim/run_mapping_exploration.py
```

The resulting artifact is
`artifacts/sim/2026-09-06-mapping-exploration.json`. The planner receives only
an estimated pose, occupancy map, simulated range scan, and camera detection;
ground truth is retained separately for sensor generation and scoring.

Run the rendered-camera domain-variation benchmark:

```sh
.venv/bin/python software/sim/evaluate_exploration_fidelity.py --count 12 --seed 907
```

The recorded benchmark completed 10 of 12 randomized missions. Its two
timeouts are retained in
`artifacts/sim/2026-09-06-high-fidelity-exploration.json`; this is simulation
evidence, not proof that unmeasured physical parameters match the rover.

The MuJoCo model uses the same normalized `forward` and `turn` action contract
as physical autonomy:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-sim.txt
.venv/bin/python software/sim/run_mujoco.py --forward 0.4 --seconds 1
```

Its actuator gain and velocity feedback were fitted from synchronized physical
motor/IMU telemetry. A separate `60/-120/60` degree command sequence reduced
held-out error across three final-yaw endpoints from `36.51` to `14.34 degrees
RMSE`; this is not a full-trajectory validation metric. The remaining error is
recorded rather than treated as a successful prediction.

The physical and simulation workflow is reproducible with:

```sh
python3 software/pi/imu_motion_experiment.py artifacts/physical/imu-motion.csv
.venv/bin/python software/sim/fit_imu_turn_dynamics.py \
  artifacts/physical/imu-motion.csv --output artifacts/sim/imu-fit.json
.venv/bin/python software/sim/validate_closed_loop_turn.py \
  artifacts/physical/2026-09-06-closed-loop-turn.csv
.venv/bin/python software/sim/train_navigation_policy.py
.venv/bin/python software/sim/evaluate_navigation_policy.py
```

The accepted contact-physical `9 -> 32 -> 2` policy contains 386 parameters.
It was trained from 29,380 imperfect-observation samples using behavior cloning
and two DAgger rounds. On 40 identical randomized evaluation contact worlds it
completed 33 missions with zero contact episodes, versus 32 missions and 36
contact episodes for the deterministic expert. Under a forced one-second
actuator stall it completed 10/12 worlds with zero contact episodes.

Those results compare the learned policy plus a safety filter against the
baseline without that filter. A fresh 12-world four-way comparison on 8 September
isolated the filter within each family: baseline 12/12 goals with 10 contact
events; baseline plus filter 10/12 with zero; neural policy alone 10/12 with
48; neural policy plus filter 11/12 with zero. This demonstrates the filter's
importance and does not establish general learned-policy superiority. See
`artifacts/sim/2026-09-08-controller-ablation.json` and the practical course.

Reproduce and verify the exact model and evidence boundary:

```sh
PYTHONPATH=software/sim:software/shared:software/jetson .venv/bin/python \
  software/sim/train_high_fidelity_policy.py
PYTHONPATH=software/sim:software/shared:software/jetson .venv/bin/python \
  software/sim/evaluate_high_fidelity_policy.py
PYTHONPATH=software/sim:software/shared:software/jetson .venv/bin/python \
  software/sim/build_offline_evidence.py
```

The resulting manifest is
`artifacts/sim/offline-autonomy-evidence.json`. Physical learned-policy
transfer remains pending because the rover lacks metric range and wheel-speed
observations.

The currently approved physical connection plan is
[`hardware/wiring/m1-one-motor-bench.md`](hardware/wiring/m1-one-motor-bench.md).
The complete two-driver map being assembled is
[`hardware/wiring/m2-four-motor-wiring.md`](hardware/wiring/m2-four-motor-wiring.md).

The bounded channel-A motor command is
[`software/pi/motor_channel_a.py`](software/pi/motor_channel_a.py). It accepts
forward or reverse, a speed from 0 to 1, and a maximum ten-second duration. It
always lowers PWM, both direction inputs, and `STBY` before exiting.
