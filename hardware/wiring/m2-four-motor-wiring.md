# M2 Four-Motor Wiring

Status: replacement left board and all four motors passed individual tests

## Bring-Up Results

- The failed left TB6612 module was replaced with the owned spare.
- All four motors passed individual forward and reverse tests.
- A floor test revealed a software direction mismatch: back-right ran backward
  while the other three motors ran forward. Back-right and back-left therefore
  have software direction inversion; their physical wiring remains unchanged.
- Individual tests identified the physical left-side channel assignment:
  channel A is front-left and channel B is back-left.
- The rover has a large open-loop drive imbalance. The closest smooth result was
  left 9% and right 80%. A slower successful result used left 8% and right 80%
  in alternating 0.1-second on/off pulses. Forward and reverse both passed with
  that pulsed setting. This is a temporary calibration, not proof that the
  right-side torque problem is resolved.
- Both right-side motors ran in both commanded directions.
- The left board measured correct motor and logic supply voltages.
- `STBY`, both PWM inputs, and all four direction inputs measured 3.3 V at the
  left-board solder pads when commanded high.
- Neither left motor moved.
- Left channel A measured 0 V across `AO1` and `AO2` during a full forward
  command. The motors therefore did not receive drive voltage; this does not
  indicate simultaneous failure of both motors.
- The complete left-board control harness was moved to the known-working
  right-board Raspberry Pi pins. Neither left motor moved under the same GPIO
  commands that previously drove both right motors. This rules out the original
  left-side GPIO selection and Pi header positions.
- The left board was then connected to the battery branch that successfully
  powered the right board. Neither channel moved. With GPIO selection, control
  signals, static supplies, and battery branch substituted or measured, the
  left TB6612 module is confirmed failed and must be replaced by the owned spare.
- Both left motors ran when powered directly, proving their windings and
  mechanical operation. Applying battery voltage at the left board's `AO1/AO2`
  and `BO1/BO2` pads also ran the corresponding motors, proving the complete
  output wiring and solder paths. Do not repeat that output-pad test because it
  can back-feed and damage an H-bridge. These results further isolate the fault
  to the left module's switching stage.

## Motor Assignment

| Driver | Channel | Motor | Output-to-terminal mapping |
| --- | --- | --- | --- |
| Right board | A | Back-right | Existing tested wiring; software inverted |
| Right board | B | Front-right | `BO1` to lower tab; `BO2` to upper tab |
| Left board | A | Front-left | `AO1` to upper tab; `AO2` to lower tab |
| Left board | B | Back-left | `BO1` to upper tab; `BO2` to lower tab; software inverted |

Upper and lower are defined with the rover upright. Reversing a motor's two
terminals is electrically valid; software records the direction inversion.

## Raspberry Pi Connections

### Right Board

| TB6612 | Colour | BCM GPIO | Physical pin |
| --- | --- | ---: | ---: |
| `VCC` | Red | 3.3 V | 1 |
| Control `GND` | Black | Ground | 6 |
| `STBY` | Yellow | GPIO25 | 22 |
| `PWMA` | Blue | GPIO12 | 32 |
| `AIN1` | Green | GPIO5 | 29 |
| `AIN2` | White | GPIO6 | 31 |
| `PWMB` | Grey | GPIO13 | 33 |
| `BIN1` | Orange | GPIO16 | 36 |
| `BIN2` | Purple | GPIO20 | 38 |

### Left Board

| TB6612 | Colour | BCM GPIO | Physical pin |
| --- | --- | ---: | ---: |
| `VCC` | Red | 3.3 V | 17 |
| Control `GND` | Black | Ground | 20 |
| `STBY` | Yellow | GPIO24 | 18 |
| `PWMA` | Blue | GPIO18 | 12 |
| `AIN1` | Green | GPIO17 | 11 |
| `AIN2` | White | GPIO27 | 13 |
| `PWMB` | Grey | GPIO19 | 35 |
| `BIN1` | Orange | GPIO22 | 15 |
| `BIN2` | Purple | GPIO23 | 16 |

GPIO numbers and physical pin numbers are different numbering systems. Physical
pin numbers identify positions on the 40-pin header.

### MPU-9250 IMU

| GY-9250 | Raspberry Pi signal | Physical pin |
| --- | --- | ---: |
| `VCC` | 5 V | 2 |
| `GND` | Ground | 9 |
| `SDA` | GPIO2 / I2C1 data | 3 |
| `SCL` | GPIO3 / I2C1 clock | 5 |

The exact HiLetgo breakout listing specifies 3-5 V input with an internal
low-dropout regulator. The installed board returned identity `0x71` from I2C
address `0x68` with this wiring.

## Battery Distribution

The two drivers connect to one 7.2 V battery in parallel:

```text
battery positive -> right VM -> left VM
battery negative -> right GND -> left GND
```

The existing right-board battery input remains unchanged. A second barrel pair
forms a removable board-to-board power link:

- Female source-side pigtail red to right-board `VM`.
- Female source-side pigtail black to the right board's unused power `GND`.
- Matching male pigtail red to left-board `VM`.
- Matching male pigtail black to left-board bottom power `GND`.

Both board grounds are common with the Raspberry Pi through their thin
control-ground wires. Motor power never connects to a Pi power pin.

## Bring-Up Order

1. Keep the Pi and battery disconnected.
2. Inspect every solder joint and remove all solder bridges.
3. Measure each output pair; each connected motor should read approximately
   6-8 ohms including leads and wiring.
4. Connect the control jumpers to the unpowered Pi.
5. Connect the board-to-board power link but leave the battery barrel open.
6. Raise every wheel clear of the bench.
7. Power the Pi and force every control pin low.
8. Connect the battery.
9. Pulse one motor at a time and record physical direction.
10. Only after individual tests pass, test same-side pairs at reduced PWM.

Do not begin with all four motors. Individual tests isolate wiring faults and
limit current while the TB6612 operating margin is still being characterised.
