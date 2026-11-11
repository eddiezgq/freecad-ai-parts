# Load run-in and lab 28

> A calibrated WQ-CR5 goes on the load run-in stand: carrying a 5 kg steel block it performs a standard motion while the drives record the torque of all 6 joints. Compare it with the parts library model's simulation: where they differ, why, and whether the model can be made accurate.

## What the run-in stand measures

Before shipping, every robot carries a **standard load** (a steel block of about 5 kg) through a standard motion: three quintic joint-space segments, 1.2 s each with 0.3 s pauses, 4.8 s in all.
The drives convert motor current into each joint's torque and record it at 100 Hz. Two things are checked:

1. **Torque margin**: each joint's RMS torque must not exceed the harmonic drive's rated torque, and its peak must not exceed the joint torque limit (motor peak × ratio × efficiency, or the gearbox's repeated peak, whichever is smaller);
2. **Do simulation and measurement agree**: the “simulation” is the same motion computed with the parts library model B-ARM-WQCR5 (nominal friction) — the same model the “Motion & dynamics” page uses.

Measured torque = rigid-body dynamics + this robot's own friction + measurement noise. Coulomb friction comes from the no-load friction torque its 6 joints measured on the **joint test bench**
(recorded first-in first-out at robot assembly); viscous friction varies with grease and temperature, is not measured by the bench, and differs per robot (example: 0.6–1.6 × nominal).

```anim
name: joint-test
caption: The no-load friction torque measured on the joint test bench goes with the joint into the robot and becomes the Coulomb friction in the run-in torque
```

## Where the gap comes from and how to fix the model

Subtract the rigid-body inverse dynamics from the measurement, and what remains is friction plus noise:

τ_measured − τ_rigid = f_c tanh(θ̇/0.01) + f_v θ̇

Two unknowns per joint, solved by least squares using only samples with |θ̇| > 0.05 rad/s (near zero speed the friction direction is undefined) — the friction identification of *Robotics* section 26.4.
The identified f_c should agree with the test bench value while f_v differs from nominal, showing that the gap comes mainly from viscous friction. Write the identified values back into the model and compute again:
the RMS gap between simulation and measurement falls to the level of measurement noise (example: large joints σ 0.1 N·m) — the model now matches this robot, and what remains cannot be measured more precisely.
The gap between “simulation and reality” in *Robotics* section 29.4 is exactly this.

## Hands on: look at a robot's run-in

First have a WQ-CR5 that has been through robot calibration (order in lab 24, calibration in lab 26). Choose it in “Quality → Load run-in” in the left sidebar: switch joints to see measured and simulated curves,
and look at the table's RMS gaps, identified friction and torque margins; download the CSV (with τ_rigid) and do the identification yourself. Then answer the lab 28 tasks on the same page; once you answer one, this step ticks itself.

```goto
tour: runin-page
label: Show me load run-in
```

```live
kind: kpi
```

## Your pick

```quiz
q: For one robot the identified J1 Coulomb friction f_c almost equals the test bench value, but the viscous friction f_v is 1.5 × nominal. Where does the gap between simulation and measurement mainly come from?
options:
  - Viscous friction: the parts library model uses nominal values, and this robot differs | right | The test bench measures only no-load Coulomb friction; viscous friction differs per robot
  - Coulomb friction: the test bench measured it wrong | wrong | f_c agrees with the bench, so the bench measured it correctly
  - Link masses were estimated wrong | wrong | Wrong masses would offset whole acceleration phases, and the identified friction would not agree either
more: #Where the gap comes from and how to fix the model
```

```quiz
q: After writing the identified friction back into the model, J2's RMS gap falls from 1.2 N·m to 0.1 N·m, and the measurement noise σ is 0.1 N·m. Can it go lower?
options:
  - Not by changing the model: what remains is measurement noise | right | At the noise level, the model already matches this robot
  - It can reach zero by identifying a few more parameters | wrong | Noise is random and no model can fit it
more: #Where the gap comes from and how to fix the model
```

```ask
q: If the run-in stand's standard motion were slow all the way, what problem would friction identification run into?
```

:::查表

## Lab 28 scoring

| Task | Content | Points |
|---|---|---|
| 1 | J2 measured peak torque (within 2 %) | 10 |
| 2 | The joint with the biggest gap between simulation and measurement | 10 |
| 3 | Identify J1's f_c and f_v (each within 5 %) | 10 |
| 4 | Which term the gap mainly comes from | 10 |
| 5 | J2 measured RMS (within 3 %), whether the robot's torque margin passes | 10 |
| 6 | What the remaining gap is after writing back to the model | 10 |
| Report | Lab guide and report template (bilingual) at the top right of the lab page | 40 |

## Modules and example values

Large joint WQJ-L (J1, J2): harmonic size 32, rated 137 N·m, repeated peak 333 N·m; nominal Coulomb friction 1.2 N·m, viscous 2.0 N·m·s/rad; measurement noise σ 0.1 N·m.
Medium joint WQJ-M (J3): size 25, rated 67 N·m; nominal 0.8 N·m, 1.0; noise 0.08. Small joint WQJ-S (J4–J6): size 17, rated 24 N·m; nominal 0.4 N·m, 0.3; noise 0.02.
σ of no-load friction torque on the joint test bench: large 0.15, medium 0.10, small 0.08 N·m.
