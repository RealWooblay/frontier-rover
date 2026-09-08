# Hardware Inventory

Last updated: 2026-09-08

This inventory separates verified product information from assumptions. No
power wiring should be based only on an Amazon title.

## Available Hardware

| Item | Exact product | Intended role | Status |
| --- | --- | --- | --- |
| Raspberry Pi | Raspberry Pi 4 Model B Rev 1.5, 4 GB | Low-level controller | Previously operational; September 8 startup/access failure persists after reported peripheral removal; cause unresolved |
| Jetson | NVIDIA Jetson Orin Nano Super Developer Kit | Later perception and planning computer | Verified; use supplied power adapter during bench development |
| Camera | Raspberry Pi Camera Module 3, standard | Vision sensor | Verified on Pi 4; IMX708 detected and 1920x1080 JPEG captured using a 15-pin-to-15-pin cable. Owner also confirms previous direct Jetson operation; preserve that installation and matching ribbon |
| IMU | HiLetgo GY-9250 / MPU-9250, ASIN B01I1J0Z7Y | Acceleration, rotation, and magnetic-field sensing | Listing specifies 3-5 V input with internal regulator; hardware returned MPU-9250 identity `0x71` at I2C address `0x68` |
| Chassis | XiaoR Geek XR-003, ASIN B07F759T89 | Four-wheel mechanical platform | Verified model |
| Motors | Four TT brushed DC gearmotors supplied with XR-003 | Differential drive | Listing states 3-12 V; current and encoders unverified |
| Motor wire | Seven black wires supplied with the chassis; original strip was previously cut | Connect motors to driver outputs | Seven owned; four continuity-tested; an existing 18 AWG pigtail can supply the missing connection later |
| Motor drivers | Three DIANN TB6612FNG dual-channel modules | Switch battery power to the motors under Pi control | Owned; suitability depends on measured motor current |
| Motor battery | LRP Power Pack 3000 mAh, 7.2 V, six-cell NiMH stick pack, Tamiya plug, SKU LRP-71115 | Mobile power for motor drivers | Owned and tested with all four motors |
| Pi power bank | Belkin BoostCharge Power Bank 20K, model BPB012 | Independent mobile 5 V supply for Raspberry Pi | Previously powered Pi; owner reports intermittent bank failure/recovery; no measured causal link to Pi startup failure |
| Battery charger | Infinity Power IP-Ni2, 2 A, 4-8 cell NiMH/NiCd charger | Correct controlled charging of the NiMH pack | Owned; Tamiya connector matches battery |
| Power connectors | Infinity Power Tamiya male/female connectors, two pairs | Removable rover battery connection | Assembled and voltage-tested |
| Insulation | Infinity Power 5 mm red/black heat-shrink | Insulate completed power-wire joints | Owned |
| Buck converters | Lylanmo LM2596 adjustable modules, ASIN B0F2BC4JGM | Step-down power conversion | Output must be adjusted and load-tested before connection |
| Jumper wires | ELEGOO Dupont kit with M-M, F-F, and M-F leads, ASIN B01EV70C78 | Low-current logic signals | No separate header strips; male ends may be soldered into logic holes; do not use for battery or motor current |
| DC pigtails | CENTROPOWER 5.5 x 2.1 mm, 18 AWG, nominal 5 A | Optional detachable low-voltage DC connections | Owned but not required between the first motor and driver |
| USB-C cable | NOCO XGrid XC1, 240 W-rated | Data/power cable | A cable only; it does not regulate voltage |
| Camera adapter cable | ZDE 15-pin-to-22-pin CSI cable, ASIN B0DQBHNT9C | Pi 5/Zero-style camera connector adapter | Not the Pi 4 camera cable; possible later Jetson mechanical adapter |
| Tools | Screwdriver set, soldering iron, leaded solder, multimeter | Assembly and measurement | Available; no dedicated wire cutters or strippers |

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

### Mobile Battery and Charger

- Battery chemistry: nickel-metal hydride (NiMH).
- Cell count: six cells in series.
- Nominal pack voltage: 7.2 V.
- Capacity: 3000 mAh.
- Connector: standard Tamiya style.
- Charger: 2 A constant-current smart charger supporting 4-8 NiMH/NiCd cells.

