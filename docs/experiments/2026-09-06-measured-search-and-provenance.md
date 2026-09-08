# Measured Search and Data Provenance

## Objective

Replace timing-based target search with measured heading steps and make every
Autonomy Lab view state whether its data is live, recorded, or simulated.

## Fault Found

`search_step_degrees=30` existed in configuration, but the running search path
called a 45 ms open-loop motor pulse. The configured angle was unused. A time
pulse cannot guarantee angle because drivetrain response changes with voltage,
friction, load, and wheel contact.

## Change

The Jetson now requests a signed 30-degree relative turn from the Pi. Sign is
converted because the visual controller defines positive turn as right while
the Pi heading controller defines positive angle as left. The Pi uses the
MPU-9250 gyroscope feedback to finish the turn before the Jetson observes up to
three new frames. Search is bounded to 12 steps per sweep and three sweeps,
with a short reverse viewpoint change and direction reversal between sweeps.

The Jetson also exposes a perception-only monitor. It continuously runs the
real camera and TensorRT detector but cannot send motor actions. The Lab UI
labels detector provenance and suppresses stale boxes over live camera frames.

The SIM view now exposes a hidden-target scenario, camera field of view,
controller state, trajectory, physics engine, timestep, measured fit, and
unmeasured assumptions.

## Evidence

- Full local suite: `139/139` tests passed.
- Jetson service after deployment: active, detector ready, disarmed.
- Deployed search limit: 12 steps; configured step: 30 degrees.
- Live monitor: 12 fresh frames, orange confidence 0.651, proposed action
  `forward=0.631`, `turn=-0.044`, `sent=false`.
- Independent Pi status during monitor: stopped, left output 0, right output 0.
- MuJoCo target at 170 degrees: acquired and reached ARRIVED in 54 control
  steps at a simulated final range of 0.18 m.

## Physical Acceptance

The physical rover began with the mandarin outside its camera view. Its first
12-step sweep returned no detections, so it performed the bounded reverse and
changed scan direction. It then detected, aligned with, and approached the
target. Intermittent close-range detections caused stationary reacquisition and
additional measured search steps rather than blind forward motion.

The mission reached `ARRIVED` with:

- 140 mission decisions
- 41 SEARCHING, 3 RECOVERING, 10 ALIGNING, 8 APPROACHING, and 11 REACQUIRING
  decisions before the latched arrival state
- final TensorRT confidence `0.784`
- final target area ratio `0.1224`
- final target bottom edge `0.9903`
- final frame age `152 ms`
- final action `forward=0`, `turn=0`, `sent=true`
- post-disarm Pi output `left=0`, `right=0`, `motor_active=false`

The raw terminal status is stored at
`artifacts/physical/2026-09-06-hidden-target-measured-search-status.json`.

## Interpretation

The monitor proves perception without actuation. The simulator proves the
algorithm against an explicit model, not the physical room. Physical acceptance
has now passed one clear-floor mission beginning with the mandarin outside the
camera's initial view. This demonstrates local visual search, not obstacle-aware
house exploration.
