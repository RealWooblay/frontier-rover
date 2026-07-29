# Hardware Inventory

Last updated: 2026-07-29

This inventory separates verified product information from assumptions. No
power wiring should be based only on an Amazon title.

## Available Hardware

| Item | Exact product | Intended role | Status |
| --- | --- | --- | --- |
| Raspberry Pi | Raspberry Pi 4 Model B Rev 1.5, 4 GB | Low-level controller | Verified and operational |
| Jetson | NVIDIA Jetson Orin Nano Super Developer Kit | Later perception and planning computer | Verified; use supplied power adapter during bench development |
| Camera | Raspberry Pi Camera Module 3, standard | Vision sensor | Compatible with Pi 4 using a 15-pin-to-15-pin camera cable |
| IMU | HiLetgo GY-9250 / MPU-9250, ASIN B01I1J0Z7Y | Acceleration, rotation, and magnetic-field sensing | Board-level voltage tolerance and authenticity unverified |
| Chassis | XiaoR Geek XR-003, ASIN B07F759T89 | Four-wheel mechanical platform | Verified model |
| Motors | Four TT brushed DC gearmotors supplied with XR-003 | Differential drive | Listing states 3-12 V; current and encoders unverified |
| Buck converters | Lylanmo LM2596 adjustable modules, ASIN B0F2BC4JGM | Step-down power conversion | Output must be adjusted and load-tested before connection |
| Jumper wires | ELEGOO Dupont kit, ASIN B01EV70C78 | Low-current logic signals | Do not use for battery or motor current |
| DC pigtails | CENTROPOWER 5.5 x 2.1 mm, 18 AWG, nominal 5 A | Low-voltage DC connections | Polarity and actual branch current must be verified |
| USB-C cable | NOCO XGrid XC1, 240 W-rated | Data/power cable | A cable only; it does not regulate voltage |
| Camera adapter cable | ZDE 15-pin-to-22-pin CSI cable, ASIN B0DQBHNT9C | Pi 5/Zero-style camera connector adapter | Not the Pi 4 camera cable; possible later Jetson mechanical adapter |
| Tools | Screwdriver set, soldering iron, multimeter | Assembly and measurement | Available |

## Verified Product Facts

### Chassis

- Product/model: XiaoR Geek XR-003.
- Mechanical plate: 256 x 150 x 2 mm.
- Listed maximum load: 500 g.
- Four two-terminal brushed TT gearmotors.
- Listed motor operating range: 3-12 V.
- The product listing explicitly excludes controller boards and sensors.

Source: <https://www.amazon.com/dp/B07F759T89>

### LM2596 Converter Modules

The LM2596 regulator family is a step-down converter. The genuine TI component
is rated for 4.5-40 V input and up to 3 A output under appropriate design and
thermal conditions. The assembled Lylanmo modules and their component
authenticity have not been independently verified.

Source: <https://www.ti.com/product/LM2596>

### Camera Module 3

- Sony IMX708, 11.9 megapixels.
- CSI-2 output.
- Raspberry Pi 4 uses the standard 15-pin camera connector.

Source: <https://www.raspberrypi.com/products/camera-module-3/>

### MPU-9250 Sensor

The bare MPU-9250 silicon uses 2.4-3.3 V for VDD and 1.8-3.3 V for VDDIO.
The breakout board must be inspected before deciding whether its `VCC` pin can
accept anything other than 3.3 V.

Source:
<https://product.tdk.com/system/files/dam/doc/product/sensor/mortion-inertial/imu/data_sheet/ps-mpu-9250a-01-v1.1.pdf>

## Missing or Unverified Before Motor Bring-Up

1. Dual-channel brushed DC motor driver.
2. Exact battery pack, cell chemistry, cell count, voltage, capacity, connector,
   and protection circuitry.
3. Motor running current and stall current.
4. Main fuse, accessible power-disconnect switch, and suitable power wiring.
5. Confirmation of whether any motor has an encoder.
6. Measured total chassis mass and payload margin.

## Candidate Motor Driver

The Cytron MDD10A Rev 2.0 is the current candidate:

- Two brushed-DC channels for left and right motor groups.
- 5-30 V motor supply.
- 10 A continuous and 30 A peak per channel.
- Accepts Raspberry Pi 3.3 V PWM and direction signals.
- No reverse-polarity protection on the motor supply.

It is not approved for purchase or wiring until the battery and motor current
are verified.

Source:
<https://www.cytron.io/p-10amp-5v-30v-dc-motor-driver-2-channels>

## Next Physical Evidence

Photograph:

1. The complete chassis from above and below.
2. All markings and wires on one motor.
3. The battery pack, holder, connector, and every label.
4. Both sides of one LM2596 module.
5. Both sides of the GY-9250 board.

Include a ruler or known-size object in the chassis photograph. Do not connect
the battery, buck converter, motors, Raspberry Pi, or Jetson for these photos.
