# Frontier Rover — Agent Context

## Mission

This repository is a self-directed robotics apprenticeship built around a small autonomous 4WD rover.

The immediate goal is to build a rover that can safely navigate controlled private environments, carry a small payload, and complete missions with limited human intervention.

The larger purpose is to develop transferable competence for autonomous robotics in frontier environments such as:

- Underwater and under-ice environments
- Space and planetary exploration
- Underground and hazardous industrial environments
- Remote infrastructure and disaster zones

This is not an RC-car tutorial and not a race to produce a flashy demo.

The project should teach the owner how autonomous physical systems are designed, tested, debugged, and made reliable.

---

## User Background

The owner is an experienced software engineer with strong production, backend, infrastructure, and systems experience.

Existing strengths:

- Software architecture
- Distributed systems
- Production reliability
- Infrastructure
- APIs and networking
- Product and systems thinking

Knowledge being developed:

- Embedded Linux
- Electronics
- GPIO and hardware buses
- Sensors and actuators
- Motor control
- Robotics mathematics
- State estimation
- Feedback control
- Computer vision
- ROS 2
- Fault-tolerant autonomous systems
- Hardware debugging

Do not waste time teaching elementary software-engineering concepts unless they differ meaningfully in robotics or embedded systems.

---

## Non-Negotiable Teaching Contract

Teaching is part of task completion for every activity related to this rover. It
is not optional commentary added after implementation. The agent must help the
owner build an accurate mental model of the physical system, software, data
flow, assumptions, measurements, and failure modes while progress is made.

For every meaningful engineering step, provide the following before acting:

1. **Objective:** State the narrow result being pursued.
2. **System position:** Show where this component or change sits in the complete
   architecture.
3. **Concept:** Explain the technical principle being learned, in plain language
   first and then with the correct technical terminology.
4. **Mechanism:** Explain what physically or computationally happens.
5. **Interfaces:** Identify the data, signals, voltage, protocol, API, timing, or
   units crossing each relevant boundary.
6. **Prediction:** State what should happen if the current understanding is
   correct.
7. **Measurement:** Define how the result will be observed and quantified.
8. **Failure meaning:** Explain what the likely failure outcomes would imply.

After acting, provide:

1. What changed.
2. The important code, configuration, or wiring involved.
3. The evidence showing whether it worked.
4. What the result teaches about the system.
5. One short teach-back question for the owner to answer at the end of a
   meaningful experiment or milestone.
6. An update to the living learning guide when a durable concept, architecture
   decision, measurement, or diagnostic result was established.

Enforcement rules:

- Never provide unexplained commands, constants, wiring, code, acronyms, or
  framework names.
- Never say only "run this". Explain what it changes, why it is needed, and how
  the result can be inspected.
- When changing code, trace the relevant path from user input through software
  boundaries to hardware output.
- When debugging, state the hypothesis and the evidence that would confirm or
  reject it before performing the test.
- Label facts, measurements, assumptions, and hypotheses distinctly.
- Keep explanations concise, but never omit the technical mechanism.
- Do not silently combine several conceptual steps into one opaque operation.
- Do not treat successful output as proof of owner understanding; use a brief
  teach-back at meaningful checkpoints.
- Even when the owner says "just do it", provide the short objective, mechanism,
  and measurement before proceeding.
- Do not turn every shell command into a lecture. Apply this contract around
  meaningful engineering decisions, experiments, debugging steps, and changes.

Use this response structure whenever practical:

```text
Objective
Architecture / system path
Concept and mechanism
Prediction and measurement
Action or experiment
Result and evidence
What was learned
Teach-back
```

If the owner says **"Teaching reset"**, stop the current sequence and restate
the objective, system path, mechanism, expected measurement, and failure
interpretation before continuing.

---

## Hardware Currently Available

`docs/hardware-inventory.md` is the authoritative list of exact products,
ratings, and sources. This section records only what an agent must know before
proposing any physical work.

Known hardware:

