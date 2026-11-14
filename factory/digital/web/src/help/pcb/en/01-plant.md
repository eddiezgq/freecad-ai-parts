# This plant: WenQuest Digital Industrial Park · PCB plant

> The park's third plant: it turns bare boards and components into three kinds of circuit boards; the driver boards in the robot plant's joints and the control boards in its AGVs are all bought here.

## What it makes

| Product | ID | Example price | Where it is used |
|---|---|---|---|
| Joint servo driver board (48 V, three-phase, current sensing + encoder interface) | DRV-JOINT | $160 | Rev A; the robot plant's joint modules used it before round 118 |
| Joint servo driver board Rev B (encoder interface chip, brake driver with coil current sensing, output-side encoder) | DRV-JOINT-B | $165 | One per joint module in the robot plant from round 118 |
| AGV control board (dual motor control + CAN + safety IO) | CTRL-AGV | $700 | One per AGV in the robot plant |
| Encoder read-head board (sine/cosine output) | ENC-RD | $60 | To be sold to the sensor plant |
| Lockstitch sewing machine controller (220 V input, PFC, main-shaft servo, 4 solenoids, stitch-length stepper, isolated panel port) | CTRL-LS | $95 | Round 159 design; sold first to the “Sewing Machine Maker (Demo)” (the sewing plant joins the park later) |

Prices, times and nominal values are all **example values**. The driver board has a KiCad design ([PCB design](/pcb-design), example design, not hardware-verified);
the chips it uses are example selections; other purchased items use generic names marked “part number to be confirmed”, with no made-up vendor part numbers.

## The shop

One **SMT line** (boards pass through in order) plus a **back end**:

- SMT line: solder paste printing → solder paste inspection SPI → high-speed placement (chip components) → multi-function placement (ICs, MOSFETs) → reflow → automated optical inspection AOI;
- Back end: selective soldering (through-hole terminals) → in-circuit test ICT → programming → conformal coating → burn-in → functional test FCT → packing.

The reflow oven takes 8 boards at a time and the burn-in room 40; the other machines work one board at a time.

```anim
name: flow
caption: Order → MRP → ERPNext → SMT line → back-end test → stock and invoice, the same line as the other two plants
```

## Hands on: find the reflow oven in the 3D shop

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
q: What is the biggest difference between the PCB plant and the robot plant?
options:
  - The PCB plant has no inspection | wrong | Quite the opposite: four inspections — SPI, AOI, ICT, FCT — more than the robot plant
  - The front end is one continuous SMT line that boards pass through in order; lots of inspection and test data | right | The robot plant's front end is machining, scheduled operation by operation across several machines
  - The PCB plant does not use ERPNext | wrong | All plants use the same platform: orders, work orders, job cards and inspections all go into ERPNext
more: #The shop
```

```ask
q: What machines does the PCB plant have, and what does each do?
```

:::查表

## Equipment list

| Workstation | Machines | What it does |
|---|---|---|
| Solder paste printer | 1 | Prints solder paste onto pads through a stencil |
| Solder paste inspection SPI | 1 | Measures the paste volume and height on every pad |
| Placement machines | 2 | The high-speed placer places resistors and capacitors; the multi-function placer places the MCU, driver chips and MOSFETs |
| Reflow oven | 1 (10 zones) | Melts the paste into joints; the oven log records peak temperature and time above liquidus |
| Automated optical inspection AOI | 1 | Takes images to find tombstoning, bridging, insufficient solder, offset, wrong parts, reversed parts |
| Selective soldering | 1 | Solders through-hole power terminals and connectors |
| In-circuit tester ICT | 1 | A bed of nails measures each component: shunt resistance and so on |
| Programming station | 1 | Writes firmware |
| Conformal coater | 1 | Sprays conformal coating |
| Burn-in room | 1 | Powered high-temperature burn-in |
| Functional test bench FCT | 1 | Powers up and tests bus voltage, current sensing, dead time, encoder interface |
| Packing bench | 1 | Packs into ESD bags |
| Component store, finished goods store, logistics carts | 2 + 2 | The component store has dry cabinets |
