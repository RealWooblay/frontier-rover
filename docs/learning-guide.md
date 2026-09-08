# Frontier Rover Learning Guide

Last updated: 2026-09-06

This is the living explanation of the rover. It records concepts, system
boundaries, measurements, and diagnostic methods so the system can eventually
be rebuilt and repaired without an assistant. It is not a session diary.

## System in One Picture

```text
Pi Camera -> Raspberry Pi -> Wi-Fi -> Jetson -> movement command
                |                         |
                |                         +-> vision and decisions
                v
         TB6612 motor drivers -> four motors -> physical motion
                ^
                |
7.2 V NiMH battery
        +-> motors through TB6612

Belkin BPB012 power bank -> 5 V USB-C -> Raspberry Pi
```

The Jetson remains on its supplied wall power during the learning build. The
rover is mobile because only the Pi, camera, motor drivers, and batteries ride
on the chassis. Separate Pi and motor batteries isolate the Pi from direct
motor-power voltage drops during development.

## What Each Computer Does

### Raspberry Pi: hardware controller

- Reads bounded movement commands.
- Converts commands into motor direction and PWM signals.
- Stops the motors when commands become stale.
- Reports hardware state and faults.

The Pi is close to the hardware and owns the safe stopped state.

### Jetson: perception and decisions

- Receives camera frames.
- Detects AprilTags and other visual features.
- Chooses actions such as search, align, approach, and stop.
- Sends time-limited commands to the Pi.

The Jetson may request motion, but it must not be the only component capable of
stopping the motors.

### Why the Jetson exists

The Jetson is not a more expensive Raspberry Pi and it does not make an AI
algorithm possible in principle when a laptop could never run it. Its value is
deployment: it combines an ARM computer with an NVIDIA CUDA GPU and tensor
cores in a compact 7-25 W embedded system. Models developed on a workstation
can therefore run near the robot's sensors with low latency, without cloud
access, using NVIDIA tools such as CUDA, TensorRT, DeepStream, and Isaac ROS.

The Pi remains the hardware and safety controller because GPIO motor control is
lightweight and must fail to a stop. The Jetson is the perception computer
because image decoding, neural-network inference, visual tracking, and SLAM are
parallel numerical workloads suited to its GPU.

For the current small chassis, the Jetson stays off the rover and receives a
compressed camera stream over Wi-Fi. This teaches the same perception-command
boundary without adding the Jetson's mass and power system to the rover. A
larger future platform could carry it and run the same perception locally.

Robotics computers form a hierarchy rather than replacing one another:

```text
Microcontroller / flight controller: deterministic sensor and actuator loops
Raspberry Pi: embedded Linux, GPIO, networking, device orchestration
Jetson: GPU perception, mapping, planning, and learned policies
Laptop/cloud: development, simulation, training, and fleet analysis
```

One device may cover multiple layers in a low-risk prototype, but
safety-critical systems preserve the lower control layer when higher-level
Linux or AI software fails. On a drone, for example, a PX4 flight controller
stabilises attitude and owns failsafes while a Pi or Jetson companion computer
requests higher-level motion. The Jetson does not replace that flight
controller.

The staged learning path is:

1. Stream the Pi camera and measure latency and frame rate.
2. Run object detection on the Jetson and draw detections without moving.
3. Convert target position into a bounded steering request.
4. Add a state machine: search, align, approach, stop, and fault.
5. Use AprilTags for measurable target pose and repeatable docking.
6. Later learn ROS 2, sensor fusion, and visual SLAM with suitable depth or
   stereo sensing; the current single Camera Module 3 is not a stereo camera.

## Camera Bring-Up

The Raspberry Pi Camera Module 3 is verified on the Pi 4. The working Pi boot
configuration uses one explicit device-tree overlay:

```text
camera_auto_detect=0
dtoverlay=imx708
```

This tells the boot firmware to describe one IMX708 sensor to Linux instead of
trying to identify the camera automatically. The kernel then binds the IMX708
driver, exposes it through the Pi Unicam and ISP media devices, and `rpicam`
uses libcamera to capture images.

The initial failure was physical ribbon orientation. Linux created the correct
IMX708 device and attempted I2C reads, but both the image sensor and autofocus
controller returned error `-5`, meaning no electrical acknowledgement. After
the ribbon was reversed into its working orientation, the kernel read camera
module ID `0x0301`, `rpicam-hello --list-cameras` reported the IMX708, and a
1920x1080 JPEG capture succeeded.

Use the connector contacts as the invariant: the ribbon's exposed metal pads
must meet the socket's spring contacts, the cable must be fully and evenly
inserted, and the latch must close squarely. Do not infer orientation only from
the blue stiffener because descriptions of its direction caused confusion in
this build.

The diagnostic layers were:

```text
boot configuration -> device-tree camera node -> kernel I2C probe
                   -> libcamera enumeration -> real JPEG capture
```

Continuity and a measured 3.3 V supply proved only that the cable carried power;
they did not prove that the I2C contacts were meeting the connector. Successful
chip-ID reading proved the control link, and the JPEG proved the complete image
path. The first image was clear but rotated 90 degrees, so orientation correction
was a software presentation task rather than a camera-detection fault.

### Live camera path

The operator console now uses this baseline video path:

```text
IMX708 sensor -> CSI-2 -> Unicam/ISP -> rpicam-vid -> MJPEG byte stream
             -> Python latest-frame buffer -> HTTP JPEG -> browser canvas
```

`rpicam-vid` captures 360 x 640 portrait frames with continuous autofocus and
JPEG compression at a configured 15 fps. The browser rotates each frame by a
quarter turn to produce a 640 x 360 landscape view. Capturing in portrait first
matters because a 90-degree rotation swaps width and height. The Python
controller parses consecutive
JPEG images from the MJPEG byte stream and retains only the newest complete
frame. It deliberately discards old frames: displaying every queued frame
would produce smooth but increasingly stale vision, which is dangerous for a
moving robot.

The browser requests `/api/camera/frame.jpg` with the last frame number it has
seen. The server returns `204 No Content` when there is no newer frame, avoiding
duplicate image decoding. A new frame includes `X-Frame-Id` and
`X-Frame-Age-Ms` headers. The browser decodes the JPEG, rotates it on a canvas,
and draws a reticle. Rotation is presentation state stored in browser local
storage; it does not modify the sensor data that a future Jetson pipeline will
receive.

The camera worker and motor watchdog are independent. Camera capture may stop
or restart without extending a movement command. The motor watchdog still
requires commands every 100 ms and stops output after 350 ms without a fresh
command.

Measured on 2026-08-31:

- Valid 360 x 640 JPEG frames from the Pi HTTP endpoint, displayed as 640 x 360.
- 15.1 capture fps after steady state.
- 32 ms latest-frame age in telemetry; browser samples observed 2-72 ms.
- Wi-Fi signal: -43 dBm during the final measurement.
- Pi temperature: 45.8 C; memory use: 14.0%.
- Controller service active; motor state stopped with zero output.

Frame age measures capture-to-HTTP availability, not complete glass-to-glass
latency. A future experiment must film a physical timestamp or flashing LED and
compare it with the displayed frame to measure sensor exposure, processing,
network, decoding, and display delay together.

### Jetson perception link

The Jetson is reachable from the Mac through NVIDIA USB device-mode networking:

```text
Mac 192.168.55.100 -> USB-C -> Jetson 192.168.55.1
```

The Jetson has no active Wi-Fi interface, and its Ethernet interface is
disconnected. For the current bench experiment, an SSH reverse tunnel maps
Jetson `127.0.0.1:8765` through the Mac to Pi `192.168.0.87:8765`. This carries
the existing HTTP camera and command API without enabling general packet
forwarding on macOS. It is suitable for learning but depends on the Mac and is
not the final independent network design.

The Jetson successfully fetched Pi telemetry and decoded a real 360 x 640 JPEG
using OpenCV 4.5.4. The measured Pi capture rate was 17.4 fps and that sampled
frame arrived with 115 ms source age. OpenCV includes the AprilTag 36h11
dictionary through its ArUco module.

Across 20 blank-scene perception passes, the first cold pass took 907 ms. The
remaining successful-frame passes had about 35 ms median processing time, 58 ms
mean processing time, and 125 ms worst observed time. Their median source age
was about 7 ms. These are component timings, not yet a measured end-to-end
detection update rate.

The first perception program rotates the raw portrait frame 90 degrees
counter-clockwise into the same forward landscape orientation used by the
operator UI. For each detected tag it calculates:

```text
horizontal_error = (tag_center_x - image_center_x) / image_half_width
area_ratio       = tag_pixel_area / image_pixel_area
```

`horizontal_error` is `0` when centred, negative on the left, and positive on
the right. `area_ratio` is a closeness proxy, not physical distance. Distance
requires a known tag size and camera calibration. The program currently emits
measurements only and has no path to the motor API.

### Jetson compute stack

GPU execution has several separate layers:

```text
Rover application
    -> OpenCV, PyTorch, or another compute library
    -> CUDA runtime and NVIDIA driver
    -> Orin GPU
    -> shared LPDDR memory
```