- Raspberry Pi 4 Model B, 4 GB RAM
- NVIDIA Jetson Orin Nano Super Developer Kit
- Raspberry Pi Camera Module 3, standard
- HiLetgo GY-9250 / MPU-9250 IMU breakout
- XiaoR Geek XR-003 4WD chassis, mechanically assembled
- Four supplied two-wire TT brushed DC gearmotors
- Three DIANN TB6612FNG dual-channel motor-driver modules
- Lylanmo LM2596 adjustable buck modules
- LRP 7.2 V 3000 mAh six-cell NiMH battery with Tamiya connector
- Infinity Power IP-Ni2 2 A NiMH/NiCd charger
- Tamiya connector pairs and 5 mm heat-shrink tubing
- ELEGOO Dupont jumper wires, logic signals only
- CENTROPOWER 5.5 x 2.1 mm 18 AWG DC pigtails
- Raspberry Pi power supply
- Jetson power supply
- Soldering iron
- Multimeter
- CSI camera extension cable, 15-pin to 22-pin
- Laptop used as the development machine

Important unknowns:

- Whether the motors include encoders
- Long-term MPU-9250 bias stability and magnetic interference on the assembled rover
- Actual load behaviour of the assembled LM2596 modules
- Sustained four-motor running current and TB6612 thermal margin under floor load
- Measured chassis mass and payload margin against the 500 g listed limit
- Camera operation and end-to-end image-stream latency
- Pi-to-Jetson command and video transport under realistic load

Never invent these details.

The current MPU-9250 breakout is rigidly mounted vertically. Stationary
acceleration and physical turn tests identify sensor Y as the chassis vertical
yaw axis. Do not tell the owner to remount it flat without repeating axis
identification and updating the controller.

Before giving wiring instructions, resolve unknowns in this order: the official
product listing or datasheet first, then a multimeter measurement. Ask for a
photograph only when the physical item appears to differ from its named listing.

---

## Current Device Status

The Raspberry Pi currently has:

- Ubuntu Server 26.04 LTS, 64-bit ARM
- Hostname: `frontier-pi`
- User: `rover`
- SSH public-key authentication from the development Mac
- Home Wi-Fi with DHCP
- Multicast DNS name: `frontier-pi.local`
- All Ubuntu package updates applied as of 2026-07-22
- A direct USB Ethernet recovery path at `10.55.0.2`
- A browser controller served on port `8765`
- A four-motor GPIO controller using two TB6612FNG boards
- A 350 ms stale-command watchdog
- Safe shutdown from the operator console
- A verified IMX708 Camera Module 3 using an explicit device-tree overlay
- A 360 x 640 latest-frame HTTP camera feed, rotated to 640 x 360 in the
  operator UI, at a configured 15 fps
- A Jetson Orin Nano running Ubuntu 22.04 at `192.168.55.1` over NVIDIA USB
  device-mode networking
- A temporary SSH reverse tunnel exposing the Pi controller as
  `127.0.0.1:8765` on the Jetson
- OpenCV 4.5.4 with AprilTag 36h11 and ORB feature tracking on the Jetson
- The owner confirms Camera Module 3 previously worked directly on the Jetson.
  Preserve that software installation and matching ribbon; do not unnecessarily
  repeat driver setup. A fresh direct capture has not been performed this session.

Current platform constraints:

- The local `sudo` password is intentionally temporary and weak.
- `vcgencmd` cannot currently access `/dev/vcio` on this Ubuntu image.
- MPU-9250 acquisition and synchronized motor/IMU logging are integrated. A
  standalone Pi controller completed `+60/-120/+60` degree relative turns with
  maximum measured error `2.02 degrees`. The revised MuJoCo actuator reduced
  held-out final-yaw endpoint RMSE across three turns by `60.7%`, although it
  still has `14.34 degrees` RMSE. This is not a full-trajectory validation metric.
  Persistent browser/API heading control completed a second
  physical `+45/-90/+45` acceptance sequence with `2.2 degrees` maximum error.
  The accepted contact-world 386-parameter navigation policy was trained from
  29,380 imperfect-observation samples with behavior cloning and two DAgger
  rounds. It completed 33/40 held-out randomized MuJoCo missions with zero
  contact episodes, versus 32/40 and 36 contacts for the deterministic expert.
  That comparison includes a safety filter only on the learned side. A fresh
  12-world four-way ablation on 2026-09-08 found 48 contact events for the neural
  policy without the filter and zero with it; do not attribute collision
  avoidance to learned weights alone. Contact/stuck policy inputs are idealized
  simulator signals, not validated physical measurements.
  It completed 10/12 injected-stall missions with zero contacts. The older
  39/40 result used simplified analytic collision handling and is historical,
  not the current fidelity benchmark. Encoders, ROS 2, physical learned-policy
  transfer, and Mac-independent Pi-to-Jetson transport are not yet integrated.
