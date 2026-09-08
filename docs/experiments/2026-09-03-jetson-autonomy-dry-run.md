# Jetson Autonomy Dry Run

## Objective

Run the real camera-to-controller path on the Jetson while making physical
motor actuation impossible in the program under test.

## System Path

```text
Pi Camera -> Pi JPEG endpoint -> Wi-Fi -> Mac SSH relay -> USB Ethernet
          -> Jetson OpenCV -> AprilTag geometry -> deterministic controller
```

The temporary SSH reverse tunnel exposes the Pi endpoint as Jetson
`127.0.0.1:8765`. This transport still depends on the Mac and is not the final
independent rover architecture.

## Computation

OpenCV decodes each compressed JPEG, rotates it into the rover coordinate
frame, converts it to grayscale, and runs the AprilTag 36h11 detector. Four
detected corners would produce normalized horizontal error and image-area
ratio. The deterministic controller maps those observations to bounded
`forward` and `turn` values.

The dry-run executable contains no action transport and therefore cannot call
the Pi `/api/action` endpoint.

## Measurements

- Jetson USB address: `192.168.55.1`
- USB round-trip latency: approximately 1.4 ms during bring-up
- Jetson: NVIDIA Jetson Orin Nano Engineering Reference Developer Kit Super
- OpenCV: 4.5.4 with AprilTag 36h11 support
- OpenCV CUDA device count: 0
- Processed camera frames: 15, from frame 5220 through 5277
- Reported source age: 0-82 ms
- Target detections: 0 of 15 because no AprilTag was in view
- Controller result: 15 of 15 `target_lost` actions with zero forward and turn
- Pi after the run: `motion=stop`, `motor_active=false`, both outputs zero
- Pi command age after the run: 63 seconds, proving the dry run sent no command

## Interpretation

The experiment proves real frame transport, image decoding, detector execution,
controller execution, and target-loss stopping on the Jetson. It does not yet
prove steering sign from a real detection, action transport, physical watchdog
timing, TensorRT inference, or autonomous movement.

OpenCV reported zero CUDA devices, so this AprilTag stage executed on CPU. A
Jetson GPU is not used merely because code runs on a Jetson; computation must
be implemented by CUDA-enabled operators or a TensorRT engine.

## Tooling Failure Observed

`python3 -m unittest tests...` resolved `tests` to an unrelated installed
Ultralytics package. Running the repository test files directly avoided that
Python module-name collision. The controller itself was not involved in that
failure.
