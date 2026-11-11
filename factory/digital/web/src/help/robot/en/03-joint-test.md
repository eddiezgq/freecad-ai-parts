# Joint testing and robot calibration

> Every joint module goes on the test bench for backlash, friction torque and encoder zero; after calibration each robot is measured for repeatability and absolute positioning error. The data goes into control charts, and anomalies open an 8D.

## What the joint test bench measures

The bench turns forward, then reverse. Just after reversing, the motor turns but the output has not followed yet — that lost motion is **backlash**; the torque needed to turn unloaded is **friction torque**;
after the encoder is fitted its zero is calibrated, and the remaining offset is the **zero calibration residual**. All three have upper limits; exceeding one fails the joint.

```anim
name: joint-test
caption: One forward–reverse cycle: the lost motion is the backlash
```

## Control charts

Data from the joint test bench, robot calibration station, AGV commissioning area and CMM all go into the “Quality” page as in the gearbox plant: choose a characteristic to see its control chart, with the same out-of-control rules.
When points keep drifting to one side but are not yet out of tolerance, that is the time to look for the cause.

```anim
name: spc
caption: Alarm first, then out of tolerance: the earlier you act, the cheaper it is
```

```video
name: robot-joint
caption: Reading joint test and robot calibration data
```

## Hands on: open a quality issue for joint backlash

On the “Quality” page choose a joint characteristic (e.g. “WQJ-L · Backlash”) and look at the control chart; open an 8D for it. Once opened, this step ticks itself (use the “Inspector” role).

```goto
tour: quality-chart
label: Show me the control chart and open a quality issue
```

```live
kind: kpi
```

## Your pick

```quiz
q: A large joint measures backlash 1.15′ (limit 1.0′) and no-load friction torque 1.3 N·m (limit 2.0 N·m). How is it judged?
options:
  - Pass: the friction torque is far below its limit | wrong | Every item must be within its limit; one over fails it
  - Fail: backlash exceeds its limit | right | Every item must be within its limit; go back to joint assembly and this lot of harmonic drives to find the cause
  - Fit it to the robot first; calibration will make up for it | wrong | Calibration corrects geometric parameters, not lost motion on reversal
more: #What the joint test bench measures
```

```quiz
q: On the small joint (WQJ-S) backlash control chart, the last 8 points are all above the center line and none is out of tolerance. What do you do?
options:
  - All pass; leave it | wrong | 8 consecutive points on one side is out-of-control rule 4: the process has changed
  - It is out of control: check this lot of harmonic drives, the assembly station and the test bench, and open an 8D if needed | right | The point of a control chart is to find problems before nonconforming parts appear
  - Loosen the upper limit a little | wrong | Tolerances are set by design and cannot be loosened because the process got worse
more: #Control charts
```

```ask
q: What could make joint backlash grow?
```

:::查表

## Measured characteristics (example values)

| Item | Operation | Characteristic | Nominal | Limit |
|---|---|---|---|---|
| Hollow shaft (large) JS-L | Part inspection | Bearing seat diameter Ø50 k5 | 50.007 mm | 50.002–50.013 mm |
| Hollow shaft (large) JS-L | Part inspection | Bearing seat radial runout | 0.004 mm | 0.01 mm |
| Joint modules large / medium / small | Joint test | Backlash | 0.6 / 0.6 / 0.7′ | 1.0 / 1.0 / 1.2′ |
| Joint modules large / medium / small | Joint test | No-load friction torque | 1.2 / 0.8 / 0.4 N·m | 2.0 / 1.4 / 0.8 N·m |
| Joint modules large / medium / small | Joint test | Encoder zero calibration residual (signed) | 0″ | ±20 / ±20 / ±25″ |
| Cobot WQ-CR5 | Robot calibration | Position repeatability | 0.018 mm | 0.03 mm |
| Cobot WQ-CR5 | Robot calibration | Absolute positioning error after calibration | 0.30 mm | 0.5 mm |
| Handling AGV WQ-AGV300 | AGV commissioning | Docking position error | 4 mm | 10 mm |

These nominals, limits and scatter are all **example values**, written in the plant manifest's “Characteristics”; the simulated shop synthesizes measurements as “nominal + slow drift + normal scatter”.
′ is an arcminute (1/60 of 1°) and ″ an arcsecond.

## Inspection records

When all characteristics of a unit (piece) have arrived, the bridge creates a quality inspection in ERPNext attached to that operation's job card;
an operation with characteristics is a “quality gate”: the job card cannot be submitted until the inspection exists.
