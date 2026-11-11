# SMT shop and inspection

> Each SMT board records its solder paste inspection, oven log and optical inspection results at the AOI station; each finished board records in-circuit and functional test results at the functional test station. The data goes into control charts.

## What each board records

| Item | Recorded at | Characteristics (nominal values and ranges are examples) |
|---|---|---|
| SMT boards SMT-DRV / SMT-AGV / SMT-ENC | Automated optical inspection AOI | Paste volume % (100, 70–130), paste height μm, reflow peak temperature ℃ (245, 235–255), time above liquidus s, chip component offset μm, IC and MOSFET offset μm, AOI defect count (attribute, pass only at 0) |
| Driver board DRV-JOINT | Functional test FCT | Shunt resistance mΩ (ICT, 2.00 ± 0.02), bus voltage reading error %, phase current sensing error %, gate dead time ns, encoder interface reading error, current zero drift after burn-in |
| AGV control board CTRL-AGV | Functional test FCT | Bus voltage reading error, 5 V and 3.3 V supplies, safety IO response time |
| Read-head board ENC-RD | Functional test FCT | Sine/cosine amplitude, DC offset, A/B phase difference, interpolation error |

An item has only one inspection template in ERPNext, so SPI, oven and AOI results are traced per board and recorded together at AOI.
At in-circuit test the driver board also identifies **which reel of shunt resistors** it used, so the quality page can stratify by reel number.

## Control charts

On the “Quality” page choose a characteristic to see its X̄–R chart; the AOI defect count is an attribute, so it has no X̄–R chart and only nonconformities are counted.

```anim
name: spc
caption: Alarm first, then out of tolerance: paste volume keeps falling — check the stencil before it leaves the limits
```

## Four problems the teacher can inject

| Problem | How it shows in the data | The right fix |
|---|---|---|
| Clogged stencil apertures | Paste volume falls board by board, AOI insufficient-solder defects increase | Clean the stencil, wipe more often |
| Reflow temperature drift | Peak temperature and time above liquidus gradually fall out of the process window (cold joint risk) | Profile the oven, correct the zones |
| Nozzle wear on multi-function placer PP-2 | Only IC and MOSFET offset grows; chip components are normal | Replace nozzles, calibrate nozzle centers |
| Incoming shunt resistor lot out of tolerance | From one reel on, ICT resistance and phase current sensing error are high; bus voltage is normal | Quarantine the reel, return it to the supplier |

Students work an 8D on a quality issue: only the right fix makes the problem go away and the data of later boards recover.

## Hands on: open a quality issue for paste volume

On the “Quality” page choose “SMT-DRV · Paste volume”, look at the control chart, and open an 8D for it. Once opened, this step ticks itself (use the “Inspector” role).

```goto
tour: quality-chart
label: Show me the control chart and open a quality issue
```

```live
kind: kpi
```

## Your pick

```quiz
q: The driver board's phase current sensing error is high while the bus voltage reading is normal. What is the most likely cause?
options:
  - Reflow temperature drift | wrong | An oven problem would show first in the oven log and AOI, not only in current sensing
  - Shunt resistance too high (incoming lot) | right | Current = voltage across the shunt ÷ resistance; a high resistance reads high current. Stratify by reel and the ICT resistance is high too
  - The functional test bench is broken | wrong | A broken bench would affect the bus voltage reading too
more: #Four problems the teacher can inject
```

```ask
q: Have recent SMT boards had many AOI defects? What kind?
```
