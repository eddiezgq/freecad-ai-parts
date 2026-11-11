# Products and BOM

> Two levels: the wafer first becomes a “tested wafer” (CP, backgrinding), then is assembled and tested into a finished lot.

## BOM (one wafer lot)

| Level | Item | Quantity (example) | Notes |
|---|---|---|---|
| Tested wafer WAF-ENCIF-CP | Fabricated wafer WAF-ENCIF | 1 wafer | Subcontracted to a foundry, lead time 60 days |
| Finished WQ-ENCIF | Tested wafer | 1 wafer | |
| | Dicing tape and wafer frame | 1 | |
| | QFN-16 lead frame strips | 144 strips | 256 sites each, enough for about 37,000 |
| | Gold bonding wire 25 µm | 630 m | About 17 wires and 17 mm per chip |
| | Conductive silver epoxy | 0.002 kg | Die attach adhesive, refrigerated |
| | Epoxy molding compound | 1.5 kg | Including runner losses; **moisture-sensitive**, use within a time limit after opening |
| | Tape and reel materials / moisture-barrier packing | 12 reels each | |
| Engineering samples WQ-ENCIF-ES | As above, but with trays and 4 sets of moisture-barrier packing | | |

Purchased items use generic names marked “part number to be confirmed”, with no made-up vendor part numbers; prices, lead times and quantities are example values.

## Suppliers

Wafer foundry, lead frame maker, bonding wire maker, molding compound and silver epoxy maker, tape and moisture-barrier packing maker — five companies, all examples.
Incoming inspection: wafers — check wafer IDs and appearance; bonding wire — measure the diameter (24.5–25.9 µm); molding compound — check shelf life and arrival temperature (≤ 5 ℃).

## Hands on: look at a tested-wafer work order

Take a WQ-ENCIF order in “Orders & planning”; after MRP the “tested wafer” work order is released first, and the finished-goods work order after it is done.

```ask
q: How much material does one WQ-ENCIF lot use? How many lots can stock cover?
```
