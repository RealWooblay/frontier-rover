# Frontier Rover Demo Runbook

## Today's Finish Line: 8 September

Evening status: the Pi remains unreachable after the owner reports disconnecting
the wiring. No fresh physical demo was completed. For tonight, record the
simulation and recorded-data chapters; describe older physical operation as
past experiments and the current startup fault as unresolved. The latest
simulation spot check also timed out without contact; retain and explain that
failure rather than presenting only successes. See the closing entry in
`learning-guide.md` and `artifacts/sim/2026-09-08-final-hour-check.json`.

Record a defensible 4-5 minute case study: a real camera/control demonstration,
measured turning calibration, and clearly labeled simulation. This is not
whole-house autonomous search or physical learned-policy transfer. The owner
reports that the Belkin works again. Fresh device checks and recording remain
required; older artifacts are not today's physical test.

Start with sections 1-2 of the [practical course](rover-practical-course.md).
After recording, work through its gradient, simulation and identification labs.
The objective today is a reproducible explanation, not memorizing robotics.

## Preparation and Roles

Latest session: see the [camera/wiring diagnostic](experiments/2026-09-08-camera-delivery-and-hardware-boundary.md).
The Pi became unreachable after a successful disarmed perception probe. The
camera buffering fix is local only, and the user reports possible wheel faults.
Do not skip those checks or claim a completed physical demo. The potato is not
a class in the installed model; confirm a supported replacement before arming.

Update: the owner supplied a soccer ball and bottle. `sports ball` is now the
persisted Jetson startup target, with a 45-second mission limit. The updated lab
shows these values. Pi access and physical trials remain outstanding; see the
[latest deployment record](experiments/2026-09-08-sports-ball-deployment.md).

The owner powers the Pi from the Belkin and the Jetson from its own adapter,
connects Jetson USB data to the Mac, clears a small floor area, places the
selected soccer ball and records video. Keep stairs, people, cables and fragile objects
out of the driving area. Keep access to the motor-power connection.
No new purchases, soldering or calibration changes are planned unless a fresh
check reveals a fault.

The assistant checks connections, fresh camera/IMU/status data and disarmed
state; records software settings; and verifies STOP before autonomous motion.
Do not silently arm while the owner prepares the camera. An unreachable endpoint
does not prove the power bank, router or SD card is broken.

Read-only checks from the Mac:

```bash
curl --max-time 5 http://frontier-pi.local:8765/api/status
curl --max-time 12 http://127.0.0.1:8780/api/live
```

Inspect the JSON for errors and freshness. The local lab can reply even when
both devices are offline. These checks do not move motors. Use a fallback IP
only when freshly verified; do not reflash a card on the basis of a failed URL.

If the lab is not running, start it from the repository:

```bash
cd /Users/jackcoleman/Developer/frontier-rover
MUJOCO_GL=cgl PYTHONPATH=software/sim:software/shared:software/jetson \
  .venv/bin/python software/sim/lab_server.py --port 8780
```

The Mac must stay awake for the present SSH tunnel/lab arrangement. The rover
can run on batteries with the Jetson on the desk. This is not fully onboard or
Mac-independent.

## Recording Script

| Time | Show | Explain |
| --- | --- | --- |
| 0:00-0:45 | Rover, Pi, camera, drivers and separate Jetson | Camera -> detection -> controller -> HTTP -> Pi GPIO -> motor power; command watchdog |
| 0:45-2:00 | Camera box/state and external rover view | Box-center alignment; size/bottom-edge proximity heuristic; actual stop before contact |
| 2:00-3:00 | Real2Sim plot and validation | Recorded commands, fitted gains, three separate endpoints, 23.36-degree worst remaining fitted error |
| 3:00-4:30 | MuJoCo cameras, map and policy report | Physics, assumed sensors, measured filter contribution, physical transfer still pending |

