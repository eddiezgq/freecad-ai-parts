# Products and materials

## BOM (per motor, example)

| Part | Items | Notes |
|---|---|---|
| Stator | Electrical steel laminations (60 / 80 frame), magnet wire, insulation kit, insulating varnish | Laminations subcontracted; magnet wire and varnish issued by kg |
| Rotor | NdFeB magnet set (10 pieces, delivered unmagnetized), rotor core and shaft, magnet adhesive | Magnets are bonded in the plant, then magnetized |
| Final assembly | Bearings ×2, fail-safe brake (servo motors only), housing and end caps, power and brake cables, screws, box | |

Purchased items all use generic names + “part number to be confirmed”, and prices are example values. [Design & process](/work/engineer) shows the four BOMs and two routings.

## Routings

| Routing | Operations (minutes, example) |
|---|---|
| Servo motor | Incoming inspection 5 → core stacking 6 → winding 25 → insertion and forming 15 → varnish and bake 180 → stator test 8 → magnet bonding 20 → magnetizing 3 → balancing 8 → motor assembly 25 → brake test 6 → motor final test 12 → packing 4 |
| AGV motor | As above, with longer winding and insertion, and no brake test |

Varnish and bake is longest: 24 stators bake together in one load.

## Measurements

ERPNext has one inspection template per item, so all measurements of a motor are recorded on the “Motor final test” operation, with the machine that measured it named in the measurement name:

| Measurement | Where | Spec (example) |
|---|---|---|
| Three-phase resistance unbalance | Stator test bench | ≤ 1.5 % |
| Turn-to-turn surge waveform area difference | Stator test bench | ≤ 5 % |
| Hipot leakage current (1500 V, 1 s) | Stator test bench | ≤ 1.0 mA |
| Rotor residual unbalance | Balancing machine | ≤ 20 g·mm |
| Brake static holding torque | Brake test bench | Per model |
| Back-EMF constant, three-phase unbalance, harmonic distortion, cogging torque | Motor final test bench | See the next chapter |
| No-load current | Motor final test bench | Per model |

## Lab 42: one servo motor from order to delivery

On the left, Labs & tasks → Lab 42: take an order for 1 WQ-SM200 yourself, run MRP (single-level BOM, so one work order), read the routing and find the bottleneck — varnish and bake is the longest per piece, but 24 stators share one oven load, so the real limit is an operation that takes one motor at a time; judge whether the motor passes final test, receive and invoice, compare the order's standard and actual cost, and review. The platform grades 60 points automatically; the lab report is worth 40.
