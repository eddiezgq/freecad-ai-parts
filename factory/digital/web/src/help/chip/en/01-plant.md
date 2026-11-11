# This plant: WenQuest Digital Industrial Park · Chip plant

> The park's fourth plant: an **assembly and test plant**. Wafers back from the foundry are tested, diced, packaged and tested again here, becoming reels of finished chips —
> the encoder interface chip WQ-ENCIF designed in rounds 92 and 93.

## Why an assembly and test plant

A real wafer fab (lithography, etching, ion implantation…) costs billions to build; only a handful exist worldwide. What schools and small companies actually do is:

1. **Design it themselves** — the [Chip design](/chip-design) page: Verilog, simulation, synthesis, layout, transistor level (rounds 92, 93);
2. **Have a foundry fabricate the wafers** — a multi-project wafer (several designs share one mask set to split the cost); this plant treats it as a subcontracted purchased item;
3. **Do assembly and test themselves** (or use an OSAT) — that is this plant.

## What it makes

| Product | ID | One unit | Example price |
|---|---|---|---|
| Encoder interface chip QFN-16 3×3 mm | WQ-ENCIF | One wafer lot: about 34,000 chips, 12 reels of tape (3,000 per reel) | $11,500 |
| Engineering samples (fully tested after burn-in, in trays, for customer evaluation) | WQ-ENCIF-ES | One wafer lot | $16,000 |

**One unit is “one wafer lot”**: assembly and test plants already move work by wafer lot, and CP yield and wafer maps are counted per wafer.
One 200 mm wafer has about 37,700 dies (die 0.80 × 0.80 mm: core from the round 92 layout, pad ring estimated as an example); CP yield about 92 %, FT about 98 %.
These, like prices, times and nominal values, are **example values**. The WQ-ENCIF chip has not really been taped out; it is an example chip.

## The shop

- **Wafer section (clean area)**: wafer incoming inspection → wafer test CP (prober + tester, 8 sites) → backgrinding; the output is a “tested wafer” with a wafer map;
- **Assembly section**: dicing → die attach → plasma clean → wire bonding (2 machines) → molding → post-mold cure → laser marking → plating → trim and form → final test FT → tape and reel;
  engineering samples get an extra burn-in step before FT.

Bonding is slowest: 17 wires per chip, over 600,000 per wafer — so there are two bonders, and each lot goes on one of them.

```anim
name: flow
caption: Order → MRP → ERPNext → wafer test → assembly → final test → stock and invoice, the same line as the other three plants
```

## Who buys

Besides example external customers, since round 106 the **PCB plant** buys WQ-ENCIF here for Rev B of the driver board: its purchase order (34,000 chips) arrives as an order for 1 lot of WQ-ENCIF;
this plant takes the order automatically, ships when done, and the other plant receives it into stock. The chip → board link is connected inside the park.

## From design to this plant's inspection standards

The final test Schmitt hysteresis and the wafer test upper and lower thresholds take their nominal values straight from the round 93 transistor-level simulation (VT+ 1.254 V, VT− 0.607 V, hysteresis 0.648 V);
the operating current comes from the round 92 layout's power (1.21 mW ÷ 1.8 V ≈ 0.67 mA). **The design's simulation results become the factory's inspection standards** — the scatter is an example value.

## Your pick

```quiz
q: Why does this plant not make its own wafers?
options:
  - A wafer fab costs too much; schools and small companies have foundries fabricate | right | Design + foundry + assembly/test is the most common split in the chip industry
  - Assembly is more advanced than wafer fabrication | wrong | Wafer fabrication (lithography, etching…) has the highest barrier
  - The SKY130 process cannot make wafers | wrong | SKY130 is an open-source process library; the foundry fabricates wafers with it
more: #Why an assembly and test plant
```
