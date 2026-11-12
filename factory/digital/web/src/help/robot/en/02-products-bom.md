# Products and BOM

> A cobot explodes into three levels: robot → joint modules → housings, hollow shafts. Only when a lower level is in stock can the level above draw material.

## Multi-level BOM

Teaching in the gearbox plant makes just one output shaft; one order in the robot plant makes a string of work orders. MRP explodes the bill of materials (BOM) level by level:
purchased items and raw materials are checked against stock; made parts and subassemblies each get a work order.

```anim
name: bom-tree
caption: The WQ-CR5 BOM (simplified): built from the bottom up
```

```anim
name: mrp
caption: Every level is the same: gross requirement − stock − on order = net requirement
```

## Hands on: run MRP for a cobot

In “Orders & planning” choose product WQ-CR5, quantity 1, and click “Run MRP”. When the result appears, this step ticks itself. Count how many work orders are needed.

```goto
tour: planner-order
label: Take me to take an order and run MRP
```

```video
name: robot-order
caption: Taking an order for a cobot: multi-level explosion, release by level, invoice when done
```

```live
kind: kpi
```

## Customizing a cobot: the parameter configurator

When a customer's payload and reach differ from the standard model, use “Cobot customization” in the “Parameter configurator” in the left sidebar: enter rated payload (including gripper), reach and speed;
the configurator sets the upper arm and forearm lengths by the method of *Robotics* section 30.3 (the two differ by 4 cm, the shoulder dead zone hidden in the base module) and picks a large, medium or small module for each joint
(peak from the worst posture plus starting acceleration, continuous from the RMS of the load run-in stand's standard motion, with a 1.2 safety factor; J1 same as J2, the three wrist joints the same),
then produces 3D, a dimension sketch and a quote. The default parameters (5 kg, 860 mm, standard) are the standard WQ-CR5; enter 6 kg and J3 becomes a large module, the quote adding the module price difference and an 8 % non-standard fee;
at 10 kg even the plant's largest module is not enough and the configurator stops you. The order still creates a WQ-CR5 order proposal, with the customization parameters recorded on it (example values).
Where this method and data come from (requirements, configuration, dimensions, modules, BOM) is in chapter 30 “Robot overall design” of *Robotics*; labs 30.1 and 30.2 can be tried in the browser first.

## Your pick

```quiz
q: For 1 WQ-CR5, MRP produces 13 work orders. Which does the shop release first?
options:
  - All 13 at once, the sooner the better | wrong | Joint module work orders would start before housings and hollow shafts are in stock, and could not draw material on completion
  - First the made parts — housings, hollow shafts, arm tubes, base; after they are in stock the joint modules; finally the robot | right | Bottom up through the BOM: only when a lower level is in stock can the level above draw material
  - First the robot, to keep the assembly station busy | wrong | The joint modules the robot needs do not exist yet
more: #Multi-level BOM
```

```quiz
q: How many large joint modules (WQJ-L) does a WQ-CR5 need?
options:
  - 1 | wrong | Count the WQJ-L row in the BOM
  - 2 | right | Large 2, medium 1, small 3 — six joints in all
  - 6 | wrong | The six joints come in three sizes: large, medium, small
more: #The BOM of one WQ-CR5
```

```ask
q: Why does one robot have so many more work orders than a gearbox?
```

:::查表

## The BOM of one WQ-CR5

| Level | Item | Qty per robot | Category |
|---|---|---|---|
| 1 | Joint module (large) WQJ-L | 2 | Subassembly |
| 1 | Joint module (medium) WQJ-M | 1 | Subassembly |
| 1 | Joint module (small) WQJ-S | 3 | Subassembly |
| 1 | Upper arm ARM-UP, forearm ARM-FO, base BASE-CR5 | 1 each | Made part |
| 1 | Robot control cabinet CTRL-CAB (part number to be confirmed), in-arm harness | 1 each | Purchased |
| 2 | Joint housing, hollow output shaft (1 each per joint module) | 1 | Made part |
| 2 | Harmonic drives CSF-32 / 25 / 17, servo motors 400 / 200 / 100 W (part number to be confirmed), encoders, driver boards, bearings | By size | Purchased |
| 3 | 6061 aluminum bar, plate, tube; 40Cr round bar | By weight | Raw material |

Items, BOMs and routings are all in the plant manifest (`factory/plants/wenquest-robot.yaml`); after import into ERPNext, ERPNext is the reference.

## Stock

Opening stock is roughly enough for 5 each of robots, AGVs and the three joints (example values). Purchase receipts belong to the supply chain domain, which in this phase exists only in the gearbox plant:
the robot plant's material requests are only records, and when stock runs out the teacher tops it up with a “Material Receipt” in ERPNext (the teaching plant allows negative stock, so nothing gets stuck).

## Viewing BOMs and routings on the page

[Design & process](/work/engineer) lists every item in this plant that has a BOM (sellable products first): pick one to see its BOM (click a made part to jump to its own BOM), its routing (minutes per piece, machines, pieces per load) and its standard cost. It is read-only; MRP uses exactly this data.