The NiMH battery supplies only the motor drivers during the current development
stage. A separate Belkin BPB012 power bank supplies the Raspberry Pi. Separating
the supplies prevents motor-current transients from directly pulling down the
Pi supply and avoids connecting an untested LM2596 to the computer.

The Belkin BPB012 has a 20,000 mAh internal battery and a USB-C output rated
5 V/3 A, with 15 W shared across all output ports. Only the Pi should be
connected during rover tests. Pi undervoltage status must still be verified
under motor and camera load.

Sources:

- <https://www.frontlinehobbies.com.au/lrp-power-pack-3000mah-7.2v-6-cell-nimh-stickpack>
- <https://www.frontlinehobbies.com.au/infinity-power-ni2-ac-2.0a-4-8s-nimh-nicd-charger>
- <https://www.belkin.com/ca/support-article/?articleNum=334029>

### TB6612FNG Motor Drivers

The TB6612FNG chip contains two H-bridge motor channels. An H-bridge lets a
low-current logic signal control the direction and average power of a much
higher-current motor circuit.

Important chip limits:

- Motor supply range: 2.5-13.5 V.
- Rated average output current: 1.2 A per channel.
- Peak output current: 3.2 A under the datasheet's specified pulse conditions.
- Logic input thresholds are compatible with Raspberry Pi 3.3 V GPIO.

The 7.2 V battery is inside the voltage range. The four motors measured 5.2,
5.5, 5.3, and 5.3 ohms after subtracting 1.0 ohm of probe resistance. Their
estimated stall currents are 1.31-1.38 A at 7.2 V and 1.53-1.62 A at an
approximately 8.4 V full-charge voltage. This is above the chip's 1.2 A
average rating but below its pulse rating, so one raised motor is conditionally
approved for short, low-duty tests. Deliberate stalls and sustained four-motor
operation are not approved.

The observed module labels are `PWMA`, `AIN2`, `AIN1`, `STBY`, `BIN1`, `BIN2`,
`PWMB`, and `GND` on the control side, and `VM`, `VCC`, `GND`, `AO1`, `AO2`,
`BO2`, `BO1`, and `GND` on the power and motor side.

Source: <https://toshiba.semicon-storage.com/info/TB6612FNG_datasheet_en_20141001.pdf>

### Camera Module 3

- Sony IMX708, 11.9 megapixels.
- CSI-2 output.
- Raspberry Pi 4 uses the standard 15-pin camera connector.

Source: <https://www.raspberrypi.com/products/camera-module-3/>

### MPU-9250 Sensor

The bare MPU-9250 silicon uses 2.4-3.3 V for VDD and 1.8-3.3 V for VDDIO.
The exact HiLetgo breakout listing specifies a 3-5 V supply and an internal
low-dropout voltage regulator. On 2026-09-06, the installed module accepted a
5 V supply and returned the expected MPU-9250 identity `0x71` over I2C.

Source:
<https://product.tdk.com/system/files/dam/doc/product/sensor/mortion-inertial/imu/data_sheet/ps-mpu-9250a-01-v1.1.pdf>

Breakout source: <https://www.amazon.com/dp/B01I1J0Z7Y>

## Missing or Unverified Before Full Four-Motor Operation

1. Motor running current under normal rover load.
2. Raspberry Pi undervoltage and runtime on the Belkin BPB012.
3. Main fuse, accessible power disconnect, and final power distribution.
4. Confirmation of whether any motor has an encoder.
5. Measured total chassis mass and payload margin.

## Motor Driver Contingency

The Cytron MDD10A Rev 2.0 is a contingency if measurements reject the existing
TB6612FNG modules:

- Two brushed-DC channels for left and right motor groups.
- 5-30 V motor supply.
- 10 A continuous and 30 A peak per channel.
- Accepts Raspberry Pi 3.3 V PWM and direction signals.
- No reverse-polarity protection on the motor supply.

Do not purchase it unless measurements show the existing drivers are
insufficient.

Source:
<https://www.cytron.io/p-10amp-5v-30v-dc-motor-driver-2-channels>

## Next Physical Step

Raise all four wheels and perform the remote-control watchdog acceptance test:
hold forward, release it, then intentionally close the browser while holding a
command. Both cases must lower the motor outputs within 0.35 seconds.