The Jetson is an Orin Nano Super developer kit with six ARM Cortex-A78AE CPU
cores and 7.4 GiB of usable shared memory. It runs NVIDIA L4T 36.4.7 and has
CUDA 12.6 installed. The CUDA compiler exists at
`/usr/local/cuda-12.6/bin/nvcc`, although that directory is not currently in
the shell's command path.

The installed OpenCV 4.5.4 reports no CUDA support. Consequently, the current
JPEG decoding and AprilTag detection execute on the CPU. Merely running a
program on a Jetson does not move it to the GPU. The chosen library must have a
GPU implementation, and the application must explicitly submit data and work
to that implementation.

The `cuda_pixel_pipeline.cu` experiment applied the same brightness transform
to 16,588,800 values on the CPU and GPU. After the cold first execution, the
CPU loop took 16.6 ms and the CUDA kernel took 9.65 ms, a 1.72x kernel
speedup. The complete GPU path took 53.0 ms because data transfer and
synchronization outweighed the saving from this simple operation. Both paths
produced identical output.

The first CUDA kernel measurement took 386.5 ms and the immediate repeat took
9.65 ms. This proves the first result was transient, but does not by itself
separate CUDA context initialization, code loading, and clock ramp-up. Systems
with latency requirements must warm up and measure steady-state behaviour.

The installed PyTorch package currently cannot import because
`libcusparseLt.so.0` is missing. This is a software-stack dependency problem,
not evidence of a faulty GPU. It must be repaired before using PyTorch models.

The practical optimization lesson is to keep image data in GPU-accessible
memory across preprocessing, inference, and postprocessing. Copying data to
and from the GPU for every small operation can be slower than using the CPU.

TensorRT 10.3 successfully compiled the official ONNX ResNet-50 v2 classifier
into a 49.4 MiB FP16 Orin engine. The build took 111.9 seconds because TensorRT
profiled and selected GPU implementation tactics. The resulting engine then
ran at 2.70 ms median GPU compute and 2.76 ms median host latency in `trtexec`.

The application-level Python path measured 42.7 ms preprocessing, 92.5 ms cold
inference, 3.95 ms median warm inference, and 6.30 ms warm p95 inference.
NVIDIA's sample cat image was classified as `tabby` with 69.1% probability.
This validates image decoding, RGB normalization, NCHW tensor layout, engine
execution, output transfer, softmax, and label lookup together.

ResNet-50 is a classifier: it answers which learned category dominates the
image but not where the object is. A rover needs object detection,
segmentation, or geometric tracking to obtain spatial state for control.

### Synthetic perception training

PyTorch was repaired without changing system CUDA files by placing NVIDIA
cuSPARSELt 0.6.2.3 in the user's local directory and activating it through the
project's explicit `run_with_ai_env.sh` launcher. PyTorch 2.5 then detected the
Orin GPU and completed a CUDA tensor operation. This cuSPARSELt version was
selected because it supports Orin compute capability 8.7 and its NVIDIA
archive checksum was verified before extraction.

The first learned rover-specific experiment generates synthetic 160 x 96
grayscale AprilTag scenes. The renderer knows the tag's exact horizontal
position, so it produces both the image and its supervised label without manual
annotation. Random size, rotation, brightness, background gradient, blur, and
noise provide limited domain randomization.

A 497,665-parameter convolutional neural network was trained on 6,000 images
for ten epochs and validated on 1,200 separately seeded images. GPU training
took 17.67 seconds. Validation mean absolute error fell from 0.0683 after the
first epoch to 0.00984 after the tenth epoch.

The trained PyTorch model was exported to ONNX and compiled into a 1.01 MiB
TensorRT FP16 engine. On a second 512-image synthetic set, PyTorch MAE was
0.010013 and TensorRT MAE was 0.010041. Their maximum prediction disagreement
was 0.000700, showing that export and FP16 optimization preserved the learned
function closely.

This is synthetic supervised perception, not a learned driving policy. It
assumes a tag is present and has not been validated on real camera frames. The
deterministic AprilTag detector remains the baseline and learned output must not
control motors until real-data error and missing-target behaviour are measured.

### Prototype versus product

The current rover proves a control chain: a command can travel through software,
GPIO, motor drivers, and motors to create physical motion. That is a meaningful
prototype milestone, but it is not yet autonomous delivery.

A deployable product must repeatedly complete a customer's task while handling
lighting changes, obstacles, wheel slip, sensor faults, flat batteries, lost
networks, damaged wiring, weather, misuse, and recovery. It also needs an
enclosure, service procedures, security, logging, remote intervention, legal
permission, insurance, and viable unit economics.

Reliability compounds across a system. As a simplified illustration, ten
independent stages that each succeed 99% of the time produce only
`0.99^10 = 90.4%` end-to-end mission success. A commercial system therefore
needs better component reliability, fault detection, redundancy where safety
requires it, and graceful recovery instead of merely working in the expected
case.

The practical route to a business is to narrow the environment and sell an
outcome before attempting general autonomy:

1. Find one expensive, repetitive inspection or transport task.
2. Teleoperate the rover and measure whether the task creates customer value.
3. Record failures and collect real sensor data.
4. Automate one repeatable part while retaining human takeover.
5. Measure mission completion, interventions, operating cost, and safety.
6. Expand autonomy only when those measurements justify it.

## The Electrical Model

### Voltage, current, and power

- **Voltage (V)** is electrical potential: the push available to move charge.
- **Current (A)** is the rate of charge flow.
- **Resistance (ohms)** opposes current.
- **Power (W)** is the rate of energy use.

The two basic relationships used in this build are:

```text
current = voltage / resistance       I = V / R
power = voltage * current            P = V * I
```

Voltage compatibility is not enough. A device can have the correct voltage but
still fail because the source, wire, connector, or driver cannot carry the
required current.

### Logic path versus power path

```text
Logic path: Pi GPIO -> TB6612 input pins
Power path: battery -> TB6612 output stage -> motor
```

Dupont wires are acceptable for logic signals. They are not acceptable for
battery or motor current. The 18 AWG pigtail wire is used for the power path.

### Why a motor driver exists

A GPIO pin produces a small 3.3 V logic signal. A motor needs much more current
and produces electrical noise when switched. Connecting a motor directly to a
GPIO pin would damage the Pi.

The TB6612FNG is an H-bridge. It uses GPIO signals to switch battery current,
reverse motor polarity for direction, and apply PWM for speed control.

### Observed TB6612 module pinout

The labels were read directly from one owned module on 2026-08-26.

```text
Control side              Power and motor side
------------              --------------------
PWMA                      VM
AIN2                      VCC
AIN1                      GND
STBY                      AO1
BIN1                      AO2
BIN2                      BO2
PWMB                      BO1
GND                       GND
```

The functions are:

- `VM`: motor power from the battery.
- `VCC`: 3.3 V logic power from the Raspberry Pi.
- `GND`: the shared zero-volt reference for battery, driver, and Pi logic.
- `AO1` and `AO2`: the two wires for motor A.
- `BO1` and `BO2`: the two wires for motor B.
- `AIN1` and `AIN2`: select motor A direction or braking state.
- `BIN1` and `BIN2`: select motor B direction or braking state.
- `PWMA` and `PWMB`: pulse-width-modulated speed commands.
- `STBY`: master enable. Low disables the motor outputs; high enables them.

The two printed ground pins are expected to be connected on the module, but
that must be verified with the multimeter before power is applied.

Verification on 2026-08-26 measured 1.0 ohm between the control-side ground and
a power-side ground, exactly matching the 1.0 ohm probe resistance. After probe
correction, the module connection is therefore approximately zero ohms. The
ground pins are confirmed internally common.

### Assembled connection state

Two TB6612 modules are now soldered, wired to all four motors, and connected to
the Pi GPIO header. Each motor has been proven in both directions. The motor
battery feeds both boards in parallel through the assembled Tamiya and barrel
connections. The Belkin power bank powers only the Pi.

A plated through-hole is a copper-lined opening connected to a PCB trace. A
wire or pin merely touching it is not a reliable electrical or mechanical
connection. Solder must wet both the pad and the inserted conductor to form a
low-resistance joint.

The planned connection methods are different because the currents are
different. No separate header strips are present; only the owned Dupont jumper
wires are available:

```text
Pi control signals -> male end of M-F Dupont wire soldered into board
                   -> female end plugged onto Pi GPIO header
Battery and motors -> directly soldered 18 AWG wire -> insulated joints
```

Power connections avoid Dupont wires because contact resistance produces
voltage loss and heat according to `P = I^2 R`.

Available assembly tools include a soldering iron and leaded solder. Dedicated
wire cutters and strippers are not available. A knife should not be used for
initial wire preparation because it can nick conductor strands and slip toward
the user's hand.

A male Dupont pin fits physically through a plated hole, but the hole has no
spring contact. That is why the signal leads were soldered to the boards rather
than left loose.

### Why the LM2596 exists

The battery is nominally 7.2 V. The Raspberry Pi requires a stable supply near
5 V. The LM2596 is a buck converter: it reduces a higher DC voltage to a lower
DC voltage.

