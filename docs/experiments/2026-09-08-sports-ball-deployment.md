# Sports-ball deployment and bounded manual control

## Objective

Prepare the currently selected soccer-ball mission, prevent indefinite repeated
motion, and fix delayed manual-button requests. The owner placed a soccer ball
and a bottle on the floor, reported restarting the Pi, and was leaving. No
unattended physical motion was commanded.

## Actual device result

The Jetson answered via USB at 192.168.55.1. Pi HTTP and SSH at 192.168.0.87
failed, mDNS did not resolve, and discovery of controller port 8765 and SSH port
22 across the current 192.168.0.0/24 LAN found no responding candidates. The
router itself answered ping. This narrows the failure but does not prove its
cause. The Pi's latest power state, wiring and Wi-Fi association remain unknown.
No network configuration, router settings or SD contents were changed.

## Target selection: what changed and why

The running TensorRT model has a `sports ball` output class. The Jetson is now
configured to select that class and ignore bottle detections for this mission.
The service's startup command also includes `--target "sports ball"`, so restarting
the Jetson service no longer silently returns to orange. Other runtime tuning
is still session configuration; this change does not persist every API setting.

The model weights were not trained or changed. Its network calculates class
scores and boxes; the configured class filter selects which boxes can become
target observations. A tomato/potato or arbitrary red sphere is not a substitute
for verifying the selected object's detection in the actual camera view.

## Two different timeout mechanisms

1. The existing Pi watchdog stops motor output after roughly 350 ms without a
   fresh command. It addresses a crashed sender or broken connection.
2. The new Jetson mission deadline stops accepting new motion after 45 seconds
   from arming. It addresses a sender that is alive but repeatedly failing to
   complete a mission. Re-arming starts a new bounded interval.

The deadline uses a monotonic clock, so the Jetson's incorrect wall-clock date
does not change its duration. It is checked before observation and again before
motor/heading commands, including after slow inference. Expiry raises a fault,
disarms the mission, and requests zero output. A pending HTTP operation or an
already accepted Pi pulse can take time to finish; this is not a hard-real-time
guarantee of a physical stop at exactly 45.000 seconds.

Code: `AutonomyService._motion_allowed_locked`, `_step`, `_run_motor_pulse`,
and `_run_heading_turn` in `software/jetson/autonomy_service.py`.
The default `mission_timeout_s=45.0` is separate from shared target-control math.
Monitor faults now clear `monitoring`, preventing repeated failed camera retries
from being presented as a live monitor.

## Manual-control race: how it worked

Previously a button press started an asynchronous disarm request and, separately,
an interval sending motor commands. Releasing the button cleared the interval,
but could not cancel the pending function. When that function resumed after
disarm, it could still send forward even though the button was released.

`software/sim/manual_drive.js` now gives each hold a generation number. Release
invalidates that generation immediately. Pending starts check the number after
awaiting disarm. A single request completes before another is sent, so requests
do not pile up. If release happens with a command already in transit, STOP is
requested immediately and again after that request settles. The Pi watchdog is
still required because a browser cannot revoke a packet already delivered.

Losing page visibility/focus stops a held manual drive. The main STOP button
also requests Jetson disarm, so an active mission cannot keep overriding a
manual zero command. Transport failure is shown as an error, not as confirmation
that the chassis physically stopped.

## Deployment and measurements

The Jetson service was restarted successfully and its status verified:

```json
{"state":"disarmed","armed":false,"monitoring":false,
 "target":"sports ball","detector_ready":true,
 "mission_timeout_s":45.0,"frames_processed":0}
```

Local and remote SHA-256 matched for both deployed files:

- `autonomy_service.py`: `5e6f7894c9f33fe106ebfb7aeb9343c3e30ec96baa86cd27f26e889fbbbde2e9`
- `frontier-autonomy.service`: `6766a936553b8f36b749d002fd1e0572e233c99f6743e31cdf8ec0d0cc03b643`

Remote originals were retained with `.pre-sports-ball-20260908` suffixes beside
the Python file and the user's systemd unit. The Mac lab was restarted with the
new manual-control module. Browser inspection confirmed selected target, timeout,
disabled motion/arming controls and the Pi connection error. No test clicked a
real movement control.

Validation: 179 Python tests and 13 JavaScript tests passed. New tests cover
expiry before motion, expiry during inference, re-arming, invalid timeouts,
monitor faults, release during disarm, release during transmission, repeated
presses, disarm failure, cancellation while stopping, and offline UI controls.

## Still not complete

- The Pi camera `read1` repair remains local only, not deployed.
- No fresh soccer-ball detection was possible without the Pi camera.
- The possible wheel/wiring fault has not been diagnosed or repaired.
- No new physical search, approach or stop-before-contact trial has passed.
- These changes do not provide household obstacle avoidance or physical transfer
  of the simulated navigation policy.

When the owner returns, restore Pi access first without assuming a reflash is
needed. Then collect a stationary frame, deploy/measure the camera reader fix,
confirm consistent wheel response under supervision, and run a bounded mission.
Keep the bottle out of the driving path; ignoring its class does not make it safe
to collide with it.

## Lesson

Detector selection, mission control, button handling and motor watchdogs are
different layers. Selecting a class changes what perception accepts. A mission
deadline bounds repeated decisions. A cancelled UI task prevents a late command.
The Pi watchdog limits continued output if communication fails. None of these
is a measurement of wheel speed or a repair for loose wiring.

Teach-back: why can the 350 ms watchdog fail to stop an endless search, while
the 45-second mission deadline does stop that search?