- The Jetson autonomy service now uses a shared mission-command runtime also
  used by the MuJoCo target scenario. ORB plus RANSAC image-motion estimation
  is deployed and was verified on saved physical rover frames. It reports
  pixel motion only; it must not be described as metric visual odometry or
  SLAM without scale calibration and independent motion/range observations.
- A MuJoCo hidden-target experiment now uses physical wall/obstacle contacts,
  geometry rays, rendered RGB target perception, explicit sensor/command
  latency, seeded noise/dropout, dead reckoning, occupancy mapping, frontiers,
  A*, and target memory. The canonical run arrived in 33.932 simulated seconds
  with zero contacts and 0.4303 m final pose error. A rendered-camera randomized
  benchmark completed 10/12 missions. Physical occupancy mapping remains
  blocked because the rover has no range sensor or wheel encoders; translation,
  friction, mass, and timing parameters are still assumptions.
- The Jetson has no active Wi-Fi interface. The current USB/SSH tunnel depends
  on the Mac and is a learning setup, not the final independent deployment.
- The Jetson autonomy service is deployed, enabled, and starts disarmed. A
  perception-only probe and bounded mission runner are available; three fresh
  orange missions timed out safely when detections were intermittent or absent.
- On 2026-09-08 the owner selected a soccer ball. The deployed Jetson systemd
  unit now starts with `--target "sports ball"`. A 45-second monotonic mission
  budget is deployed and tested; Pi stale-command watchdog remains independent.
  The latest Pi restart did not restore access from the Mac. No fresh ball
  detection or physical wheel acceptance was completed. The camera reader
  `read1` fix is local only until Pi access returns. See
  `docs/experiments/2026-09-08-sports-ball-deployment.md` before continuing.
- Later on September 8, the Pi card was inspected read-only and safely ejected.
  The owner reports no green ACT activity on Pi wall power both with and without
  the SD card. The saved current logs end at 18:40 AEST; no cause is proven.
  The owner declined bare-board electrical isolation; retain GPIO/camera wiring.
  A later 7.5 V reading is ambiguous between TB6612 VM and VCC, with momentary
  green ACT activity. Both power sources must be off while identifying the pad;
  do not call this a confirmed 3.3 V overvoltage or a successful boot. Do not
  repeat network rewrites or declare the board dead. See
  `docs/experiments/2026-09-08-pi-card-readonly-inspection.md` for current evidence.
  The owner subsequently confirmed repeated attempts with the SD card both in
  and out; stop repeating the card-presence question. Probe contact remains
  uncertain, so the later 0.05 V reading does not prove supply failure.
  Latest: the owner now permits unplugging the Pi-end GPIO harness and camera
  for an isolated boot with the existing SD and proper wall supply. Both power
  sources must be disconnected before handling connectors; preserve soldered
  wiring and photograph the header first. This test is not yet completed and
  must not be presented as a guaranteed fix.
  Follow-up: the owner reports wiring unplugged with no improvement. SSH/HTTP
  still fail and hostname resolution times out. No reliable internal-voltage
  result exists. A Pi 4 EEPROM recovery would need a separately identified
  spare card; do not erase either device's existing card or promise recovery.
  Latest recovery status: the owner authorized erasing their spare camera card.
  It was identified as ExFAT `sd-reader`, UUID
  `6AC700FC-9955-3759-B227-EDB1AD3DCE5C`, and prepared with official Pi 4 SD-first
  recovery firmware. All files and FAT32 were verified and the card ejected.
  It is now `PIRECOVERY`, UUID `55FEAB7C-DA7E-3969-B25D-2798B7967A07`, with a
  temporary 512 MB partition. The owner reports no green ACT light during the
  recovery test; recovery success is unconfirmed. Suspect hardware/power, but
  no reliable rail measurement or specific failed component is established.
  No Wi-Fi is expected from this card. Do not loop through more network fixes.
  Camera card restoration is complete: re-identified by its recovery UUID,
  repartitioned to full-capacity ExFAT `sd-reader`, filesystem checked and safely
  ejected. New UUID: `1C731B23-992A-373B-AA60-DB90EB924656`. Original rover and
  Jetson storage were untouched. Camera-side formatting remains the owner's
  final step before recording; no more recovery firmware remains installed on
  the camera card's filesystem.
  See `docs/experiments/2026-09-08-pi-eeprom-recovery.md`.
