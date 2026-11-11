# This plant: WenQuest Digital Industrial Park · Robot plant

> The park's second plant: it builds six-axis cobots, handling AGVs and three joint modules; the WQR-105 made by the gearbox plant is a purchased item here.

## What it makes

| Product | ID | Example price | How it is made |
|---|---|---|---|
| Six-axis cobot (5 kg payload class) | WQ-CR5 | $18,000 | Three joint modules + upper arm, forearm, base + a purchased control cabinet |
| Handling AGV (300 kg load class) | WQ-AGV300 | $9,500 | Frame + two drive units (each containing a WQR-105 from the gearbox plant) + battery, lidar |
| Joint modules large / medium / small | WQJ-L / WQJ-M / WQJ-S | $1,800 / $1,300 / $900 | Housing and hollow shaft made in-house; harmonic drive, servo motor, encoder purchased |

Prices, times and sizes are **example values**. Purchased part numbers are chosen from the parts library (harmonic drives CSF-32/25/17, bearings 6010/6007/6004, lidar TiM781);
anything not in the library (servo motors, control cabinet, battery) is marked “part number to be confirmed”, with no made-up parameters. Joint driver boards and AGV control boards are bought from the park's WenQuest PCB plant (round 85).

## The shop

The whole plant is built from one plant manifest: machining at the front, assembly, testing and calibration at the back — the same platform as the gearbox plant.

```anim
name: flow
caption: Order → MRP → ERPNext → shop → test and calibration → stock and invoice, the same line as the gearbox plant
```

```video
name: robot-plant
caption: The robot plant's shop and products
```

## Hands on: find the joint test bench in the 3D shop

Open the 3D shop and click a machine to see what it is doing. Once clicked, this step ticks itself.

```goto
tour: open-3d
label: Take me to the 3D shop
```

```live
kind: machines
```

## Your pick

```quiz
q: In which operations does the robot plant differ most from the gearbox plant?
options:
  - Cutting and turning | wrong | The machining front ends of the two plants are similar
  - Assembly, testing, calibration: joint test bench, robot calibration station, load run-in stand, AGV commissioning area | right | These operations produce measurement data that go into control charts on the quality page
  - Packing | wrong | Both plants pack; it is not a difference
more: #The shop
```

```quiz
q: Where does the WQR-105 in the AGV drive unit come from?
options:
  - The robot plant makes it | wrong | The robot plant has no gear machining
  - Bought from the WenQuest gearbox plant; in this phase requested like an ordinary external supplier | right | Real orders between the two plants came in phase two of the park
  - From stock; no need to buy | wrong | Stock runs out; once it reaches safety stock it must be requested
more: 04-agv-gearbox#How the two plants connect
```

```ask
q: What machines does the robot plant have, and what does each do?
```

:::查表

## Equipment list

| Workstation | Machines | What it does |
|---|---|---|
| Band saw | 1 | Cutting: aluminum bar, 40Cr bar, aluminum tube |
| CNC lathes | 2 | Rough and finish turning of joint housings and hollow shafts |
| Vertical machining centers | 2 | Milling and drilling of arm tubes, bases, housings |
| Cylindrical grinder | 1 | Bearing seats of hollow shafts |
| CMM | 1 | Part inspection |
| Joint assembly stations | 2 | Assemble joint modules |
| Joint test bench | 1 | Backlash, no-load friction torque, encoder zero calibration |
| Robot assembly cell | 1 | Robot assembly, packing |
| Robot calibration station | 1 | Geometric parameter calibration, outgoing inspection |
| Load run-in stand | 1 | Run-in under load |
| AGV assembly station, AGV commissioning area | 1 each | Assemble drive units and vehicles, docking accuracy commissioning |
| Stores, logistics carts | 2 + 2 | Raw material and purchased parts store, finished goods store; two carts deliver material in the shop |

## What is available in this phase

The order-to-invoice main line, 3D shop, quality (including joint test data), cost, the hub's production anomalies, help.
The gearbox plant's seven domains (customers and service, safety and environment, maintenance, people, supply chain, energy, business and finance), labs 15–23 and the two-week scenario are only in the gearbox plant in this phase.
