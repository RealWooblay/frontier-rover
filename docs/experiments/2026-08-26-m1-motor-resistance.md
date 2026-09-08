# M1 Motor Winding Resistance

Status: in progress

## Objective

Estimate each motor's stall current and decide whether one TB6612FNG channel
can drive one motor safely.

## Concept Being Learned

A stopped brushed motor draws its greatest current because there is no
rotation-generated back EMF opposing the battery. Winding resistance gives a
conservative stall-current estimate using Ohm's law.

## Hardware Used

- Four TT brushed DC gearmotors on the XR-003 chassis
- Digital multimeter on the 200 ohm range
- No battery or motor driver connected

## Architecture / Signal Path

```text
multimeter -> motor terminal -> winding and brushes -> motor terminal -> multimeter
```

## Assumptions

- Measurements are taken with the wheel stopped.
- Both probes contact the motor's electrical terminals, not its casing.
- Probe resistance will be measured and subtracted.

## Predicted Result

Each motor should show a finite low resistance. Measurements may change with
rotor position because the brushes contact different commutator segments.

## Procedure

1. Set the meter to the 200 ohm range.
2. Measure probe resistance with the tips touching.
3. Measure each stopped motor in several rotor positions.
4. Record the lowest stable reading.
5. Subtract probe resistance.
6. Estimate stall current at nominal and fully charged battery voltage.

## Measurements

| Measurement | Raw resistance | Corrected resistance | Status |
| --- | ---: | ---: | --- |
| Probe leads | 1.0 ohm | N/A | Measured |
| Motor 1, physical position pending | 6.2 ohms minimum; 6.5 ohms second reading | 5.2 ohms | Measured |
| Motor 2, physical position pending | 6.5 ohms minimum; 7.4 ohms second reading | 5.5 ohms | Measured |
| Motor 3, physical position pending | 6.3 ohms minimum; 6.5 ohms second reading | 5.3 ohms | Measured |
| Motor 4, physical position pending | 6.3 ohms minimum; 6.5 ohms second reading | 5.3 ohms | Measured |

After correcting for probe resistance, the measurements imply:

| Motor | At 7.2 V nominal | At approximately 8.4 V fully charged |
| --- | ---: | ---: |
| Motor 1 | 1.38 A | 1.62 A |
| Motor 2 | 1.31 A | 1.53 A |
| Motor 3 | 1.36 A | 1.58 A |
| Motor 4 | 1.36 A | 1.58 A |

These are conservative stall-current estimates, not expected free-running
current. They exceed the TB6612FNG's 1.2 A average rating but remain below its
3.2 A specified peak rating.

The `25 ohm` value observed while turning the wheel is excluded. A rotating
motor generates voltage, so an ohmmeter reading taken during rotation is not a
valid winding-resistance measurement.

## Actual Result

All four motors produced similar corrected readings from 5.2 to 5.5 ohms. The
estimated fully charged stall-current range is 1.53-1.62 A per motor.

The four chassis-supplied motor wires measured 1.1, 1.1, 1.3, and 1.1 ohms
end-to-end against the same 1.0 ohm probe baseline. All four are continuous and
are suitable for the initial test after checking that no loose strands can
touch an adjacent terminal.

## Failure Observed

The meter initially displayed over-range (`1`) while the wheel was moving or
the probes were not making stable contact.

## Diagnosis

Resistance must be measured with the rotor stationary and firm contact on both
terminals. The rotor may be repositioned between readings, but not during one.

## Changes Made

None. This is a non-powered characterisation test.

## Acceptance Result

Conditional pass for initial bench experiments:

- Use one motor per TB6612FNG channel.
- Raise all wheels off the floor.
- Begin with short, low-duty PWM commands.
- Never hold a wheel stalled.
- Keep the battery connector physically accessible for immediate disconnection.

This does not yet approve sustained four-motor operation. Running current and
driver temperature must be measured during staged bring-up.

## Transfer to Other Domains

Characterising an actuator before selecting its driver is the same process used
for pumps, valves, thrusters, relays, and other robotic loads.