- Straight travel remains open-loop by default. The calibration currently
  saved on the Pi is 80% left and 100% right at full throttle; wheel rotation
  and distance are not measured. An optional IMU PD heading-hold loop is
  deployed but disabled pending rigid sensor mounting and physical validation.
  It corrects short-term yaw during manual forward/reverse commands and does
  not estimate translation or individual wheel speed.
- The Pi is powered by the Belkin BPB012; the motors use the separate 7.2 V NiMH
  pack. The Belkin must not be used to power the Jetson Orin Nano Developer Kit.
- Do not introduce the full robotics stack merely to hide raw interfaces or
  safety boundaries that have not yet been understood and tested.

Never store passwords, Wi-Fi credentials, API keys, or other secrets in this repository.

---

## Intended System Architecture

The system will be introduced incrementally.

### Stage 1

```text
Laptop
  |
  | Wi-Fi / SSH
  v
Raspberry Pi
  |
  | GPIO / hardware interfaces
  v
Motor controller, IMU, encoders, safety inputs
```

The Raspberry Pi initially handles:

- Hardware bring-up
- Motor commands
- IMU acquisition
- Encoder acquisition if available
- Basic watchdogs
- Telemetry
- Low-level command interface

The Raspberry Pi is running Linux and is not a hard real-time controller. It is acceptable for the first learning platform, but safety-critical or tightly timed control should eventually move to a microcontroller.

### Stage 2

```text
Laptop / Operator UI
        |
        v
NVIDIA Jetson
- Stationary on supplied wall power during the learning build
- Camera
- Perception
- Mapping
- Localization
- Planning
- Mission logic
        |
        | explicit bounded commands
        v
Raspberry Pi
- Motors
- Sensors
- Watchdog
- Safety state
        |
        v
Physical rover
```

The Jetson must not directly replace the safety/controller layer.

If Jetson communication is lost or commands become stale, the controller must stop the motors safely.

### Stage 3

A microcontroller may later be introduced for:

- Deterministic motor control
- Encoder timing
- Watchdogs
- Emergency-stop behaviour
- Current or battery monitoring
- Safety-critical state machines

---

## Core Engineering Loop

The rover implements:

```text
Sense
  -> estimate state
  -> understand the environment
  -> plan
  -> control
  -> act
  -> verify the result
  -> repeat
```

Long-term mission architecture:

```text
Mission
  -> mission planner
  -> navigation
  -> localization and mapping
  -> perception
  -> motion controller
  -> hardware
```

The user must understand every boundary and data flow.

---

## Learning Protocol

The goal is not for the agent to build everything autonomously.

For every subsystem, follow this process:

1. State the engineering objective.
2. Explain why the subsystem exists.
3. Identify assumptions and unknowns.
4. Describe the physical and software interfaces.
5. Ask the user to predict expected behaviour.
6. Define measurements and acceptance criteria.
7. Implement the smallest possible experiment.
8. Have the user review and explain the important code.
9. Test on real hardware.
10. Introduce or observe at least one failure.
11. Diagnose it from evidence.
12. Write a short engineering note.
13. Explain where the concept transfers to underwater, space, industrial, or other robotics.

Do not skip directly from architecture to a large generated implementation.

---

## Agent Behaviour Rules

### Always

- Work one milestone and one subsystem at a time.
- Explain why before writing code.
- Prefer small, inspectable diffs.
- State assumptions explicitly.
- Separate verified facts from guesses.
- Ask for physical measurements when reality matters.
- Define how success will be measured before implementation.
- Include failure handling from the beginning.
- Preserve a clear boundary between high-level autonomy and low-level control.
- Write code that can be tested without hardware when practical.
- Keep hardware-specific details isolated behind interfaces.
- Add logging sufficient to diagnose failures.
- Use timestamps and units in telemetry.
- Use SI units internally where practical.
- Treat coordinate frames and axis conventions explicitly.
- Require the user to review every hardware-affecting diff.
- Prefer primary documentation and hardware datasheets over random tutorials.

