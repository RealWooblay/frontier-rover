# M1 One-Motor Bench Wiring

Status: one-motor functional pass

## Objective

Make one raised motor turn under Raspberry Pi control while keeping the Pi on
its official wall supply. Use only existing parts.

The first test motor is `M1`, the back-right motor when viewed in the rover's
intended forward direction.

Assembly record:

- Two chassis wires soldered to the back-right motor tabs.
- Motor and both wires measured 6.6 ohms end-to-end before connection to the
  driver.
- Free wire ends soldered to TB6612 `AO1` and `AO2`.
- Each driver-to-motor wire path measured 1.1 ohms against a 1.0 ohm probe
  baseline; both output joints passed.
- Six M-F Dupont control wires soldered to `VCC`, control `GND`, `STBY`,
  `PWMA`, `AIN1`, and `AIN2`; continuity and bridge checks pending.
- Battery harness measured +7.6 V through a spare male barrel pigtail; polarity
  is confirmed before connection to the driver.
- Raspberry Pi Wi-Fi restored and SSH verified at `192.168.0.83`.
- GPIO5, GPIO6, GPIO12, and GPIO25 were explicitly configured as output-low and
  read back low before motor power.
- TB6612 `VCC` measured 3.3 V relative to control `GND` with the Pi powered;
  logic power wiring passed.
- With the chassis raised, a guarded 0.15-second channel-A pulse moved the
  back-right motor. The command returned GPIO5, GPIO6, GPIO12, and GPIO25 low.
- A guarded 1.0-second pulse ran smoothly with the wheels removed. For this
  back-right motor wiring, GPIO5/AIN1 high and GPIO6/AIN2 low is defined as
  forward rotation.
- A guarded 1.0-second reverse pulse also ran smoothly. GPIO5/AIN1 low and
  GPIO6/AIN2 high is therefore reverse rotation. All control pins returned low
  after both commands.
- A guarded 5.0-second forward run completed smoothly. All four control pins
  returned low afterward, and the TB6612 chip remained cool.

## Why This Is the First Powered Test

This test proves one boundary at a time:

```text
Pi logic -> TB6612 channel A -> battery current -> one motor
```

The LM2596 and mobile Pi power are deliberately excluded. If the test fails,
the failure must be in the GPIO, driver, battery harness, or motor path.

## Power Domains

```text
Pi official supply -> Pi -> 3.3 V logic and GPIO signals
NiMH battery -------> TB6612 VM -> motor

Pi ground ----------+
                     +-> common TB6612 ground
Battery negative ---+
```

The grounds are joined so the Pi and driver share the same zero-volt reference.
The Pi's 3.3 V rail does not power the motor.

## Existing Parts Used

- Raspberry Pi 4 and official power supply
- One TB6612FNG module
- One motor on the raised chassis
- Charged 7.2 V NiMH battery
- One loose Tamiya connector that mates with the battery
- Six M-F Dupont jumpers for logic
- Red/black motor wire supplied with the chassis
- One 18 AWG barrel-pigtail pair for the battery harness
- Solder and heat-shrink
- Multimeter

No wire cutting or stripping is required. All used pigtail ends are already
prepared.

## Exact Logic Wiring

The male end of each M-F jumper is soldered into the TB6612 hole. The female end
plugs onto the Raspberry Pi's existing male GPIO header.

| TB6612 | Pi function | BCM GPIO | Pi physical pin | Suggested colour |
| --- | --- | ---: | ---: | --- |
| `VCC` | 3.3 V logic power | N/A | 1 | Red |
| Control-side `GND` | Logic ground | N/A | 6 | Black |
| `STBY` | Driver enable | GPIO25 | 22 | Yellow |
| `PWMA` | Motor A speed command | GPIO12 | 32 | Blue |
| `AIN1` | Motor A direction input 1 | GPIO5 | 29 | Green |
| `AIN2` | Motor A direction input 2 | GPIO6 | 31 | White |

`BIN1`, `BIN2`, `PWMB`, `BO1`, and `BO2` remain disconnected for this test.

## Battery Harness Without Cutting Wire

Use one 18 AWG barrel-pigtail pair:

```text
Battery Tamiya connector
  -> mating loose Tamiya connector
  -> red/black wires of female barrel pigtail
  -> barrel connection
  -> male barrel pigtail
  -> red wire to TB6612 VM
  -> black wire to TB6612 power-side GND
```

The battery-side barrel connector is female so its live contacts are recessed.
Polarity must be measured at the rover-side pigtail before it is soldered to the
driver. Wire colour alone is not accepted as proof.

## Motor Wiring

```text
TB6612 AO1 -> one chassis-supplied motor wire -> motor terminal 1
TB6612 AO2 -> one chassis-supplied motor wire -> motor terminal 2
```

Motor polarity only determines direction. If the wheel turns opposite to the
defined forward direction, software can reverse it or the two motor wires can
be swapped later. Inspect the manually stripped ends first: the strands should
be intact, tightly twisted, and unable to touch the neighbouring terminal.

## Safe Initial State

- Battery disconnected.
- Pi powered off while GPIO wires are attached.
- `STBY` is held low by the TB6612 chip when not actively driven.
- Chassis secured with every wheel off the floor.
- Battery connector remains reachable for immediate disconnection.
- First command is low PWM for less than one second.

## Tests Before Motor Power

1. Inspect every solder joint for bridges to adjacent pads.
2. Measure continuity from Pi-end female connectors to their corresponding
   TB6612 pads.
3. Verify no continuity between adjacent control pins.
4. Measure battery-harness polarity and voltage.
5. Verify `VCC` is not shorted to `VM` or ground.
6. Power the Pi with the battery still disconnected.
7. Verify GPIO outputs are low before enabling `STBY`.

## Acceptance Criteria

- The motor remains stopped during Pi boot.
- A short forward command turns only motor A.
- A stop command stops the motor immediately.
- A reverse command changes direction.
- Disconnecting or lowering `STBY` stops the motor.
- The driver and wiring remain cool.

Only after these pass will the same method be extended to the other motors.

## Primary References

- Raspberry Pi GPIO header and 3.3 V logic:
  <https://www.raspberrypi.com/documentation/computers/raspberry-pi.html#gpio-and-the-40-pin-header>
- Toshiba TB6612FNG pin functions and operating limits:
  <https://toshiba.semicon-storage.com/info/TB6612FNG_datasheet_en_20141001.pdf?did=10660&prodName=TB6612FNG>