Use macOS Screenshot (`Shift-Command-5`) for the screen and a phone for the
external view. Say the run number aloud to match clips to logs. Retain raw
failures; keep passwords and private terminal history out of the recording.

After readiness and STOP checks, record up to three bounded physical trials:
centered visible target; off-center visible target; target just outside initial
view in the same clear area. Run one trial at a time and disarm between them.
Do not hide it behind furniture. For each record placement, settings, detector
source (`yolo` or `hsv`), outcome, duration, contact and operator intervention.
`ARRIVED` is software's proximity judgment; external video must confirm a stop
before the object. STOP + DISARM on contact or incorrect behavior, and retain
the failure. An operator intervention is not autonomous success.

For simulation, keep the seed fixed when changing controllers. The new saved
12-world comparison is: baseline 12/12 goals with 10 contact events;
baseline+filter 10/12 with zero; neural alone 10/12 with 48; neural+filter 11/12
with zero. Explain the filter's substantial contribution and the small sample.

If devices remain offline, finish the simulation/recorded-data chapters and
date any earlier physical footage honestly. Do not claim a new physical test.

## 1. Start and Observe

Power the Pi, motor battery, and Jetson. Confirm the Pi controller at
`http://frontier-pi.local:8765/`, Jetson autonomy console at
`http://192.168.55.1:8771/`, and local Autonomy Lab at
`http://127.0.0.1:8780/`.

Use the Autonomy Lab LIVE tab as the primary system view. It combines the real
camera, TensorRT box, controller state, Pi watchdog, motor output, manual drive,
and autonomy controls. Mapping, Policy arena, Real2Sim, Policy, Evidence, and
Learn expose state estimation, planning, runtime parity, model fitting, neural
inference, claim status, and the actual code path without switching tools.

## 2. Physical Evidence

Use the Pi controller to show manual drive, live camera, IMU yaw rate, and a
bounded relative-angle turn. Explain that the Pi converts normalized commands
to calibrated left/right PWM and stops stale commands after 350 ms.

## 3. Edge-AI Evidence

In the Jetson console, press PROBE CAMERA while disarmed. Show the measured
TensorRT latency, target geometry, proposed action, and `sent:false`. Only ARM
with a clear floor and a visible target; STOP + DISARM ends the mission.

## 4. Real2Sim Evidence

Open the Autonomy Lab Real2Sim tab. Show physical IMU and fitted MuJoCo traces,
the RMSE reduction across three held-out final-yaw endpoints from 36.51 to
14.34 degrees, and the remaining error. This is not full-trajectory validation
and uses the gyro rather than independent motion capture as its reference.

## 5. Mapping and Planning Evidence

Open Mapping and press rerun. Explain the colors before playing: cyan is the
estimated rover pose, white is simulator ground truth, black/red is the map
constructed from range observations, and the cyan line is the planned route.
Change odometry scale or gyro bias and rerun; the visible estimate/truth gap is
the localization error that Real2Sim calibration is intended to reduce.

State the sensor boundary clearly: the range rays are simulated because the
physical rover has no lidar, depth camera, ultrasonic array, or wheel encoders.
The experiment proves software architecture and behavior in MuJoCo, not
physical room mapping.

## 6. Sim2Real Learning Evidence

In the Policy tab, change goal error and obstacle-clearance sliders and show
the 386-parameter network changing forward/turn outputs. In Policy arena,
switch between expert and learned policies, select an identical held-out seed,
inject an actuator stall, and replay the actual MuJoCo chase/onboard frames,
observations, proposed action, delayed executed action, contact count, and pose
error. Physical policy transfer remains pending
because the real rover cannot yet produce the policy's clearance and velocity
inputs.

## Honest Closing

State that relative heading, TensorRT perception, physical target-state
transitions, Real2Sim fitting, domain-randomized simulation, policy training,
Jetson artifact execution, and fail-closed services are measured. Physical
learned waypoint/obstacle navigation and Mac-independent Pi-Jetson transport
remain pending acceptance tests.
