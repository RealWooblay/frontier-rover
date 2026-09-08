# Persistent Jetson Autonomy Service

## Architecture

The Jetson receives Pi camera JPEGs, executes the TensorRT FP16 YOLO engine,
converts the selected box into normalized geometry, runs the target controller,
and sends normalized actions to the Pi. The Pi retains PWM, calibration, and a
350 ms watchdog.

## Safety Properties

- Starts disarmed and requires explicit ARM.
- Stale images produce zero action.
- Exceptions disarm and request zero action.
- DISARM is ordered after any in-flight action.
- Search and alignment are bounded pulses followed by explicit stop.
- A perception probe exercises camera and TensorRT without sending motion.

## Measured Probe

The deployed Jetson service loaded TensorRT 10.3 and the FP16 engine. One live
Pi frame completed in 102.77 ms: 41.63 ms preprocessing, 60.63 ms inference,
and 0.47 ms postprocessing. Observation age was 133 ms. No orange was visible;
the proposed search action was recorded with `sent:false`.

## Fresh Physical Runs

Three bounded runs automatically disarmed on timeout. The first saw three
orange frames crossing from horizontal error `+0.87` to `+0.43` to `-0.60`,
which exposed alignment overshoot. The second saw one edge detection. The third
saw zero detections across 94 service frames. These runs validate timeout and
disarm behavior but do not constitute a successful fresh target mission.

The earlier physical mandarin run remains the evidence for observed SEARCH,
ALIGN, APPROACH, and ARRIVED states. Mac-independent operation remains pending
until the Pi is physically connected to the Jetson USB device-mode network.