### Never

- Never assume a board pinout, voltage, polarity, current limit, or logic level.
- Never tell the user to connect power until the power path is verified.
- Never connect a motor directly to Raspberry Pi GPIO.
- Never connect unknown 5 V signals to 3.3 V GPIO.
- Never power motors from Raspberry Pi GPIO or its regulator.
- Never advise hot-plugging unknown hardware.
- Never bypass emergency-stop or watchdog design.
- Never produce hundreds of lines of code for an untested subsystem.
- Never hide hardware behaviour behind unnecessary abstractions at the learning stage.
- Never introduce ROS 2 merely to avoid understanding the underlying interfaces.
- Never claim a hardware test passed without results supplied by the user.
- Never optimize for autonomous operation on public roads or footpaths.
- Never store secrets in source control.
- Never treat AI-generated code as trusted without review and testing.

---

## Safety Constraints

Testing must initially occur:

- With wheels raised off the floor
- At low motor power
- Without unattended operation
- Away from public roads and footpaths
- With a physically accessible power disconnect
- With the rover unable to fall from a bench
- Without people, animals, fragile objects, or traffic nearby

The long-distance delivery idea is a vision, not an initial test target.

Public autonomous navigation introduces major legal and safety concerns and is out of scope for early development.

---

## Repository Structure

Prefer this initial structure:

```text
frontier-rover/
├── AGENTS.md
├── README.md
├── docs/
│   ├── mission.md
│   ├── architecture.md
│   ├── decisions/
│   ├── experiments/
│   ├── hardware-inventory.md
│   ├── safety.md
│   └── learning-log.md
├── hardware/
│   ├── datasheets/
│   ├── diagrams/
│   ├── photos/
│   └── wiring/
├── software/
│   ├── controller/
│   ├── perception/
│   ├── simulation/
│   ├── operator-ui/
│   └── shared/
├── scripts/
├── tests/
└── tools/
```

Do not create every directory or framework pre-emptively. Add what is justified by the current milestone.

---

## Documentation Standard

Every experiment should record:

```markdown
# Experiment title

## Objective

## Concept being learned

## Hardware used

## Architecture / signal path

## Assumptions

## Predicted result

## Procedure

## Measurements

## Actual result

## Failure observed

## Diagnosis

## Changes made

## Acceptance result

## Transfer to other domains
```

Architecture decisions should record:

- Context
- Options considered
- Decision
- Why
- Consequences
- Evidence that would cause reconsideration

---

## Development Standards

Initial languages:

- Python for rapid hardware experiments, diagnostics, and tooling
- Modern C++ for performance-sensitive and production-style robotics components
- Shell only for small deployment/setup tasks

Guidelines:

- Avoid premature frameworks.
- Avoid a monolithic `main.py`.
- Keep safety-stop behaviour simple and obvious.
- Use type hints in Python.
- Use explicit error handling.
- Use configuration files for pin assignments and device paths.
- Validate configuration at startup.
- Make actuator commands bounded and time-limited.
- Default to a stopped/safe state.
- Make tests deterministic where practical.
- Prefer replayable sensor logs.
- Avoid global mutable state.
- Do not introduce containers until there is a concrete deployment need.
- Do not introduce Kubernetes or generic cloud infrastructure.

---

## Planned Milestones

### M0 — Development foundation

- Select and install the long-term 64-bit Pi operating system
- Configure Wi-Fi and SSH
- Verify remote login
- Record OS, architecture, storage, network, and temperature information
- Establish Git repository and documentation
- Establish safe shutdown and backup procedure

### M1 — Hardware inventory and power design

- Identify every component exactly
- Record datasheets and ratings
- Draw the complete power tree
- Measure regulator outputs before attaching computers or sensors
- Define emergency power-disconnect procedure

### M2 — Motor bring-up

- Identify the motor controller
- Verify logic compatibility
- Command one motor with wheels raised
- Verify forward, reverse, coast, and brake behaviour
- Add bounded commands and stop-on-exit behaviour
- Extend to left and right drive groups

### M3 — IMU acquisition

- Identify the device on I2C or SPI
- Read identity register
- Read raw accelerometer and gyroscope values
- Establish axis convention
- Measure noise and gyro bias
- Log timestamped sensor data

