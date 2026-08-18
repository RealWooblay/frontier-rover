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
- Lylanmo LM2596 adjustable buck modules
- ELEGOO Dupont jumper wires, logic signals only
- CENTROPOWER 5.5 x 2.1 mm 18 AWG DC pigtails
- Raspberry Pi power supply
- Jetson power supply
- Soldering iron
- Multimeter
- CSI camera extension cable, 15-pin to 22-pin
- Laptop used as the development machine

Not present, despite what earlier notes implied:

- No battery, battery holder, or battery protection circuitry of any kind
- No motor-controller board; the XR-003 listing excludes controllers and sensors

Important unknowns:

- Motor winding resistance, running current, and stall current
- Whether the motors include encoders
- Battery chemistry, nominal voltage, maximum voltage, and safe current
- Exact MPU-9250 breakout-board design and voltage tolerance
- Actual load behaviour of the assembled LM2596 modules
- Physical wiring and connector polarity
- Measured chassis mass and payload margin against the 500 g listed limit

Never invent these details.

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
- No Ethernet adapter currently available

Current platform constraints:

- The local `sudo` password is intentionally temporary and weak.
- `vcgencmd` cannot currently access `/dev/vcio` on this Ubuntu image.
- No GPIO, motor, sensor, ROS 2, or Jetson software has been installed.
- Do not install the full robotics stack before the earlier raw interfaces and
  safety boundaries have been understood and tested.

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

Do not build autonomous navigation yet.

The immediate priority is M0:

Completed:

1. Selected and installed Ubuntu Server 26.04 LTS ARM64.
2. Configured Wi-Fi and key-based SSH.
3. Booted and updated the Raspberry Pi.
4. Verified remote access, internet, DNS, storage, temperature, and system state.
5. Recorded the baseline system state.
6. Created the initial Git repository and documentation.
7. Established and tested the safe shutdown procedure.

Remaining before M1:

1. Review the M0 experiment and operating-system decision with the user.
2. Establish and test the backup and recovery procedure.

Do not write GPIO, motor, sensor, ROS, or Jetson code until M0 is complete.

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