Its adjustment screw does not know what is connected. The output must be set to
5.1 V with a multimeter before the Pi is connected, then checked again under
load. Reversing polarity or applying 7.2 V directly to the Pi can destroy it.

### LM2596 module anatomy

The owned modules have four labelled power connections:

- `IN+` and `IN-` receive battery power.
- `OUT+` and `OUT-` provide the reduced voltage.

The round `100 uF 50 V` part on the input and `220 uF 35 V` part on the output
are electrolytic capacitors. They store small amounts of energy and smooth
voltage changes and switching noise. Their voltage markings are maximum part
ratings, not the voltage produced by the module. They are not controls and must
not be twisted.

The output control is a separate small potentiometer, normally a rectangular
part with an adjustment screw. It changes the regulator's feedback ratio and
therefore the output voltage. The output must always be measured while this
screw is adjusted.

The owned module's potentiometer is marked `W103`. The `103` resistance code
means `10 x 10^3`, or approximately 10,000 ohms. This resistance is part of the
voltage-feedback network; the marking does not mean the converter outputs
10,000 V or 10,000 A.

## Why We Measure Motor Resistance

A stopped motor initially behaves approximately like a low-value resistor. Its
largest current occurs at stall, when it cannot rotate.

```text
estimated stall current = battery voltage / winding resistance
```

The estimate is intentionally conservative. We compare it with the TB6612's
current limits before applying power. This turns an unknown hardware risk into
a measured design decision.

## Control and Data Loop

### Network and recovery paths

The normal control path uses the existing 5 GHz network, so the development
computer retains internet access:

```text
Mac or Jetson -> Optus 5 GHz router -> frontier-pi.local -> browser control :8765
```

Two independent permission failures overlapped. The Pi setup script selected
`umask 077` while writing the secret Wi-Fi configuration but failed to restore
the normal mask. `netplan generate` therefore created its non-secret
`10-netplan-*.network` files with mode `0600`. After startup,
`systemd-networkd` runs as the `systemd-network` user and logged `Permission
denied` when it reloaded those root-only files. It then selected Dracut's
generic DHCP fallback, obtained a different address, and removed the USB IPv4
address.

After that Pi fault was repaired, macOS still returned `No route to host` for
direct Wi-Fi and USB connections. Packet capture proved that the Mac sent no
packet, while the Pi could initiate traffic back to the Mac. The decisive host
setting was **Privacy & Security > Local Network > ChatGPT**, which was off.
Turning it on immediately restored both direct paths. The temporary route
through the Optus gateway worked only because it avoided a direct local-link
connection; it was removed after the permission was enabled.

The Pi repair scopes `umask 077` to the secret source file. On a verified clean
boot, Netplan generated mode `0640` files owned by `root:systemd-network`, so
Networkd could read them. The repair also disables the completed one-time
bootstrap and removes its temporary credential files. The verified current
Wi-Fi lease is `192.168.0.87`; clients should normally use
`frontier-pi.local` rather than embedding that DHCP address.

Battery proximity, tape placement, and router isolation were hypotheses, not
causes. The evidence identified one Linux permission error and one macOS local
network permission setting.

The USB-C connection is a separate recovery path. The Pi presents a USB
Ethernet interface at `10.55.0.2`, while the Mac uses `10.55.0.1`. USB gadget
enumeration and IP setup are separate: the Mac can see the Ethernet device even
when the Pi has not assigned its address. `frontier-usb-recovery.service`
therefore waits for `usb0`, brings it up, and assigns `10.55.0.2` explicitly.
This gives direct SSH access even when router forwarding or Wi-Fi is
unavailable.

### Why clean shutdown matters

Linux writes files through an ext4 journal. Removing power during a write can
leave journal and allocation metadata inconsistent. The card may then need an
offline `e2fsck` repair. From the Mac, run
`ssh -t rover@frontier-pi.local 'sudo shutdown -h now'`, enter the Pi password,
wait for SSH to disconnect, then wait at least 20 seconds before removing
power. Merely seeing the SSH login banner means only that login succeeded; it
does not prove that a second pasted command executed.

### Browser control and dead-man safety

The Pi serves the operator page on port `8765`. Holding a direction sends a
fresh HTTP command every 100 ms. The browser is an input device, not the motor
controller. The Python process on the Pi validates each command, translates it
to left and right PWM values, and drives the TB6612 GPIO pins. Releasing the
button sends STOP. Independently, the Pi stops the motor outputs if no fresh
command arrives for 350 ms. This is a dead-man control: continued movement
requires continued communication.

```text
button held in browser
  -> POST /api/command {motion, throttle}
  -> Python watchdog on Pi
  -> logical left/right speed
  -> GPIO direction + PWM
  -> TB6612 switches motor-battery power
  -> wheels move
```

The operator console also reads two endpoints. `/api/status` reports the
current command and applied motor outputs. `/api/telemetry` reads real Pi state:
temperature, memory use, uptime, Wi-Fi address and signal, camera detection,
and Ethernet carrier for the future Jetson link. An unavailable sensor is
reported as unavailable; the UI does not invent a healthy value.

The speed slider is a multiplier around the physical calibration. The values
currently saved on the Pi are 80% PWM on the left and 100% on the right. At a
50% slider setting, the same command applies 40% left and 50% right. This
preserves the saved ratio
while changing overall speed:

```text
applied PWM = calibrated PWM * operator throttle
```

Left and right straight calibration can be edited in the operator console.
Pressing Apply first stops the motors, validates both values as percentages
from 0 to 100, and sends them to `POST /api/calibration`. The Pi stores the
result in `/var/lib/frontier-rover/motor-calibration.json`, so calibration
survives browser reloads and Pi reboots. The browser does not become the source
of truth; it edits the controller's saved configuration.

### From a speed number to a turning motor

The software represents each side's requested motion as a number from `-1.0`
to `1.0`. The sign selects direction and the magnitude selects PWM duty cycle:

```text
-0.60 = reverse direction, 60% PWM
 0.00 = stopped
+0.60 = forward direction, 60% PWM
```

For each motor, `MotorChannel.prepare()` converts that number into three TB6612
inputs. Positive speed raises `IN1`, negative speed raises `IN2`, and the
absolute value is written to `PWM`. Some motors are mounted or wired in the
opposite physical orientation, so their `inverted` setting reverses the sign
before those outputs are selected.

```text
STBY  IN1  IN2  PWM       Result
-----  ---  ---  --------  -----------------------------
0      x    x    x         driver disabled
1      1    0    0.60      forward at 60% duty cycle
1      0    1    0.60      reverse at 60% duty cycle
1      0    0    0.00      motor output stopped
```

PWM does not reduce the battery to a steady lower voltage. At the configured
1 kHz frequency, the TB6612 connects and disconnects the 7.2 V motor supply
1,000 times per second. A 60% command means the battery is connected for 60% of
each cycle. The motor's electrical inductance and mechanical inertia smooth
those pulses into torque and rotation. Duty cycle influences speed and torque,
but it is not a direct measurement of either.

`RoverDrive.set_tank(left, right)` sends the same left value to both left
motors and the same right value to both right motors. Forward uses two positive
values; reverse uses two negative values. A left turn drives the left wheels
backward and right wheels forward, while a right turn does the opposite. This
is differential, or tank, steering.

The current GPIO mapping is defined in `software/pi/drive.py`:

```text
Motor         Direction GPIOs  PWM GPIO  Software inversion
------------  ---------------  --------  ------------------
front-left    17, 27           18        no
back-left     22, 23           19        yes
front-right   16, 20           13        no
back-right    5, 6             12        yes
left STBY     24
right STBY    25
```

The Pi GPIO carries only 3.3 V control information. The TB6612's H-bridges do
the high-current work by switching the separate motor battery across each
motor in either polarity. The shared ground gives the Pi and both drivers the
same reference for what logic low and logic high mean.

### Safe shutdown from the operator console

The controller runs as the unprivileged Linux user `rover` with
`NoNewPrivileges=yes`. It is deliberately unable to run arbitrary commands as
root. A confirmed shutdown request first stops the motors, then creates only
`/run/frontier-rover/poweroff`. A root-owned systemd path unit watches for that
specific file and invokes `systemctl poweroff`.

```text
confirmed UI action -> unprivileged marker file -> root systemd path unit
                    -> clean Linux poweroff
```

This is a narrow privilege boundary. Compromising the HTTP controller does not
provide general `sudo` access. The confirmation dialog prevents an accidental
tap from shutting down the Pi.

The watchdog was tested by sending one forward command and then sending
nothing. Its status changed to stale and the motor outputs returned low after
the timeout. This software test was performed with the motor battery removed.

### Four-motor direction calibration

Individual floor-direction tests confirmed back-left and front-left move
forward with a positive left command. Front-right also moves forward, while
back-right requires inverted polarity in software. Back-left also requires the
same inversion because of its terminal orientation. Direction inversion is
a calibration between logical `forward` and physical motor installation; it
does not indicate a damaged motor.

The physical left-side channel labels were also verified: channel A controls
front-left and channel B controls back-left. The initial notes had those names
reversed; the GPIO wiring itself was correct.