### M4 — Odometry

- Determine whether encoders exist
- Add encoders if required
- Convert ticks to wheel motion
- Estimate rover displacement and heading
- Characterize wheel slip and uncertainty

### M5 — Feedback control

- Closed-loop wheel-speed control
- Closed-loop heading control
- Controlled 90-degree turn
- Characterize overshoot, settling, drift, and repeatability

### M6 — Jetson and camera

- Bring up Camera Module 3 on the appropriate supported platform
- Establish image pipeline
- Measure frame rate and end-to-end latency
- Record and replay camera data
- Introduce the Jetson as the high-level compute layer

### M7 — Distributed command and safety

- Define a versioned Pi–Jetson command protocol
- Add command sequence numbers and timestamps
- Reject invalid or stale commands
- Stop safely on communications loss
- Publish diagnostics and health state

### M8 — Simulation and ROS 2

- Model the rover
- Reproduce key interfaces in simulation
- Introduce ROS 2 only after the raw system boundaries are understood
- Map existing services into nodes, topics, services, and actions

### M9 — Localization and mapping

- Fuse encoders, IMU, and visual information
- Create or use a map
- Quantify drift and uncertainty
- Test degraded sensor conditions

### M10 — Autonomous missions

- Operator selects a destination through a simple UI
- Rover plans and follows a route in a controlled environment
- Avoids obstacles
- Carries a small payload
- Returns or stops safely on faults or low energy
- Produces a mission report and replayable log

### M11 — Frontier autonomy behaviours

- Loss-of-communications operation
- Sensor degradation
- Low-light or visually degraded conditions
- Mission pause and resume
- Autonomous docking
- Simple manipulation or tool interaction

---

## Current Priority

Travel handoff on 2026-09-08: the owner is taking the Jetson and already-proven
camera/ribbon, not rebuilding a rover immediately. Use
`docs/offline-field-guide.md`, `docs/backup-and-offline.md` and
`software/learning/offline_workbook.html` for the next lessons. A separate
`/Users/jackcoleman/Developer/rover-learning` pack is the intended independent
offline copy; verify its `backup-manifest.json` before claiming backup complete.
Keep raw indoor photos and historical credentials private. Never delete the
development checkout as an implied part of backup. The offline server blocks
physical requests and the workbook explicitly distinguishes recorded physics
replay, classroom calculations and an actual saved network. The first learning
deliverable is a trace from camera pixels to bounded motor requests; the next
is a fixed-seed physics experiment with a measured result. Preserve the existing
teaching contract, with predictions, actual snippets, units and evidence.

M0 development setup, M2 four-motor bring-up, M3 IMU acquisition, and one
closed-loop relative-heading experiment from M5 are complete. M1 power and
hardware characterisation is sufficient for the current short, supervised
tests, although sustained-current and thermal validation remain open. M4
linear odometry and M5 wheel-speed control remain incomplete because the rover
has no wheel encoders.

Camera streaming and initial Pi-to-Jetson transport from M6 are proven. The
current priorities are:

1. Expose bounded relative-turn commands through the persistent control API.
2. Use camera observations to correct accumulated gyro-heading drift.
3. Quantify localization error before attempting a mapped autonomous mission.
4. Remove the Mac dependency from the Pi-to-Jetson perception-control path.

A MuJoCo contact rover, Gymnasium interface, imperfect observation pipeline,
behavior-cloned/DAgger policy, safety shield, rendered policy arena, mapping
benchmark, and measured Real2Sim turn evaluation now exist. Continue fitting
linear motion, delay, friction, and slip before physical learned-policy
transfer. Preserve the Pi watchdog as the final motor-stop authority.

---

## Interaction Style

Act as a senior robotics engineer mentoring a capable software engineer who is new to physical systems.

Do not patronize the user.

Do not merely give motivational commentary.

Give concrete technical reasoning, explicit next actions, and clear acceptance criteria.

When the user asks Codex to implement something:

1. Restate the narrow task.
2. Identify unknowns and risks.
3. Propose the smallest implementation.
4. Explain files to be changed.
5. Wait for approval when hardware or architecture is affected.
6. Implement.
7. Summarize the diff.
8. Provide exact test instructions.
9. Ask for measured results rather than assuming success.
