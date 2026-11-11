# Labs 24 and 25

> The robot plant's two labs: one cobot from order to delivery; layered root cause and 8D for a joint backlash anomaly. There is also lab 31: troubleshooting a brake alarm at joint final test. Open them under “Labs & tasks” in the left sidebar.

## Lab 24: one cobot from order to delivery

Take 1 WQ-CR5, run MRP, release by level, judge whether a joint passes, calibrate the robot, stock and invoice it, compute this robot's cost variance, review.
The platform scores 60 points automatically from your own order; the report is 40. Release order is the focus of scoring: each place where a level is released before the lower level it uses loses 5 points.

```anim
name: bom-tree
caption: Build from the bottom up: made parts → joint modules → robot
```

## Lab 25: tracing a joint backlash anomaly and 8D

The teacher injects a hidden problem (one of five); you find the out-of-control signal on the control chart, then stratify by **assembly station**, **harmonic drive lot** and **test sequence**
to see which group alone has the problem; then open an 8D and choose fixes; after the teacher approves they go to the shop, and you verify with post-fix data (all pass and Cpk ≥ 1.33).

```video
name: robot-joint
caption: Reading joint test data on the quality page
```

## Stratification

Under the control chart on the quality page, the robot plant's joints have two extra small tables: count, mean and out-of-tolerance units by assembly station and by gearbox lot.
If only one group is off, the cause is in that group; if all groups drift together with test sequence, the cause is in something they all share.

Round 120 added two problems using two measurements from joint test that the Rev B driver board brings: **dual-encoder cross-check difference** (joints assembled at one station are high — the encoder locating fixture is worn) and **brake holding torque** (every joint lower than the one before in test sequence — the test bench's torque sensor drifted while the brakes are fine: bad data is not necessarily a bad product). So do not stare only at backlash: look over all the characteristics on the control charts first, and check whichever is out of control.

## Lab 31: troubleshooting a brake alarm at joint final test

Three joint modules reported fault 7 (brake) at final test. The page has each unit's test record: the CAN frames the driver board sent (raw bytes only — decode them yourself with the protocol excerpt on the page) and three waveforms — brake coil current, joint angle, output switch.
You decode the alarm's subcode, judge whether the brake in the motor is bad (wire break, coil short) or switch transistor Q7 on the driver board (failed short, always on), decide the repair, and release only after a passing retest.

The most important point: for the unit with the shorted transistor, the heartbeat frame says “brake engaged”, yet the coil current never stops — **the frame reports the command; the current is the fact**. That is why the firmware does not turn off the output and holds the motor in place, so the swing arm does not fall.
The test records are real output of the driver board Rev B firmware running in the Renode simulator (scenarios ⑮ ⑯ ⑰ in the PCB plant's “PCB design → Rev B → Motor” tab).

## Hands on: look at the control chart and open an 8D

```goto
tour: quality-chart
label: Show me the control chart and open a quality issue
```

```live
kind: kpi
```

## Your pick

```quiz
q: The backlash control chart is out of control. By assembly station: JA-1 mean 0.61′, JA-2 mean 0.95′; by lot: every lot around 0.75′. Where is the cause most likely?
options:
  - One lot of harmonic drives | wrong | The lot means are similar, so the lot is not the cause
  - Assembly station JA-2 | right | Only JA-2's joints are high; lots look similar because both stations used every lot
  - The test bench | wrong | The test bench is shared and would not make only JA-2's joints high
more: #Stratification
```

```quiz
q: D5 of the 8D chose “tighten outgoing inspection, retest 100 % of joints”. Can this 8D be verified effective?
options:
  - Yes, the bad ones are all picked out | wrong | Picking them out does not stop making them; that is a D3 containment action
  - No: it does not remove the cause, post-fix data stays off, and Cpk cannot reach 1.33 | right | Corrective actions must target the root cause
more: #Lab 25: tracing a joint backlash anomaly and 8D
```

```ask
q: What other dimensions can stratification use?
```

:::查表

## Scoring at a glance

| Lab | Tasks | Points |
|---|---|---|
| 24 | Order and MRP 10, release by level 15, joint verdict 10, calibration, stock and invoice 10, cost 10, review 5 | 60 + report 40 |
| 25 | Detect out-of-control 10, stratify 15, open 8D 10, fix and verify 15, D7 close 10 | 60 + report 40 |
| 26 | Forward kinematics 10, pose selection 10, identification 10, verification verdict 10, too few poses 10, where zero comes from 10 (see chapter 8) | 60 + report 40 |
| 27 | MRP 10, sent to the gearbox plant 10, arrival inspection and stock 10, lead time 10, safety stock and reorder point 10, review 10 (see chapter 7) | 60 + report 40 |
| 28 | J2 peak 10, joint with the biggest gap 10, identify J1 friction 10, where the gap comes from 10, torque margin 10, write back to the model 10 (see chapter 9) | 60 + report 40 |
| 29 | Robot and joint in alarm 10, as-built record 10, cause 10, recall scope 10, service order completed 10, the cost 10 (see chapter 11) | 60 + report 40 |
| 30 | Order and MRP (including where the chassis comes from) 10, release by level 10, two robots competing for one station 10, humanoid verdict 10, stock and invoice 10, cost 10 (see chapter 12) | 60 + report 40 |
| 31 | Decode the alarm frame 10, find the bad part 10, read the waveforms 10, safety logic 10, decide the disposition 10, retest and release 10 | 60 + report 40 |

Lab guides and report templates are at the top right of each lab page.
