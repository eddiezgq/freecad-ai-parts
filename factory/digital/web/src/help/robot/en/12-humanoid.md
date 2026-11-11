# Wheeled humanoid WQ-H1

> The robot plant's third complete robot (round 71): the upper body is humanoid — 16 joint modules in the two arms, waist and head — and the lower body is one of the plant's own WQ-AGV300. A robot inside a robot, so MRP explodes several levels at once.

## What a WQ-H1 is made of

| Part | Joint modules | Other |
|---|---|---|
| Left arm, right arm | Each: medium joint WQJ-M × 2, small joint WQJ-S × 4 | Forearm tube, two-finger electric gripper |
| Waist | Large joint WQJ-L × 2 | Waist base (machined from aluminum bar) |
| Head | Small joint WQJ-S × 2 (pitch, pan) | Stereo camera in the head |
| Torso | — | Torso shell, shoulder frame (machined from aluminum plate), humanoid main controller, harness |
| Chassis | — | One WQ-AGV300 (which itself has two drive units, each with a WQR-105 from the gearbox plant) |

16 joint modules in all: large 2, medium 4, small 10; that is 16 harmonic drives, 16 servo motors and 16 encoders. All parameters and the price (example: $68,000) are example values.

```anim
name: mrp
caption: Level within level: WQ-H1 → joint modules, WQ-AGV300 → drive units → WQR-105
```

## How it is built

1. Machining: torso shell, shoulder frame, waist base, forearm tubes;
2. Joint assembly and joint test: 16 joint modules (the same line as the cobot, so the joint test bench gets busier);
3. AGV assembly and commissioning: the chassis is first made into a passing WQ-AGV300;
4. **Humanoid final assembly** (new station HA-1, about 3 hours): mount the waist, torso, two arms and head on the chassis;
5. **Dual-arm and hand-eye calibration** (at robot calibration station CAL-1): measure the relative pose between the two arm bases, and the hand-eye relation from the head camera to the hands;
6. **Humanoid integration test** (at AGV commissioning area AT-1): drive a short way, reach a table, pick up a box with both hands, and record the cycle time;
7. Packing, shipping, invoicing.

Three inspection items (example nominals): dual-arm relative pose error ≤ 1.0 mm, hand-eye calibration error ≤ 3.0 mm, integration cycle time ≤ 40 s — all recorded on the humanoid integration test operation (ERPNext has one inspection template per item); the two calibration items are values remeasured during integration.
Robot calibration station CAL-1 already has only one person who can run it and is also the cobot's calibration station; when both robots are ordered together it has to serve two lines — visible both in capacity under “Orders & planning” and in “People & shifts”.

Lab 30 is in the last section of this chapter; the dynamics model is in the next section; field service and the *Humanoid Robots and Embodied AI* course come later.

## Dynamics model (parts library B-HUM-WQH1)

**B-HUM-WQH1** in the parts library is this WQ-H1 (round 75): the 3D shape, URDF and MuJoCo simulation file can all be downloaded, and the “Motion & dynamics” page can select it directly.

- The 16 joints map one-to-one to the BOM: waist W1, W2 (large joints), head H1, H2 (small joints), left and right arms A1–A6 (the two shoulder joints medium, the rest small);
- Joint module mass, motor, harmonic drive, ratio and friction use the same data as WQ-CR5; arm tubes, torso, shoulder frame, waist base, grippers, camera and main controller each count as one mass;
- The chassis (one WQ-AGV300) is fixed to the ground in simulation; only the upper body is studied — driving and chassis dynamics come later;
- Two ready-made poses: zero (standing straight, arms hanging) and box hug (arms forward). Holding a box with 2.5 kg in each hand, the most loaded joints are the shoulders, still within the joint modules' torque limits.

All are example values; the whole robot is about 153 kg, the upper body about 40 kg.

## Hands on: take a WQ-H1 and watch MRP explode it

In “Orders & planning” choose WQ-H1, quantity 1, and click “Run MRP”. See how many joint modules must be made and whether harmonic drives and WQR-105 must be requested. When the result appears, this step ticks itself.

```goto
tour: planner-order
label: Take me to take an order and run MRP
```

```live
kind: kpi
```

## Your pick

```quiz
q: For 1 WQ-H1, how many small joint modules WQJ-S does MRP need?
options:
  - 10 | right | 4 per arm and 2 in the head: 4 × 2 + 2 = 10
  - 8 | wrong | Head pitch and pan each use a small joint too
  - 6 | wrong | That is the total joints of one cobot
more: #What a WQ-H1 is made of
```

```quiz
q: Which calibration station do both the cobot WQ-CR5 and the wheeled humanoid WQ-H1 use? What should you watch when both are ordered together?
options:
  - Robot calibration station CAL-1: the cobot's calibration and outgoing inspection and the humanoid's dual-arm and hand-eye calibration are all on it, and only one person can run it — stagger the schedule and train an apprentice | right | A shared station plus a single point of dependency is the easiest way to block two lines
  - Humanoid assembly station HA-1: both robots are assembled there | wrong | HA-1 assembles only humanoids; the cobot is assembled in robot assembly cell RA-1
  - Load run-in stand RUN-R1 | wrong | Only the cobot goes on the run-in stand; the humanoid is tested in the AGV commissioning area
more: #How it is built
```

## Lab 30: one wheeled humanoid from order to delivery

Under “Labs & tasks → Lab 30” (round 74). Individual, 4 class hours; the platform scores 60 points automatically, and the 40-point report is graded by the teacher.

| Task | What you do | Points |
|---|---|---|
| 1 Order and MRP | Take 1 WQ-H1: how many work orders, how many joint modules, where the chassis comes from | 10 |
| 2 Release by level | Machined parts → joint modules, AGV drive units → AGV chassis → humanoid; 5 points off for each mistake | 10 |
| 3 Two robots competing for one station | Take 1 WQ-CR5 in the same week; find the station both robots use that only one person can run, and choose a feasible fix for this week | 10 |
| 4 Judge whether a humanoid passes | Compare the three integration test items with their tolerances | 10 |
| 5 Finish into stock, invoice | Ticks itself | 10 |
| 6 This humanoid's cost | How many percent actual is above (below) standard, the work order with the biggest variance | 10 |

The fixes for task 3 are computed on the spot from that station's load this week and the skill matrix: if it fits, stagger the schedule; if only one person can do it, train an apprentice. Subcontracting is impossible (calibration needs the plant's own station and this robot's data), and skipping calibration means it cannot ship.
