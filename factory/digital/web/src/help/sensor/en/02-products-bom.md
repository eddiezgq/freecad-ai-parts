# Products and materials

> Purchased items always use generic names + “part number to be confirmed”; prices, lead times and times are example values.

## BOM of encoder WQ-ENC17

| Item | ID | Qty | Source |
|---|---|---|---|
| Optical code disc Ø32 mm (glass, absolute track + incremental track) | DISK-17 | 1 | Subcontracted disc maker |
| Disc hub, housing and cover | HUB-ENC, HSG-ENC | 1 each | Subcontracted precision machining |
| Encoder bearings | BRG-ENC | 2 | Standard parts supplier |
| Disc bonding adhesive (UV-cured) | GLUE-UV | Small amount | Strain gauge and adhesive supplier |
| **Encoder read-head board (sine/cosine output)** | **ENC-RD** | 1 | **The park's PCB plant** |
| Cable, screws, ESD packing box | CABLE-ENC, SCR-M3, BOX-S | — | Example suppliers |

## BOM of torque sensor WQ-TS

| Item | ID | Qty |
|---|---|---|
| Elastic body (17-4PH stainless steel, subcontracted machining) | BODY-TS | 1 |
| Strain gauge 350 Ω (shear type, dual grid) | SG-350 | 4 (forming a full bridge) |
| Strain gauge adhesive (heat-cured epoxy) | GLUE-SG | Small amount |
| Compensation resistor kit, signal conditioning board, cable | RES-COMP, SIG-TS, CABLE-TS | 1 each |

## From order to invoice

As in the other plants: take a WQ-ENC17 or WQ-TS order in [Orders & planning](/work/planner) → MRP (shortages requested automatically; read-head boards ordered from the PCB plant) → work orders into ERPNext →
the shop works operation by operation → final test records measurements → into stock → ship and invoice.

## Selling to the robot plant

Each of the robot plant's joint modules WQJ-L / M / S uses one encoder. The robot plant sets the encoder's safety stock equal to its opening stock, replenishing one for each one used,
so as soon as it starts work this plant receives purchase orders — visible among park orders in [Orders & planning](/work/planner).

## Lab 43: one torque sensor from order to delivery

On the left, Labs & tasks → Lab 43: take an order for 1 WQ-TS yourself, run MRP (single-level BOM, so one work order), read the routing and find the bottleneck — temperature compensation is the longest per piece, but 10 sensors share one chamber load, so the real limits are the one-at-a-time operations, gauge bonding and dead-weight calibration; judge whether the sensor passes final test, receive and invoice, compare the order's standard and actual cost, and review. The platform grades 60 points automatically; the lab report is worth 40.