Equal PWM did not drive straight because nominally identical motors, gearboxes,
wheels, chassis load, and wiring do not produce identical physical speed. A
loose back-right connection also caused an asymmetric forward fault and was
repaired before final calibration.

The first confirmed open-loop straight calibration was 40% PWM left and 60%
PWM right. After later floor testing, the values currently saved on the Pi are
80% left and 100% right at full slider speed. Turning currently uses 50% per
side in opposite directions. PWM percentage describes electrical duty cycle,
not measured wheel speed. Moving wiring or changing wheel friction can alter
the required trim; closed-loop wheel encoders would eventually correct this
from measurement instead of a fixed ratio.

```text
camera frame
  -> perception result
  -> desired rover motion
  -> bounded command with timestamp
  -> motor output
  -> observed motion
  -> next camera frame
```

This is feedback. The system does not merely command movement; it observes the
result and corrects its next action.

## Diagnostic Order

When something fails, check layers in this order:

1. Is the correct voltage present?
2. Is polarity correct?
3. Can the source supply the required current?
4. Is there a shared ground between logic devices?
5. Are control signals reaching the expected pins?
6. Is software producing the expected command?
7. Is the physical result consistent with the command?

Do not rewrite software before proving the electrical and signal layers.

## Current Learning Checkpoint

### Proven

- The Pi boots Ubuntu ARM64, joins 5 GHz Wi-Fi at `192.168.0.87`, and is
  reachable directly over USB SSH at `10.55.0.2`.
- Direct USB Ethernet recovery works at `10.55.0.2`.
- Both SSH and the controller are reachable through `frontier-pi.local` and
  through USB recovery in the same boot.
- Netplan's generated Networkd files are readable by the Networkd service;
  the failed one-time bootstrap is disabled and no failed units remain.
- macOS Local Network access is enabled for ChatGPT, and temporary host routes
  and static neighbour entries are no longer required.
- With USB networking disabled, direct Wi-Fi passed 300 controller requests
  and 30 SSH checks over five minutes with zero failures; USB recovery was then
  restored and reverified.
- The Pi can be shut down cleanly without corrupting the SD card.
- The selected battery and charger use compatible chemistry, cell count, and
  Tamiya connectors.
- All four motors run individually in both directions through the two TB6612
  boards.
- Both side pairs run under floor load.
- Pulsed forward and reverse movement work using the temporary 8% left / 80%
  right calibration.
- The Belkin BPB012 is rated to provide 5 V/3 A over USB-C to the Pi.
- The Pi has booted from the Belkin with no Mac cable, joined 5 GHz Wi-Fi at
  `192.168.0.87`, and exposed SSH and the controller without undervoltage or
  storage errors in that boot log.
- The browser controller starts automatically and is reachable over USB at
  `http://10.55.0.2:8765`; its 5 GHz address is
  `http://192.168.0.87:8765`.
- All 32 controller, camera, and motor-mapping unit tests pass on the Pi.
- Three AprilTag state-geometry tests pass on both the Mac and Jetson.
- The Jetson receives and decodes live Pi camera frames through the USB/SSH
  tunnel while Pi motor output remains zero.
- The Jetson detected physical AprilTag 36h11 ID 0 in 20 of 20 camera frames;
  the complete outer border and four corners must remain visible.
- The command watchdog stops stale commands after 0.35 seconds in the
  motor-power-disconnected test.
- The TensorRT YOLO engine detects the pretrained COCO `orange` class on the
  Jetson and supplies normalized box geometry to the shared controller.
- The MuJoCo rover uses the same observation/action controller interface and
  completed 20/20 seeded randomized target scenarios with the current physical
  controller parameters.
- Physical closed-loop telemetry contains SEARCHING, ALIGNING, APPROACHING,
  and ARRIVED. In the accepted run, median perception time was 53.63 ms,
  median command transport was 20.57 ms, and maximum target area was 0.140.
- Persistent heading control completed `+45/-90/+45` with `2.2 degrees`
  maximum error and `-1.9 degrees` net return error.
- A measured Real2Sim fit reduced held-out turn RMS error from 36.51 to 14.34
  degrees.
- The accepted contact-world learned policy completed 33/40 held-out randomized
  MuJoCo missions with zero contact episodes, versus 32/40 and 36 contacts for
  the deterministic expert. It completed 10/12 forced-stall missions with zero
  contacts. The earlier 39/40 result used simplified analytic collision logic.
- The learned policy artifact's checksum and inference output were verified on
  the Jetson.
- The enabled Jetson service loaded TensorRT, completed perception-only probes,
  and safely disarmed three bounded timeout runs.

### Current acceptance work

- Place a clearly visible orange in a controlled floor area and repeat the
  persistent service mission through ARRIVED.
- Connect the Pi USB host directly to the Jetson USB device-mode port and prove
  camera/action transport without the Mac tunnel.
- Add physical observations corresponding to simulated forward velocity and
  obstacle clearances before arming the learned navigation policy.

### Not yet proven

- Sustained four-motor current and driver-temperature behaviour.
- Pi-to-Jetson transport independent of the development Mac's SSH tunnel.
- Physical raised-wheel watchdog stop behaviour.
- A fresh physical target mission proving that ARRIVED remains latched.
- Fitted linear motion, contact friction, delay, and wheel-slip parameters.
- Physical learned-policy waypoint following, obstacle avoidance, and recovery.

### Motor-characterisation result

The four corrected winding resistances are 5.2-5.5 ohms. Estimated stall
current is approximately 1.31-1.38 A at nominal battery voltage and 1.53-1.62 A
when the battery is fully charged. This conditionally approves one motor per
TB6612 channel for short raised-wheel tests, but not sustained stalls or final
four-motor operation.

### Manual pulse versus motor program

The first movement used direct `pinctrl` commands because that kept the initial
test small and observable. The repeatable Python command now owns the same four
signals and adds PWM speed control, a ten-second duration limit, signal
handling, and an unconditional cleanup step. The unconditional cleanup is the
important safety property: normal completion, an error, or interruption all
lead to PWM, both direction inputs, and `STBY` being lowered.

## Questions to Be Able to Answer

1. Why can the battery power a motor but not connect directly to the Pi?
2. What is the difference between a logic wire and a power wire?
3. Why is stall current higher than running current?
4. What must happen when Wi-Fi communication stops?
5. Why do we test one raised motor before four motors on the floor?

If any answer is unclear, revisit that section before the corresponding
hardware test.

## Deterministic Autonomy Baseline

The first autonomy controller deliberately contains no learned policy. It maps
an observed target into two normalized outputs:

```text
horizontal_error = (target_x - image_centre_x) / image_half_width
turn = clamp(turn_gain * horizontal_error)
distance_error = (desired_area - observed_area) / desired_area
forward = max_forward * clamp(distance_error)
```

Apparent tag area is initially a proximity proxy, not a metric distance. The
controller first aligns if the horizontal error exceeds its tolerance, then
approaches. Missing targets enter a pulsed in-place search. Camera frames older
than 300 ms produce zero output. Arrival latches zero output for the rest of
the mission. The current physical calibration uses 70 ms turn pulses, a 0.30
minimum turn command to overcome drivetrain deadband, and a 0.15 alignment
tolerance.

This baseline matters because later learned policies need a measured comparison.
If a neural policy cannot outperform a simple explainable controller on held-out
missions, adding the neural model has not improved the system.

### Camera sequence restart semantics

Camera frame numbers are process-local sequence counters. Restarting the Pi
controller returns its frame counter to zero while an already-open browser can
still remember a much larger previous number. The original endpoint returned
no content whenever `server_frame <= browser_frame`; after a restart that made
the browser wait until the new counter caught up, appearing as a frozen image.

The endpoint now returns no content only when the counters are equal. A browser
counter greater than the server counter indicates a restarted producer, so the
current JPEG is returned and the browser resynchronizes. The live verification
recovered from browser frame 150432 to server frame 83 and then advanced to 106
without reloading the page.

### Continuous autonomy action boundary

Manual commands name fixed motions. Autonomy instead sends normalized
`forward` and `turn` values. The Pi mixes them into left/right wheel commands,
applies physical side calibration, and rejects values outside `[-1, 1]`.
Nonzero actions still expire after 350 ms. This means perception or policy code
can fail without retaining indefinite motor authority.

### First Jetson controller dry run

The Jetson processed 15 live Pi camera frames through the Mac's temporary SSH
relay. With no AprilTag visible, every observation produced `target_lost` and
zero action. The Pi command age continued increasing and its motor outputs
remained zero, which distinguishes calculating an action from transmitting one.

This OpenCV build reported zero CUDA devices. AprilTag detection therefore ran
on the Jetson CPU. GPU acceleration is explicit: a computation must be provided
by CUDA-enabled code or compiled into a TensorRT engine. Running ordinary Python
on a Jetson does not automatically move that computation onto its GPU.

### First physical lemon annotations

