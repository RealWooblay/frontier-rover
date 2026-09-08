# Camera delivery and hardware fault boundary

## Objective and system path

Remove avoidable camera buffering and misleading live indicators before the
next supervised drive. Camera -> rpicam-vid -> Pi Python reader -> HTTP JPEG ->
Jetson inference and Mac lab -> proposed action -> Pi watchdog -> motor drivers.
The user reported potentially weak wheels or wiring faults. That report remains
an open physical issue, not a reason to increase PWM automatically.

## Observed during this session

- The Pi and Jetson initially answered. A second Pi JPEG was sharp after an
  initially blurred picture. Autofocus can explain that transition; permanent
  camera damage was not established.
- The Jetson's existing USB connection worked. Its loopback port 8765 relay was
  restored through the Mac to the verified Pi address 192.168.0.87. A status
  request through the IP-based relay took about 29 ms. This is one HTTP sample,
  not an end-to-end control latency distribution.
- A disarmed TensorRT probe processed three frames. Its retained last timing
  was 16.53 ms preprocessing, 35.67 ms inference-stage time and 5.13 ms
  postprocessing, 57.45 ms total. The inference stage includes transfers and
  synchronization. The proposed search command was recorded with `sent:false`.
- The installed detector has no potato class. Its current target is orange.
  An apple, banana or sports ball is a supported replacement candidate, not a
  guarantee of reliable detection from every distance. No replacement has yet
  been confirmed and no potato model was trained.
- The Jetson clock reports March, although the Mac date is September. Do not
  subtract these hosts' wall-clock timestamps to estimate transport latency.
- The Pi subsequently stopped answering by its verified IP and mDNS name.
  Both command-line requests and a direct browser request failed. The Mac's
  neighbor entry for the Pi was incomplete. The Jetson continued answering and
  was disarmed with monitoring off. This does not identify whether the Pi lost
  power, rebooted, disconnected from Wi-Fi or changed address.

No nonzero motor command was sent by the assistant during this session. Earlier
manual browser commands are not autonomous acceptance tests. No network settings,
SD-card contents, GPIO mapping or PWM calibration were changed on the Pi.

## Reproduced software fault and repair

Python's buffered `stdout.read(64 * 1024)` can wait for 64 KiB even when a complete
JPEG smaller than that has already arrived. At a 10 KiB image size, it may wait
for approximately seven frames. At 15 fps that means several frame periods of
avoidable delay. That example is illustrative, not a measured camera latency.

The regression test launches a child process that writes one short JPEG, flushes
it, and stays open. Before the change, the reader did not publish it within two
seconds. With `stdout.read1(64 * 1024)`, it published before the producer closed
and the test completed in approximately 12 ms. `read1` consumes available pipe
data without waiting to fill the entire requested buffer. The unused pipe is
also explicitly closed on restart/exit.

Code: `software/pi/remote_control.py`, `CameraCapture._run`.
Test: `tests/test_remote_control.py`,
`test_short_frame_is_published_before_producer_closes`.

**Deployment status: local fix tested; NOT installed on the Pi.** The Pi became
unreachable before deployment. Do not call this a measured physical steering
improvement or a fix for Wi-Fi loss.

## Measurement outcome

`artifacts/physical/2026-09-08-camera-delivery-before.json` contains the attempted
baseline: zero frames and connection errors. It is failure evidence, not a valid
before/after timing comparison. Its historical filename does not imply a valid
baseline. No after measurement exists.

When the Pi is reachable, first confirm disarmed autonomy and zero motor output;
capture a valid baseline, back up the remote controller, deploy the camera-only
change without changing calibration, restart the service and capture a second
run. The collector issues only GET requests:

```bash
.venv/bin/python software/learning/camera_delivery_benchmark.py \
  --pi-url http://192.168.0.87:8765 --seconds 10 \
  --output artifacts/physical/camera-delivery-before-retry.json
```

Use the freshly verified Pi URL. The report measures unique frames, gaps,
skipped IDs and publication age. Publication age begins when Python publishes
the JPEG, not at sensor exposure. An optical latency test is still needed before
claiming camera-to-action latency.

## Operator UI repair

The lab's HTTP proxy now preserves source frame ID and publication age. Browser
freshness adds request time and elapsed local monotonic time. Repeated frame IDs
cannot reset the age. A failed request makes the retained picture explicitly
STALE; missing metadata is not accepted as fresh. Only an inference from the
same frame may draw a detection box. This trades fewer overlaid boxes for honest
frame alignment; a future synchronized annotated-frame endpoint can improve it.

Telemetry says `Commanded PWM` and `Wheel speed: NOT MEASURED`. Historical
inference age is labeled `At inference`, not presented as the age now.
The running Mac lab has these changes. Unit validation: 174 Python tests and
six JavaScript freshness tests passed. The browser visibly showed CAMERA
UNAVAILABLE with no current frame. The attempted viewport override did not change
the actual 694 x 837 viewport; no new desktop/mobile coverage is claimed here.

## Why software must not conceal a wire fault

PWM controls the fraction of time a driver applies motor power. It is not a
wheel-speed measurement. Under steady load, unequal PWM can compensate for
repeatable motor differences. An intermittent contact instead changes the
electrical path unpredictably. Raising PWM does not reconnect it reliably.

The gyroscope senses chassis angular velocity. A heading controller can reduce
small drift if it has actuator authority, but one gyro cannot distinguish a
stalled front-left wheel from another fault producing similar chassis rotation.
No per-wheel current or encoder feedback is installed.

At the next supervised check, record which wheel and direction fail. If a wheel
cuts in/out with the same command, stop; inspect that motor's two joints, driver
output joints and connectors with Pi and motor power disconnected. Never wiggle
exposed live contacts as a test. A meter's stable unpowered continuity result is
useful but does not prove acceptable voltage drop under load. Only after the
electrical behavior is stable should trim or heading-hold be evaluated.

## Acceptance still required

1. Pi connectivity and camera-only deployment, with valid delivery measurements.
2. Supported object selection and fresh disarmed detection across near/far views.
3. Supervised confirmation that all four wheels respond consistently both ways.
4. Bounded approach and stop-before-contact, externally observed and recorded.

Whole-house search and physical transfer of the simulated navigation policy
remain outside these completed results; see `docs/resume-claim-validation.md`.

## Lesson and teach-back

Robotics separates commands, measurements and inference. A high PWM command is
not proof of wheel motion, a downloaded JPEG is not proof of freshness, and a
passing simulator episode is not proof of a physical mission. This same
distinction matters in production arms with encoder and drive-current feedback.

If PWM stays constant but a wheel stops intermittently, which additional
measurement would distinguish a controller decision from an electrical fault?
