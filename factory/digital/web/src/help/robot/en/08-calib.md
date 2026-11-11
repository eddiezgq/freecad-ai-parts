# Robot calibration and lab 26

> Every WQ-CR5 differs slightly from its nominal geometry. The robot calibration station measures a set of poses with a laser tracker, identifies the parameter deviations by least squares, compensates them, and verifies with another set of poses.

## Why calibrate

The robot controller computes where the tool is from the **nominal DH parameters**. Every robot built has deviations: each of the 6 joints has zero, offset, link length and twist deviations — 24 in all.
Part of the zero deviation comes from the zero residuals the 6 joints showed on the joint test bench. Added up, the tool is off by about 1 mm (example magnitude) —
repeatability is excellent (0.02 mm), yet absolute position is inaccurate. Calibration finds these deviations and compensates them in the controller; after calibration the mean error falls to 0.1–0.15 mm (example), with ≤ 0.5 mm passing.

```anim
name: joint-test
caption: The joint's zero is calibrated on the test bench; its residual goes with the joint into the robot and becomes part of the robot's zero deviation
```

## How to calibrate

1. The robot moves to 30 poses and the laser tracker measures the tool point position (example: measurement noise 0.02 mm);
2. Compute these 30 positions from the nominal parameters and compare with the measurements; the differences are the residuals;
3. Take partial derivatives of the residuals with respect to the 24 parameters (the Jacobian), solve the deviations by least squares, and iterate a few times;
4. After compensation, verify with another 20 poses.

The axial offsets of adjacent parallel axes (J2, J3, J4) can only be separated as a sum, so only 21 combinations of the 24 parameters are separable — *Robotics* section 13.5 covers this weakness of DH parameters at parallel axes.
The **condition number** tells whether a set of poses can separate the parameters: too few poses, or poses too concentrated (all in a small region), make the condition number large, noise is amplified into the parameters, and calibration makes things worse.
Errors outside the geometric model (joint compliance, gear backlash, example 0.06 mm) cannot be calibrated away, so the error does not fall to zero.

## Hands on: look at a robot's calibration and try other poses

First take a WQ-CR5 in “Orders & planning” (the one from lab 24 is fine) and carry it through robot calibration. Click this robot in “Quality → Robot calibration” in the left sidebar:
switch to “concentrated near common postures” and look at the condition number and post-calibration error; then switch to 8 poses. Then answer in “Labs & tasks → Lab 26”; once you answer a task, this step ticks itself.

```goto
tour: calib-page
label: Show me robot calibration
```

```live
kind: kpi
```

## Your pick

```quiz
q: All 30 measurement poses are within ±10° of common postures, and the condition number goes from 20 to 5000. What happens to the post-calibration error across the whole workspace?
options:
  - Smaller: concentrated poses measure more carefully | wrong | Concentrated poses cannot separate the parameters, and noise is amplified into them
  - Larger: this pose set cannot separate the parameters, the identified deviations are skewed by noise, and outside that small region the compensation is wrong | right | Measurement poses should cover the workspace
more: #How to calibrate
```

```quiz
q: The joint test bench's zero calibration program drifted by 30″; robots assembled afterwards are calibrated. What do you see?
options:
  - The identified zero deviations of the joints all gain about 30″, and calibration still compensates them | right | The zero deviation comes into the robot from the joint test bench; robot calibration finds it
  - Calibration fails and the robot is rejected | wrong | A 30″ zero deviation is within what calibration can compensate
  - Nothing visible | wrong | Zero deviation is exactly one of the parameters calibration identifies
more: #Why calibrate
```

```ask
q: For a robot that only works at one station, can it be calibrated only near that station? What is the cost?
```

:::查表

## Lab 26 scoring

| Task | Content | Points |
|---|---|---|
| 1 | Compute the tool position with nominal DH parameters (within 0.5 mm) | 10 |
| 2 | Spread vs concentrated: which has the larger condition number (both must have been done on the calibration page) | 10 |
| 3 | The two joints with the largest zero deviation | 10 |
| 4 | Mean error after calibration, verdict | 10 |
| 5 | What happens with 8 poses (8 must have been done on the calibration page) | 10 |
| 6 | Where the zero deviation comes from | 10 |
| Report | Lab guide and report template (bilingual) at the top right of the lab page | 40 |

## Nominal parameters and error magnitudes (example values)

Nominal DH (standard DH, T = Rz(θ)·Tz(d)·Tx(a)·Rx(α)): J1 d = 150 mm, α = 90°; J2 a = −400 mm; J3 a = −360 mm; J4 d = 120 mm, α = 90°;
J5 d = 100 mm, α = −90°; J6 d = 90 mm. The tool point is at (50, 0, 100) mm in the flange frame.
Errors: assembly zero σ 0.01° (plus the joint test bench zero residual), link length and offset σ 0.3 mm, twist σ 0.05°; laser tracker noise 0.02 mm; non-geometric 0.06 mm.