The `2026-09-03-train-b` capture contains ten images. Seven images have valid
one-class YOLO bounding-box labels, and visual overlay inspection confirms that
every saved box tightly covers the visible lemon. Frames 3, 4, and 10 are
near-duplicates and can be excluded. Frame 6 contributes a verified close-left,
clipped view. Frames 1 and 2 are duplicates; only one should enter the curated
dataset so repeated camera frames do not inflate the apparent amount of
independent evidence.

A YOLO label row stores `class_id x_center y_center width height`, with the four
box values normalized by image width and height into the range `[0, 1]`.
Structural validation proves that the file can be parsed; overlay inspection is
still required to prove that the numbers identify the intended object.

### Direct browser dataset capture

Lemon dataset collection now follows `Pi camera -> Wi-Fi JPEG -> Mac browser
canvas -> local dataset`. The browser rotates the Pi camera response into the
canonical 640 x 360 orientation, waits through a visible five-second countdown,
encodes that canvas as JPEG, and posts it to the local annotation server. The
server validates the session name, payload size, and JPEG boundaries before
assigning a sequential filename without overwriting an earlier capture.

The Jetson is intentionally absent from this acquisition path. It will later
run training experiments and deployed inference, but it is not required merely
to record supervised examples. This reduces failure points while preserving the
actual rover camera viewpoint used at deployment.

### First physical object-search mission

The Jetson ran TensorRT YOLO against the Pi camera and commanded the Pi through
the bounded `forward`/`turn` API. Early runs exposed two real-system effects
that the original 50 ms simulation loop did not represent: network/camera delay
kept turns active too long, while low-amplitude pulses failed to overcome motor
and gearbox stiction. The controller now separates turn amplitude from turn
duration: sufficient PWM provides torque, while a 70 ms pulse limits angular
movement before the next observation.

An early run recorded 48 SEARCHING, 10 ALIGNING, 8 APPROACHING, and 1 ARRIVED
updates. Detection noise subsequently restarted motion, so ARRIVED became a
latched terminal state. Later testing exposed a separate geometry problem:
apparent area alone could remain below its threshold until the floor target
passed beneath the camera and disappeared.

The current controller therefore uses two monocular proximity signals:

```text
area_ratio        = bounding_box_area / image_area
bottom_edge_ratio = bounding_box_bottom_y / image_height
```

For the downward-angled camera, a floor object's box moves toward the image
bottom as the rover approaches. Mission 13 stopped at bottom-edge ratio 0.923
and area ratio 0.081, while the complete mandarin remained visible. Bottom-edge
arrival also requires area above 0.030 so a tiny distant detection at the edge
cannot trigger a false arrival. Approach pulse duration decreases from 150 ms
toward 50 ms as area grows, reducing distance travelled between close-range
measurements.

### MPU-9250 hardware identity

The Pi's I2C controller `/dev/i2c-1` addressed the installed GY-9250 breakout
at `0x68`. Reading register `WHO_AM_I` (`0x75`) returned `0x71`, the expected
MPU-9250 identity. This transaction validates the complete digital path: sensor
power and ground, clock and data wiring, Linux I2C configuration, address, and
register communication.

The IMU reports signed 16-bit integers, not physical units. With the configured
full-scale ranges, acceleration is converted using 16,384 counts per `g` and
angular velocity using 131 counts per degree/second. Gyroscope rate can be
integrated to estimate a change in heading, but constant bias is integrated too
and therefore creates heading drift. Stationary bias measurement comes before
closed-loop turning or Real2Sim dynamics fitting.

The first 100-sample stationary baseline at 20 Hz measured gyroscope bias of
`(0.695, 1.254, 0.612) degrees/second` and noise standard deviation of
`(0.099, 0.119, 0.070) degrees/second` for sensor X, Y, and Z. A representative
acceleration vector had magnitude about `1.03 g`, which is physically plausible
for a stationary sensor measuring gravity. Unit conversion is not calibration:
calibration additionally estimates and removes systematic error such as these
nonzero gyro biases.

### Closed-loop heading and IMU-driven Real2Sim

A single Pi process recorded motor phases and MPU samples on the same monotonic
clock. Sensor Y was identified as rover yaw because left and right commands
produced the largest opposite-signed response on that axis. A feedback
controller then used `error = target - integrated_yaw` to complete relative
targets `+60/-120/+60 degrees` with maximum absolute error `2.02 degrees`.

The original MuJoCo actuator applied constant torque. It could match one short
turn after gain fitting but overpredicted a longer turn because it lacked motor
speed saturation and braking. The revised affine actuator subtracts a
wheel-velocity term from command-generated force. Training-data fitting found
left/right gains `0.90/0.84` and velocity feedback `0.004`, with `2.33 degrees`
training trajectory RMS error.

The closed-loop sequence was held out from fitting. Its simulation error fell
from `36.51` to `14.34 degrees RMS`, a `60.7%` reduction. This demonstrates the
difference between calibration and validation: low training loss says the
parameters explain known data; held-out error estimates whether the model
generalizes. The remaining long-right-turn error proves further model and
measurement work is still required.

### Live IMU service integration

The persistent Pi control service now reads the MPU-9250 at 50 Hz alongside
the camera and the 100 Hz command watchdog. On startup, it estimates yaw bias
from 75 stationary samples and rejects calibration samples while the motors
are active. `/api/telemetry` publishes IMU state, yaw rate, relative yaw, bias,
noise, sample age, sample count, and any sensor error. The operator console
shows the live yaw values without adding page scrolling.

Relative yaw is reset whenever the service restarts; it is not a global compass
heading. During one stationary service run it drifted from about `2.6` to
`26.8` degrees because even a small residual gyro-rate error accumulates during
integration. The gyro is therefore useful for accurate short turns, while
long-term localization still needs an external correction such as visual
landmarks, visual odometry, or a trustworthy magnetometer measurement.

### Persistent heading control

The browser heading API turns a target angle into a background feedback job.
The job repeatedly computes `error = target - measured relative yaw`, chooses
turn direction from the error sign, refreshes commands every 100 ms, stops
early to allow mechanical coast, then applies bounded correction pulses. The
Pi watchdog still has final authority: if refreshes stop for 350 ms, PWM is
lowered independently of the heading job.

A live `+45/-90/+45` API sequence measured `+46.1/-92.2/+44.2 degrees`. Maximum
absolute error was `2.2 degrees`, and the net measured turn was `-1.9 degrees`.
This is accurate relative rotation over seconds, not absolute localization.

### Straight-line heading hold

Static left/right PWM calibration is open-loop: it assumes the same command
continues producing the same motion. Motor temperature, battery voltage, floor
friction, load distribution, and ordinary gearbox differences violate that
assumption. A stable mismatch is a control problem; a sudden change when a wire
is touched is an electrical fault and must be repaired rather than hidden in
software.

The operator controller now contains an optional closed-loop heading hold for
manual forward and reverse commands. At the start of a straight command it
captures the current integrated gyro yaw as its local reference. Every control
cycle it computes:

```text
error      = reference_yaw - measured_yaw
correction = Kp * error - Kd * yaw_rate
left_PWM   = calibrated_left_PWM  - correction
right_PWM  = calibrated_right_PWM + correction
```

`Kp` is the proportional gain: larger heading error requests a larger opposing
turn. `Kd` is rate damping: if the rover is already rotating quickly, measured
yaw rate opposes that rotation before angle error grows. Correction is limited
to 18 percentage points and cannot reverse a wheel. The mode stops output if
the IMU is unavailable or its newest sample is older than 150 ms. The existing
350 ms network-command watchdog remains independent and still stops stale
operator commands.

This mode is deliberately excluded from the Jetson's continuous
`forward/turn` actions. Visual steering already commands a turn; a separate
straight-heading loop would fight it. A future autonomy controller can use IMU
feedback explicitly while deciding its desired heading.

The UI exposes the controller's reference, heading error, PWM correction, and
correction saturation. This makes the feedback loop observable instead of
presenting corrected motion as unexplained "intelligence." The mode is
disabled by default until the IMU board is mounted rigidly and a physical
acceptance run confirms the sign and gains.

The MPU-9250 is a 9-axis inertial/magnetic sensor: a 3-axis gyroscope measures
angular velocity in degrees per second; a 3-axis accelerometer measures
specific force including gravity; and a 3-axis magnetometer measures magnetic
field. It also includes a temperature sensor. It does not directly measure
position, distance, wheel speed, or left/right drift. On this physical mounting
the sensor's Y gyroscope axis was experimentally identified as rover yaw.

The board is mounted vertically and must remain rigidly fixed in that measured
orientation. The stationary acceleration vector `(-0.094, +1.003, -0.202) g`
shows that sensor Y is nearly aligned with the chassis vertical axis. Physical
left/right tests then showed positive/negative Y-axis gyro response, so Y is
the correct rover-yaw axis for this mounting. Mounting it flat now would change
the axis mapping and invalidate the current controller unless the axis were
identified again. It must not rotate or swing on its wires; otherwise the gyro
reports motion of the sensor board rather than motion of the chassis. Insulate
the soldered underside from conductive surfaces and strain-relieve its four
wires. The magnetometer is not currently used because brushed motors, motor
current, battery wiring, and steel parts can distort magnetic heading. The
accelerometer is not integrated twice for position because small bias would
rapidly become large position drift.

