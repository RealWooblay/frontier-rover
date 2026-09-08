# Jetson Perception Link

## Objective

Prove that the stationary Jetson can receive and decode live Pi camera frames
without giving it authority to move the rover.

## Architecture

```text
Pi camera -> Pi HTTP :8765 -> Mac Wi-Fi -> SSH reverse tunnel
          -> Jetson localhost:8765 -> OpenCV perception
```

The Pi watchdog remains the motor-stop authority. The perception program does
not call the motor API.

## Findings

- The Jetson boots Ubuntu 22.04 and exposes NVIDIA USB networking at
  `192.168.55.1`; the Mac receives `192.168.55.100`.
- The Jetson has no active Wi-Fi interface and Ethernet is disconnected.
- An SSH reverse tunnel exposes the Pi controller at Jetson
  `127.0.0.1:8765`.
- Jetson OpenCV 4.5.4 includes AprilTag 36h11 support through `cv2.aruco`.
- The Jetson decoded a real 360 x 640 Pi JPEG.
- Pi telemetry reported 17.4 capture fps; the sampled frame source age was
  115 ms.
- The first blank-scene pass correctly reported no tag and did not move the
  motors.
- The generated AprilTag 36h11 ID 0 was detected in all 20 physical-camera
  frames after its complete outer border was placed inside the image.
- The measured tag centre remained near `(340, 156)` in a 640 x 360 frame,
  with normalized horizontal error near `+0.061` and area ratio near `0.244`.
- A 20-frame blank-scene run measured 35 ms median and 58 ms mean warm
  successful-frame processing time, with a 125 ms worst observed pass. Median
  source-frame age was about 7 ms.
- Three geometry tests prove centred, left, right, and invalid tag-state cases.
- The Orin GPU and CUDA 12.6 toolchain are operational. A repeated CUDA pixel
  experiment measured 16.6 ms on CPU, 9.65 ms for the GPU kernel, and 53.0 ms
  for the complete copy-kernel-copy path over 16,588,800 values. CPU and GPU
  outputs matched exactly.
- OpenCV 4.5.4 was compiled without CUDA, so current AprilTag processing is on
  the CPU. The installed PyTorch currently fails to import because
  `libcusparseLt.so.0` is missing.

## State Interface

Each detection exposes tag ID, pixel centre, normalized horizontal error, and
image-area ratio. Horizontal error is a steering input. Area ratio is only a
closeness proxy until camera calibration establishes metric distance.

## Limitations

- The tunnel depends on the Mac and is not an independent deployment network.
- Successful-frame processing time does not include a complete measurement of
  skipped-frame polling and therefore is not yet the control-loop rate.
- No autonomous motion command exists yet.
- The Python neural-inference environment is not yet usable, and the current
  computer-vision path does not use the GPU.

## Next Measurement

Measure detection and state stability with the tag at left, centre, and right,
then define bounded search, align, approach, stop, and fault transitions before
connecting perception to motion.
