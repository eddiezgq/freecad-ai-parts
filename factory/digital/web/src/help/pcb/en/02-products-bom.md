# Products and BOM

> Each finished board has two levels: the SMT line makes an “SMT board”, and the back end adds terminals, tests and burns it in to make the finished board.

## Two-level BOM

| Level | Item | What is in it |
|---|---|---|
| Finished board | DRV-JOINT | SMT board SMT-DRV × 1, power terminals × 2, signal connectors × 3, conformal coating, ESD bag |
| SMT board | SMT-DRV | Bare board × 1, motor control MCU, half-bridge gate drivers × 3, CAN transceiver, RS-485 transceivers × 2, buck regulator, linear regulators × 2, current sense amplifiers × 3, MOSFETs × 6, **shunt resistors × 3**, 0402 resistors 18 / capacitors 30, 1206 capacitors 7, bus electrolytic capacitor, diodes × 4, power inductor, crystal, solder paste |

Driver board quantities follow its KiCad design (the BOM on the “PCB design” page); the chips are example selections, not hardware-verified. The last column of the BOM table on the “PCB design” page is “Look up outside”: chips by part number, resistors, capacitors and inductors by package size + value, with ready-made search links to LCSC, DigiKey and SnapMagic for stock and prices (links only, not used in any check). The AGV control board and read-head board likewise have two levels. Take a driver board order and MRP schedules the SMT board work order first, then the finished board work order.

```anim
name: bom-tree
caption: One driver board explodes into two levels: SMT board → components
```

## Hands on: take a driver board order and run MRP

As “Planner”, take a DRV-JOINT order in “Orders & planning” and look at MRP: SMT board work order, finished board work order, requests for missing components. Once MRP is done, this step ticks itself.

```goto
tour: planner-order
label: Help me take an order and run MRP
```

```live
kind: kpi
```

## Your pick

```quiz
q: Why is the driver board split into “SMT board” and “finished board” levels?
options:
  - To make the BOM look nice | wrong | The levels exist because production really has two stages
  - The SMT line and the back end are two production stages with inspection and possibly queuing in between; the SMT board is an intermediate item that can be counted and traced | right | The two work orders each start and finish into stock, and quality data is recorded in two places
  - ERPNext does not support single-level BOMs | wrong | It does; it just does not fit how this plant produces
more: #Two-level BOM
```

## Lab 39: one drive board from order to delivery

On the left, Labs & tasks → Lab 39: take an order for 1 DRV-JOINT yourself, run MRP, release by level (SMT assembly → drive board), judge whether one board passes functional test, receive and invoice, compare the order's standard and actual cost, and review. The platform grades 60 points automatically; the lab report is worth 40.

```ask
q: Which components need to be requested for 20 driver boards?
```

## Viewing BOMs and routings on the page

[Design & process](/work/engineer) lists every item in this plant that has a BOM (sellable products first): pick one to see its BOM (click a made part to jump to its own BOM), its routing (minutes per piece, machines, pieces per load) and its standard cost. It is read-only; MRP uses exactly this data.