Primary hardware reference: [TDK InvenSense MPU-9250 product
specification](https://invensense.tdk.com/wp-content/uploads/2015/02/PS-MPU-9250A-01-v1.1.pdf).

### The trained navigation policy

The policy is a small multilayer perceptron (MLP), meaning a sequence of matrix
multiplications and nonlinear functions:

```text
9 observations x 32 learned weights + 32 biases -> tanh hidden activations
32 hidden activations x 2 learned weights + 2 biases -> tanh actions
```

The exact parameter count is `9*32 + 32 + 32*2 + 2 = 386`. A weight is one
stored multiplier connecting an input or hidden activation to the next layer.
Training compares predicted `forward/turn` with expert actions, propagates the
squared-error slope backward through both matrices, and uses Adam to change
each parameter. Turn error is weighted four times more strongly because a
small steering error compounds into a large trajectory error.

Initial imitation alone failed because the learner entered situations absent
from expert demonstrations. Two dataset-aggregation rounds then ran the
learner, collected the states it actually reached, asked the expert for the
correct action there, and retrained. This is DAgger-style training. Validation
MSE fell from `0.28442` before training to `0.01749` on examples excluded from
weight updates. The accepted contact-world dataset contains 29,380 samples.

### Domain randomization and policy evaluation

Domain randomization changes physical and sensor parameters between simulated
missions so the policy cannot depend on one perfect world. The contact-world
test varied friction, left/right drive strength, directional turn gain,
velocity feedback, command/range latency, range noise/dropout, odometry scale,
and gyro scale/bias/noise. The learned policy completed 33/40 missions with
zero contact episodes versus 32/40 and 36 contacts for the deterministic
expert. With a forced one-second actuator stall, both completed 10/12 worlds;
the learned policy recorded zero contacts versus 13 for the expert.

The safety guard is not learned. It latches collision/stuck transitions,
reverses or pivots, steers away from low side clearance, and slows as front
clearance shrinks. It consumes only the same imperfect observation available
to the network. This separates performance optimization from explicit safety
behavior. Zero contacts in a finite simulated test set is evidence, not a
universal safety proof.

The full implemented explanation, equations, code paths, practical labs, and
claim boundaries are in `docs/simulation-and-sim2real-course.md`.

### Jetson autonomy service

The persistent Jetson process implements this loop:

```text
Pi JPEG -> TensorRT YOLO -> box geometry -> controller state
        -> normalized forward/turn -> Pi HTTP API -> watchdog -> GPIO PWM
```

It starts disarmed. ARM resets mission state; DISARM is serialized after any
in-flight command so a late inference cannot restart motion. A perception-only
probe runs the same camera and TensorRT path but marks the proposed action
`sent:false`. One measured probe took 102.77 ms end to end, including 60.63 ms
of TensorRT inference, with a 133 ms-old complete observation.

The original physical search contained a wiring error in software: although a
`30 degree` search step was configured, the mission loop actually used an
open-loop 45 ms PWM pulse. Pulse duration is not an angle, so battery voltage,
friction, wiring contact, and wheel loading changed how far each pulse turned.
Search now calls the Pi's closed-loop relative-heading API. The Pi integrates
the MPU-9250 Y-axis angular rate, stops near the requested 30 degrees, settles,
and corrects until it is within 4 degrees. The Jetson then inspects up to three
stationary frames. Twelve steps bound one nominal 360-degree sweep; after a
miss, the rover makes one 300 ms reverse movement to change viewpoint and
scans in the opposite direction. A visible but off-center target still uses a
35 ms alignment pulse. If a moving frame misses a recently seen target, the
rover stops for up to 1.5 seconds to reacquire stable imagery instead of
immediately resuming search. Mission 13 completed the camera-to-TensorRT-to-
controller-to-motor loop with 7 ALIGNING, 8 REACQUIRING, 6 APPROACHING, and 1
ARRIVED update. Earlier failed runs remain in the evidence set because they
identify the controller assumptions that required correction.

Mission 14 started with the mandarin outside the field of view. SEARCHING sent
rotation only, never forward motion. After acquisition, the controller
alternated alignment, approach, and stationary reacquisition until ARRIVED at
0.930 normalized box-bottom and 0.113 area. This distinguishes closed-loop
autonomy from a timed motion script: every movement segment depended on a new
camera measurement, and temporary perception loss produced zero motion.

### Interactive autonomy lab

The local lab at `http://127.0.0.1:8780/` is an operator and engineering
instrument, not a replacement controller. Its backend proxies the existing Pi
and Jetson APIs and loads the same MuJoCo and policy code used by evaluation.

```text
LIVE -> real JPEG, YOLO box, state, action, IMU, watchdog, and PWM
SIM  -> MuJoCo scenario, domain parameters, policy, and injected stall
NN   -> nine policy inputs, hidden activations, and two outputs
R2S  -> physical IMU trace against old and fitted dynamics
EV   -> accepted and pending engineering claims
```

Holding a manual button refreshes the Pi command every 100 ms. Releasing it
sends STOP, and the Pi's independent 350 ms watchdog remains authoritative.
Starting manual motion first disarms Jetson autonomy so two command producers
cannot intentionally control the motors at once. ARM remains explicit and the
red STOP relays both a Pi stop and Jetson disarm.

The LIVE camera and TensorRT result are separate data streams. Camera images
remain live whenever the Pi camera is streaming, but the Jetson only produces
fresh detections while armed, probing, or monitoring. The UI now labels each
detector result as `LIVE CONTROL`, `LIVE MONITOR`, `LAST PROBE`, or
`STORED RESULT`; it draws a box only for a live result. `LIVE MONITOR` runs the
real camera and TensorRT loop continuously but never calls the Pi action API.
Its first deployment processed 12 fresh frames, proposed an orange approach,
and independently verified `motor_active=false` with both Pi outputs at zero.

The SIM tab is not a camera reconstruction of the room. Python advances the
four-wheel MuJoCo model with a 2 ms physics timestep and returns chassis state;
the browser renders that state as a top-down engineering diagram. The target-
search scenario can begin at 170 degrees, outside the simulated 70-degree
camera field, then show SEARCHING, acquisition, approach, and ARRIVED. The yaw
response is fitted to physical IMU data. Translation speed, wheel slip, mass,
and room geometry remain explicitly unmeasured assumptions, so this is a
calibrated dynamics model rather than a complete digital twin of the house.

The first physical measured-search acceptance run passed. The rover initially
failed to detect the mandarin during one full sweep, reversed to change its
viewpoint, found it during the opposite sweep, and eventually reached ARRIVED
after intermittent close-range loss and reacquisition. The terminal live frame
had `0.784` confidence, `0.1224` target area, `0.9903` bottom edge, and `152 ms`
age. The controller requested zero motion, and a separate post-disarm Pi query
reported both PWM outputs at zero. This is local target search in clear space;
without localization and obstacle observations, it must not be described as
autonomous exploration of a house.

### What now runs on each computer

The Mac is the development and visualization machine. It stores the repository,
runs tests, launches MuJoCo, and serves the Autonomy Lab. It is not supposed to
decide physical motor outputs during an independent deployment.

The Jetson is the perception and mission computer. Linux `systemd` starts this
process:

```text
/usr/bin/python3 software/jetson/autonomy_service.py
```

Python is the orchestration language. The expensive YOLO inference is not a
Python loop: Python calls NVIDIA TensorRT, which executes the compiled neural
network engine on the Jetson GPU. OpenCV performs CPU image decoding and ORB
feature tracking. The service converts those measurements into a
`MissionCommand` such as a measured heading turn or bounded motor pulse.

The Pi is the hardware and safety computer. Its HTTP API receives normalized
`forward` and `turn` values, mixes them into calibrated left/right PWM, and
drives TB6612 logic pins through GPIO. A 350 ms watchdog lowers PWM if command
refresh stops. This means a dead Jetson, broken tunnel, browser crash, or stale
camera cannot leave the motors commanded indefinitely.

```text
camera -> Pi JPEG -> Jetson TensorRT/ORB -> mission command
       -> Pi HTTP -> watchdog -> PWM + direction pins -> TB6612 -> motors
```

### The shared runtime: what makes simulation relevant

`software/jetson/mission_runtime.py` defines the operation contract used by
both the Jetson service and the target simulator. It translates controller
state into one of four execution types:

```text
stop | heading_turn | motor_pulse | fault
```

For example, SEARCH means a measured 30-degree heading turn, not an arbitrary
duration of wheel power. On hardware, the Pi closes that turn using gyro yaw.
In simulation, MuJoCo advances wheel/chassis dynamics until the same heading
tolerance is reached. The actuator implementations differ, but mission
semantics and limits are shared. This is runtime parity; copying similar logic
into two files would not provide the same guarantee.

### Visual motion: what ORB measures

ORB finds visually distinctive corners and assigns each a short binary
descriptor. Hamming distance counts how many descriptor bits differ, allowing
features in consecutive frames to be paired. RANSAC repeatedly estimates an
image transform from small match subsets and keeps the transform supported by
the largest consistent set of matches, rejecting moving objects and bad pairs.

The deployed Jetson test produced 159 matches and 107 geometric inliers. The
estimated image displacement was `-2.74 px` horizontally and `-2.47 px`
vertically. Those are image-plane measurements, not metres. With one camera,
the same pixel shift can be caused by a small nearby movement or a larger
distant movement. Metric scale therefore needs an additional constraint such
as wheel odometry, known landmarks, stereo/depth, or calibrated ground-plane
geometry.

### Localization, mapping, and planning

Localization asks: "where does the rover estimate it is?" Mapping asks: "which
parts of the world appear free, occupied, or unknown?" Planning asks: "which
collision-free sequence of positions reaches the current goal?" They are
separate computations and can fail independently.

The mapping experiment implements this loop:

```text
wheel/gyro motion -> dead-reckoned pose estimate
range rays         -> log-odds occupancy-grid update
free/unknown edge  -> frontier candidate
occupancy grid     -> inflated safety map -> A* path
path + estimate    -> bounded forward/turn action -> MuJoCo physics
```

Dead reckoning integrates velocity and yaw rate over time:

```text
heading[t+1] = heading[t] + yaw_rate * dt
x[t+1]       = x[t] + speed * cos(heading) * dt
y[t+1]       = y[t] + speed * sin(heading) * dt
```

Every bias is also integrated, so pose uncertainty grows. In the canonical
run, intentionally imperfect odometry produced `0.221 m` final position error.

An occupancy grid stores evidence per cell. A range ray makes traversed cells
more likely free and its hit endpoint more likely occupied. Log odds allow
repeated observations to accumulate without snapping one uncertain reading to
absolute truth. Frontier cells are known-free cells touching unknown cells;
choosing one gives exploration a concrete goal. A* searches the inflated grid
for a low-cost route, while obstacle inflation reserves the rover footprint
instead of planning as though the chassis were a point.

### How the simulator is real, and how it is not

MuJoCo computes forces, contact, inertia, wheel actuation, and chassis motion.
The map is built from simulated sensor rays; it is not a hard-coded picture or
a browser animation. The planner never receives true rover coordinates or the
complete world map. Ground truth exists separately because a simulator must
generate sensor observations and score estimation error and collisions.

The simulated range sensor is currently the crucial reality gap. The physical
rover has a monocular camera and an IMU but no wheel encoders, lidar, depth
camera, ultrasonic range array, or bump sensor. It therefore cannot currently
produce the metric obstacle-distance measurements consumed by this mapper and
the trained policy. Software can estimate image motion, but it cannot safely
invent metric clearance. Physical house-scale search is not accepted until
that observation interface exists and is tested.

### Is this AI?

The system contains both learned and deterministic parts. YOLO is a trained
neural network that maps pixels to object boxes. The 386-parameter navigation
policy is also a neural network, trained by imitation and dataset aggregation.
Occupancy mapping, A*, watchdogs, and the target state machine are classical
algorithms. A production autonomy stack deliberately combines them: learned
models handle ambiguous perception or policy approximation; deterministic
logic handles geometry, constraints, state transitions, and safety.

### What to learn next

1. Coordinate frames and rigid transforms: camera, IMU, chassis, map, and world.
2. Probability and estimation: bias, covariance, Kalman filtering, and pose graphs.
3. Mapping and planning: occupancy inverse-sensor models, frontiers, A*, and MPC.
4. Vision: camera calibration, projective geometry, features, optical flow, and depth.
5. Controls: system identification, PID/PD, saturation, latency, and stability.
6. Edge inference: CUDA execution, TensorRT compilation, quantization, and profiling.
7. ROS 2 after the raw boundaries are understood: nodes, topics, TF, bags, and QoS.

The same structure transfers to a production robot arm. A joint encoder replaces
wheel odometry, forward kinematics replaces planar dead reckoning, a voxel or
scene model replaces the floor grid, and a trajectory planner replaces A*.
Perception estimates object pose; planning chooses a collision-free trajectory;
joint controllers track it; independent limits and emergency stops remain the
final authority.

### High-fidelity exploration upgrade

The mapping simulator now compiles the room walls, cylindrical obstacles, and
orange target into the MuJoCo model. Wheels and chassis react through MuJoCo's
contact solver. Range observations come from `mj_ray` intersections with that
compiled geometry. The old analytic overlap check and pose teleport have been
removed.

The onboard simulation camera now renders 320 x 180 RGB. An OpenCV HSV detector
extracts orange pixels, computes a box and image-centre error, and estimates
range from apparent target width. Positive horizontal error means image-right
at every boundary. This convention matters: an earlier reversed sign made a
locally valid detector command the controller to turn away and place remembered
targets outside the room.

Separate queues model range, camera, and command latency. Seeded noise and
dropout affect only observations after MuJoCo generates ideal sensor values.
The estimator integrates those imperfect values, so its cyan pose diverges from
the optional white truth pose. The planner still sees no truth.

The interactive Mapping view exposes these values as experiment controls and
shows the actual MuJoCo onboard frame alongside the occupancy grid. Its
parameter ledger labels each value `measured`, `configured`, or `assumed`.
The 12-trial rendered-camera benchmark passed 10 missions and retained two
timeouts. See `docs/experiments/2026-09-06-high-fidelity-mujoco-exploration.md`.

## 2026-09-08: Practical Workshop and Evidence Corrections

Start the new session with [the practical course](rover-practical-course.md).
It connects each concept to this repository, supplies runnable experiments,
worked arithmetic, primary-source readings, a demo plan and a travel curriculum.
The goal is to predict and explain behavior, not memorize framework names.

Three separate systems must not be conflated: pretrained YOLO detects objects
on the Jetson; a deterministic state machine converts target geometry into
physical motion; a separately trained 386-parameter MLP drives simulated
navigation scenarios through a safety filter. The simulated mapping planner
uses occupancy cells, frontiers and A*, not that MLP.

The box-to-PWM workshop imports the actual controller and motor mixer without
touching hardware. A classroom box centered at pixel 480 in a 640-wide image
gives `(480-320)/320 = +0.5` horizontal error. With runtime defaults and explicitly
assumed 0.8/1.0 calibration, it requests a 35 ms alignment pulse with signed
PWM `(0.24,-0.30)`. The script distinguishes these assumptions from live settings.

The gradient workshop loads a copy of the saved network, computes derivatives,
checks one against finite differences and takes one in-memory SGD step.
The selected weight changes from 0.82832645 to 0.82838239 while weighted example
loss falls from 0.00331952 to 0.00314818. The original training uses Adam; the
saved model is unchanged. This demonstrates HOW a weight update is calculated.

The 60.7% Real2Sim improvement is RMSE across THREE final-yaw endpoints of a
separate turn sequence, not full-trajectory validation. The fitted endpoint
RMSE remains 14.34 degrees, with a worst residual of about 23.36 degrees. The
reference is gyro integration, not independent ground truth. Earlier broad
trajectory wording should be read with this correction.

A fresh fixed-model controller comparison (seed 260908, 12 worlds each) found:

| Stack | Goals reached | Contact events |
| --- | ---: | ---: |
| Baseline | 12/12 | 10 |
| Baseline plus filter | 10/12 | 0 |
| Bounded neural policy | 10/12 | 48 |
| Bounded neural policy plus filter | 11/12 | 0 |

The filter strongly affects contacts in this small suite. Comparing neural+filter
to baseline alone does not isolate learning. Across controller families action
bounds also differ. Contact/stuck inputs include ideal simulator information;
we do not yet have corresponding validated physical measurements. This is a
concrete observation-parity gap, not something that TensorRT compilation solves.

The owner reports the Belkin working again. During this audit the local lab was
reachable but the Pi endpoint returned no route and the Jetson timed out.
No hardware motion, remote deployment or new physical acceptance was performed.
Use [the recording runbook](portfolio-demo-runbook.md) once devices are ready.

## 2026-09-08: Live Camera Timing and Possible Wiring Faults

Later in the same day both devices became reachable, and a disarmed Jetson
probe processed three Pi frames through the restored USB/SSH relay. The Pi
subsequently stopped answering again, while the Jetson remained disarmed.
The sequence, evidence and deployment boundary are recorded in the
[camera and hardware diagnostic](experiments/2026-09-08-camera-delivery-and-hardware-boundary.md).

The Pi reader's buffered `read(65536)` was reproduced holding a complete short
JPEG while waiting for more data. Its `read1(65536)` replacement passes the
regression test, but has not been deployed because the Pi became unreachable.
No physical timing or steering improvement has yet been measured.

The running Mac lab now marks old camera images STALE, preserves source frame
metadata, and does not place an old inference box on a different image. Its
motor telemetry explicitly shows commanded PWM, not measured wheel speed.

An IMU reports chassis rotation, not individual wheel rotation or current.
Feedback may correct repeatable drift, but cannot reliably repair an intermittent
wire. That distinction is the next physical diagnostic boundary: establish
stable wheel response before tuning compensation.

## 2026-09-08: Soccer Ball, Mission Deadline and UI Cancellation

The owner selected a soccer ball and reported restarting the Pi. The Jetson
was reachable but the Pi was not found by IP, mDNS, controller-port discovery or
SSH discovery on the current LAN. No physical mission was run.

The Jetson now starts disarmed with `sports ball` selected and a 45-second
mission budget. This filters an existing model class; it is not new training.
The new timer addresses endless valid commands; the Pi's existing watchdog
addresses missing commands. Manual button releases now invalidate pending
asynchronous starts, serialize held commands and issue a final stop after any
in-flight command settles. STOP also disarms the Jetson.

See [the deployment and worked mechanism](experiments/2026-09-08-sports-ball-deployment.md)
for code references, hashes, tests and the explicit physical acceptance gaps.

## 2026-09-08: Boot Before Networking

With the Pi card in the Mac, its kernel and initial RAM filesystem both passed
compression integrity checks. This is narrower than proving successful boot.
Linux must also mount its root filesystem and start the networking services.
Failures at those earlier stages can produce the same unreachable-browser
symptom as a Wi-Fi problem.

The card is currently disk5; disk4 is the Jetson's small USB drive. Disk numbers
are assigned dynamically, so the new read-only diagnostic verifies the actual
card identity. The authenticated read-only check subsequently returned zero but
reported pending filesystem-journal recovery and free-count differences. A
zero exit status alone was not enough to call it completely clean. No network
changes or repairs were applied. See the
[inspection evidence and next measurement](experiments/2026-09-08-pi-card-readonly-inspection.md).

There are two different journals here: ext4's journal records filesystem changes
so interrupted writes can be recovered; systemd's journal records system events
for diagnosis. The latter shows a successful Wi-Fi boot and normal operation
through 18:40 AEST, but no later saved boot or full-system shutdown. That narrows
the evidence without identifying the physical cause. The next observed boot
uses the existing Pi wall supply to separate the Belkin power path from boot
and networking, rather than rewriting a configuration that demonstrably worked.

The owner then reported no green activity on wall power, including with the SD
card removed. This moves the diagnostic before Linux. A board receives 5 V but
also produces lower voltages internally; the red light does not certify every
internal supply. An attached circuit can overload or interfere with those
supplies. Testing the Pi without its GPIO/camera connections isolates that
possibility before changing firmware or buying a replacement. The isolation
test is requested, not yet completed; all supplies must be disconnected before
unplugging the signal connections.

## 2026-09-08: Closing the Prototype Phase Honestly

The owner subsequently tried the card both in and out, then reported unplugging
the wiring with no improvement. Fresh SSH/controller checks still failed. The
Belkin's earlier failure is a reasonable hypothesis to investigate, not proof
that it damaged the Pi. The no-SD observation does not exclude onboard startup
firmware, which is stored separately from Linux. No definite hardware cause or
successful firmware recovery has been established.

The physical target-seeking, camera, motor and IMU experiments remain past
engineering results even without a polished external video. They do not prove
present availability, whole-house autonomy or physical learned-policy transfer.
Treat this as a demonstrated experimental prototype with an unresolved startup
fault, not a production-ready autonomous product.

The simulation calculates motion and contacts in MuJoCo, generates sensor
observations and feeds them to controllers. The UI displays calculated states
and rendered cameras, rather than prescribing a decorative path. Its map is
built from simulated range readings, not a scan of the owner's house. Those
range observations are unavailable on the physical rover.

Real2Sim here means using recorded motor commands and IMU yaw to fit actuator
parameters, then checking predictions against separate physical turns. The
three held-out final-angle errors have RMSE 14.34 degrees, down from 36.51.
That is limited turning calibration, not a fully calibrated digital twin.
Physical Sim2Real deployment of the learned navigation policy remains pending.

The saved 40-world learned-policy-plus-safety evaluation completed 33 missions
with zero contact episodes. A fresh final-hour rerun of seed 9201, scenario 0
timed out at 24.04 simulated seconds with zero contacts, 470 trace samples and
97 rendered frames. The failure is retained in
`artifacts/sim/2026-09-08-final-hour-check.json`; do not call the demonstration
uniformly successful or hide this result. The laptop lab still serves normally.

Learning checkpoint: explain why matching three final turn angles does not yet
validate simulated straight-line motion, obstacle sensing or policy transfer.

## 2026-09-08: Travel Learning Kit and Power Boundaries

The minimum useful travel kit is the Mac and Jetson developer kit with its
existing system card, heatsink/fan, original power supply, working USB data cable,
card reader and destination plug adapter. MuJoCo experiments continue on the
Mac. The Jetson adds actual NVIDIA deployment, inference timing and optimization
experiments; it is not needed to run the current simulator.

Mac camera frames can be captured on the Mac and sent over the existing USB
network to Jetson inference. That is a proposed capture/streaming workflow,
not an already implemented live camera bridge. Camera Module 3 is small enough
to pack optionally with its 15-to-22-pin cable, but its IMX708 driver must match
the Jetson kernel/JetPack. Do not assume stock plug-and-play support or overwrite
the working Jetson system to install an unverified camera driver. Existing
historical IMX708 overlay configuration alone is not a fresh camera test.

The owner reports leaving motor power connected for weeks. Power still connected
is different from motors running: the driver switches battery current according
to its control inputs and standby state. The motor supply is separate from Pi
logic power. A higher-voltage connection into that logic circuit could cause
damage, but remaining connected does not establish that such a fault occurred.
No confirmed cause of the Pi failure exists. Disconnect both batteries before
storage or connector changes, and verify the harness before fitting another Pi.

Camera references: [NVIDIA CSI connection guide](https://docs.nvidia.com/jetson/orin-nano-devkit/user-guide/latest/howto.html#csi-camera)
and [RidgeRun IMX708 driver](https://developer.ridgerun.com/wiki/index.php/Raspberry_Pi_Camera_Module_3_IMX708_Linux_driver_for_Jetson).

The owner explicitly confirms Camera Module 3 previously worked directly on
the Jetson. Preserve the existing Jetson software and matching ribbon; do not
frame this as an untried camera integration or suggest unnecessary driver
replacement. This is a historical owner-confirmed result, not a fresh capture.

## 2026-09-08: Recovery Firmware Is Not the Rover OS

The owner supplied and authorized erasing a spare camera card. It now contains
verified official Pi 4 EEPROM recovery files on a 512 MB FAT32 partition and
has been safely ejected. The original rover card and Jetson media were untouched.
See [the recovery record](experiments/2026-09-08-pi-eeprom-recovery.md).

The distinction is ROM/startup firmware versus Linux: the Pi can load a recovery
program that rewrites its onboard bootloader without booting Ubuntu. This card
therefore should not appear on Wi-Fi or serve the rover UI. Rapid continuous
green flashing is the recovery success indicator, after which power must be
removed and the original OS card restored for a separate boot test. A completed
recovery would prove that this recovery path executed, not that all GPIO,
peripherals or the assembled rover are healthy.

The owner then reported no green activity with the recovery card. We have no
confirmed recovery success. This shifts suspicion toward hardware or power
delivery, because this test does not depend on Ubuntu, Wi-Fi or the controller.
It does not prove a particular component failed or that the Belkin caused it.
Reliable supply-rail measurements remain missing, so "suspected hardware/power
fault" is the conclusion, not "confirmed fried Pi". More network configuration
changes would not address the observed failure at this earlier startup stage.

The spare card is temporarily partitioned to 512 MB; restore its full capacity
and format it in the camera after testing. Its smaller visible size is a
partitioning choice, not a physically damaged or permanently reduced SD card.

Restoration subsequently completed: one full-capacity ExFAT partition now
replaces the temporary recovery partition, filesystem verification passed, and
the card was safely ejected. A partition describes which portion of storage a
filesystem uses; replacing that layout restored access to the nominal 128 GB
without changing the card's physical memory. Format it in the camera before
recording to let the camera create its own folders and preferred settings.

## 2026-09-08: Offline study and reproducible evidence

The travel curriculum is now organised around three separate experiments:
physical target detection/control, measured yaw fitting, and simulated learned
navigation. Do not describe them as one end-to-end trained rover. Start with
[the field guide](offline-field-guide.md), then the interactive workbook in
`software/learning/offline_workbook.html`.

The workbook's saved-network forward pass matches NumPy to floating-point
precision. Its training control uses a deliberately simple scalar example so
the derivative and weight update are visible. Its Real2Sim section presents
held-out turn residuals, including the remaining 23.36-degree error. Two newly
exported predetermined MuJoCo scenarios both timed out and are retained as
debugging examples, not hidden or described as success. The full simulator can
be launched separately; replaying saved frames does not execute new physics.

The offline pack lives outside this checkout. Its copied environment preserves
the simulator packages, and its server rejects all physical-device requests.
This makes it possible to investigate software while hardware is unavailable.
Git tracks selected files; ignored private photographs and old provisioning
files require a separate local copy. The backup manifest records that
distinction, hashes and the independently checked remote commit.

First exercise: use a box centred at x=480 in a 640-pixel image. Calculate the
normalised error, inspect the actual controller output, and explain which
subsequent software layer turns that result into a motor command. Then change
only image freshness. Why must a geometrically correct box still be rejected
when its image is stale?
