# Torque sensor line

> A joint torque sensor is an elastic body: under torque it deforms slightly, and 4 strain gauges bonded on it form a full bridge that turns the deformation into a millivolt-level voltage.
> Cobots rely on it for collision detection and hand-guided teaching.

## Operations

| Operation | What it does | Key points |
|---|---|---|
| Strain gauge bonding | Grind and clean the body surface, align and bond 4 gauges under a microscope, clamp with pressure pads | Position and direction accurate; adhesive layer thin and even |
| Adhesive cure | The cure oven ramps and holds per the profile | **The temperature must be high enough**: under-cured adhesive slowly “creeps”, and the reading drifts over time |
| Bridge wiring | Connect the 4 gauges into a full bridge and solder to the cable | Recheck bridge resistance |
| Temperature compensation | Measure zero drift with temperature in the chamber, fit compensation resistors | — |
| Deadweight calibration | Lever with weights, 5 steps loading and 5 unloading | Compute sensitivity, nonlinearity, hysteresis |
| Final test | Recheck zero, hold full scale 30 min to see creep | Pass/fail against the spec |

## What final test records (all as % of full scale FS)

| Characteristic | Nominal | Upper limit (example) |
|---|---|---|
| Nonlinearity | 0.10 % | 0.30 % |
| Hysteresis (loading vs unloading difference) | 0.08 % | 0.25 % |
| Zero output | 0 | ±0.5 % |
| Creep (full scale held 30 min) | 0.03 % | 0.10 % |
| Zero temperature drift (per 10 K) | 0.05 % | 0.15 % |

## Creep, hysteresis and temperature drift all growing

When all three grow together, it is usually not bad gauges but **under-cured adhesive** — the layer is still soft and slowly deforms under load. Check the cure oven's temperature profile and calibrate the controller; post-cure the under-cured parts.
