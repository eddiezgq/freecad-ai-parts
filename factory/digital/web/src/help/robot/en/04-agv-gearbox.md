# The AGV uses the gearbox plant's gearbox

> Each drive unit of the handling AGV contains a WQR-105 — the one made by the WenQuest gearbox plant. The two plants form upstream and downstream: the purchase order goes over, and that plant ships back when done.

## How an AGV is built

WQ-AGV300 is assembled from a frame, two drive units, four casters, a battery, a lidar and an AGV controller. The drive unit (DU-AGV) is a subassembly the robot plant builds itself:
one WQR-105 gearbox + one AGV drive motor + one polyurethane drive wheel.

```anim
name: mrp
caption: At the drive unit level: WQR-105 requests are computed as “gross requirement − stock − on order + safety stock”
```

## How the two plants connect

The robot plant's suppliers include “WenQuest gearbox plant”, and WQR-105 is a purchased item from it. WQR-105's safety stock is set at its opening stock (example: 10 units),
so every AGV order makes MRP request replenishment from the gearbox plant:

1. The robot plant takes 1 WQ-AGV300 → MRP: 2 WQR-105 needed;
2. Stock 10, safety stock 10 → using 2 drops below safety stock → net requirement 2, rounded up to the purchase lot of 10 → request 10, supplier: WenQuest gearbox plant;
3. After confirmation, the material request is written into the robot plant's ERPNext.

4. Once the request becomes a purchase order, the platform **sends it to the WenQuest gearbox plant**, where it becomes a sales order; the gearbox plant ships when done, and the WQR-105 is inspected on arrival and stocked
   (see chapter 7 “Purchase receipts and supply from the gearbox plant”).

```video
name: robot-order
caption: Take the order and run MRP: is WQR-105 in the material request?
```

## Hands on: take an AGV order and look for WQR-105 in the requests

In “Orders & planning” choose WQ-AGV300, quantity 1, and click “Run MRP”. When the result appears, this step ticks itself; find WQR-105 among the request rows, with its quantity and supplier.

```goto
tour: planner-order
label: Take me to take an order and run MRP
```

```live
kind: kpi
```

## Your pick

```quiz
q: The robot plant takes 1 AGV; WQR-105 stock 10, safety stock 10, nothing on order, purchase lot 10. How many does MRP request?
options:
  - 0: stock of 10 is enough | wrong | After using 2 only 8 remain, below safety stock
  - 10 | right | Net requirement = 2 (gross) + 10 (safety stock) − 10 (stock) − 0 (on order) = 2, rounded up to the lot of 10
  - 12 | wrong | Gross requirement and safety stock are not simply added: subtract stock, then round up to the lot
more: #How the two plants connect
```

```quiz
q: The robot plant confirmed the WQR-105 request. What happens at the gearbox plant now?
options:
  - Nothing: a request is just a piece of paper | wrong | Once it becomes a purchase order it is sent to the gearbox plant
  - Once it becomes a purchase order it is sent to the gearbox plant, becomes a sales order there, and is shipped back when done | right | The buyer's purchase order is the seller's sales order (park phase two, round 51)
  - The gearbox plant's stock drops by 10 directly | wrong | The two plants keep separate stock
more: #How the two plants connect
```

```ask
q: If the gearbox plant's WQR-105 delivery slips a week, what happens to the robot plant's AGV orders?
```

:::查表

## The AGV's BOM

| Item | Qty per AGV | Category | Supplier |
|---|---|---|---|
| AGV frame FRAME-AGV300 | 1 | Purchased | Example |
| Drive unit DU-AGV | 2 | Subassembly (built in-house) | — |
| &ensp;└ WQR-105 gearbox | 1 / unit | Purchased | WenQuest gearbox plant |
| &ensp;└ AGV drive motor, polyurethane drive wheel | 1 each / unit | Purchased | Example |
| Casters | 4 | Purchased | Example |
| 48 V battery, lidar TiM781, AGV control board | 1 each | Purchased (control board from the WenQuest PCB plant) | Example |

## The AGV's routing

Drive unit: AGV assembly. Vehicle: AGV assembly → AGV commissioning (measure docking position error) → packing.
