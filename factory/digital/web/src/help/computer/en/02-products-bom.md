# Products and bills of materials

BOMs have **two levels**: first the subassemblies (mainboards, memory modules, chassis, notebook housings), then the systems; a rack uses 16 servers. A desktop order makes MRP schedule work orders for the board, modules and chassis as well.

| System | Made in-house | Main bought-in parts |
|---|---|---|
| Desktop WQ-PC1 | Desktop board MB-PC, DIMM-32 ×2, desktop chassis CHS-PC | Desktop CPU, 1 TB SSD, 500 W PSU, cooler, 2 fans, thermal paste |
| Industrial PC WQ-IPC | MB-PC, DIMM-32 ×1, CHS-PC | As the desktop, one fan |
| Notebook WQ-NB14 | Notebook board MB-NB (CPU and 8 DRAM packages on board), housing NBC-14 | 14-inch display, battery, keyboard, heat-pipe module, 65 W adapter |
| Server WQ-SV2U | Server board MB-SV, DIMM-32 ×16, 2U chassis CHS-SV | 2 server CPUs, 4 × 3.84 TB SSDs, 2 × 1600 W PSUs, 2 heatsinks, 6 fans |
| Rack WQ-RACK42 | WQ-SV2U ×16 | Top-of-rack switch, 2 PDUs, rear-door heat exchanger, 42U frame, 16 cable kits |

**Memory module DIMM-32**: 16 DDR5 packages of 16 Gb on a 10-layer board (16 × 16 Gb = 32 GB) plus the PMIC and SPD hub.

Bought-in parts use generic names with “model to be confirmed”; prices are example values.
