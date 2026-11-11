# Products, materials and routings

## Two machines

| Product | ID | Example price | Made parts |
|---|---|---|---|
| Industrial direct-drive lockstitch machine | WQ-LS | $520 | Lockstitch housing HSG-LS, upper shaft LS-101, lower shaft LS-102, needle bar LS-201, rotary hook LS-301, feed / lift eccentrics LS-401 ×2 |
| Industrial direct-drive four-thread overlock machine | WQ-OL | $640 | Overlock housing HSG-OL, main shaft OL-101, needle bar OL-201, looper / differential eccentrics OL-401 ×3 |

Housings use castings poured in-house: lockstitch housing casting CAST-LS (HT250, about 14 kg) and overlock housing casting CAST-OL (about 6 kg, two per mold).

Purchased items use generic names + “part number to be confirmed”: direct-drive servo motor and control box, needles, loopers, bobbin cases, feed dog / needle plate / presser foot, bearings, timing belts, covers, oil pans, standard parts, packing.
The control box is flashed with the plant's firmware at factory test.

## How many work orders one order creates

Take 1 WQ-LS and MRP creates 8 work orders: casting → housing, upper shaft, lower shaft, needle bar, rotary hook, eccentrics, and finally the machine.
Each work order is dispatched to the shop operation by operation along its own routing; a lower level must be finished and in stock before the next level can draw material.

## Routings (times are example values)

| Routing | Operations |
|---|---|
| Casting | Charge make-up → melting → ladle analysis → sand mixing → sand testing → core making → core inspection → molding, core setting, closing → inoculation and pouring → cooling 60 min → shakeout → used sand reclamation → gate and riser removal → shot blasting → internal core sand removal → grinding → first aging 480 min → filler → primer → physical and chemical testing → casting inspection |
| Lockstitch housing | Blank inspection → rough-mill base (VMC) → roughing, rough boring (HMC) → second aging → finish-mill base, ream pin holes, mark serial number (VMC) → drilling and tapping, oil holes (drill-tap center) → finish-bore bore system (HMC, one setup) → deburring → wash and blow dry → CMM → housing final inspection → topcoat → baking |
| Overlock housing | As above, plus a leak test (oil sump) |
| Shafts | Cutting → rough turning → quench and temper → straightening → finish turning → mill flats and drill → induction harden journals → straightening → cylindrical grinding → washing → part inspection |
| Needle bar | Cutting → centerless rough grinding → turn and drill the needle clamp hole → harden and temper → straightening → centerless finish grinding → washing → inspection |
| Rotary hook | Turning → mill hook point and race → carburize and harden → grind the race → lap the hook point → washing → inspection |
| Eccentrics | Cutting → turning → keyway milling → carburize and harden → grind bore and faces → grind eccentric diameter → eccentric measurement → washing → inspection |
| Lockstitch final assembly | 4 subassemblies → A01–A12 final assembly line → adjustment → run-in 30 min → factory test → clean and pack |
| Overlock final assembly | 2 subassemblies → B01–B06 final assembly line → adjustment → run-in → factory test → packing |

ERPNext has one inspection template per item, so all of an item's measurements are recorded on its last inspection operation, with the measuring machine named in the measurement name.

## Lab 34: one lockstitch machine from order to delivery

On the left, Labs & tasks → Lab 34: take an order for 1 WQ-LS, run MRP, release by level (casting and key parts → housing → machine), judge one machine's final test, receive it and invoice, compare the machine's standard and actual cost, then review. The platform grades 60 points automatically; the lab report is worth 40.
