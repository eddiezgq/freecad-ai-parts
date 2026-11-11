# This plant: WenQuest Sewing Machine Plant

> A complete sewing machine plant with machines laid out per real processes: everything from molten iron to finished machines is made in the plant.
> The products are the industrial direct-drive lockstitch machine WQ-LS and the four-thread overlock machine WQ-OL.
> Processes follow the “Sewing machine plant process plan” (round 134) and chapters 23–25 and 27 of *Sewing Machine Design and Manufacturing*; all values are examples.

## Five shops

```
① Housing foundry → ② Housing machining ──┐
                    ③ Key parts ──────────┼→ ④ Lockstitch assembly → Finished goods
                                          └→ ⑤ Overlock assembly → Finished goods
Metrology lab (CMM, cam measuring machine, roundness tester, roughness tester, cleanliness analysis)
```

| Shop | What it does | Main equipment (count) |
|---|---|---|
| ① Housing foundry | Melting, core making, molding, pouring, cooling, shakeout, cleaning, first aging, filler and primer, casting inspection | Medium-frequency furnaces ×2, core shooters ×3, molding line, automatic pouring machine, shot blaster, aging furnace |
| ② Housing machining | Lockstitch housing line, overlock housing line: datum faces, roughing, second aging, drilling and tapping, finish boring of bore systems, washing, final inspection, topcoat | Vertical machining centers ×4, horizontal machining centers ×7, drill-tap centers ×4, washer, leak test bench, topcoat booth and oven |
| ③ Key parts | Upper shaft, lower shaft, overlock main shaft, needle bar, rotary hook, eccentrics | CNC lathes ×10, cylindrical grinders ×4, centerless grinder, cam grinders ×2, hook race grinders ×2, carburizing line, induction hardening machine |
| ④ Lockstitch assembly | Subassembly → 12-station final assembly line (takt 2.4 min) → adjustment → run-in → factory test → packing | Adjustment stations ×5, run-in stands ×15, factory test benches ×3 |
| ⑤ Overlock assembly | Subassembly → 6-station final assembly line (takt 7.2 min) → adjustment → run-in → factory test → packing | Adjustment stations ×3, run-in stands ×6, factory test bench |

About 150 machines / stations in all, laid out by shop in the 3D shop.

## Where the bottleneck is

The 5 horizontal machining centers that finish-bore lockstitch housings: each housing takes 16 min (6 min roughing + 10 min finish boring); 180 housings a day is exactly 100 % load, as in the worked example in section 27.4 of the textbook.
When a horizontal machining center stops on the board, that day's housings fall short. Raising their OEE from 60 % to 68 % brings the load down to only 88 %.
