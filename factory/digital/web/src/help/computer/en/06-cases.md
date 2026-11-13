# Design cases: CPU power, server cooling, computing center

> Left menu “Design cases”: three cases of the computer plant, from the design brief to the shop floor. Case A's board goes into the desktop, case B's server into case C's rack. All numbers come from the scripts; these are example designs, not built and tested.

| Case | What | Worth a look |
|---|---|---|
| A CPU core power on the desktop board | 12 V to about 1.1 V at up to 140 A: 6-phase buck, load line, output capacitors, tolerance stack | ngspice switching simulation matches the formulas (ripple, conduction loss); the capacitor sweep shows the voltage leaving the load line with fewer than 5; **the voltage spread from the tolerance stack is used by the plant**, so the power-on test yield is set by the design |
| B CPU cooling in the 2U server | Two 270 W CPUs, 35 °C inlet, below 85 °C even with one fan failed | More fins is not always better (fans and duct set the airflow together); FEA of the copper base matches the spreading formula within 0.1 °C; the design resistance goes into the same model as [System burn-in curves](/burn-in) |
| C A 20-rack computing center | 20 racks: power, cooling, layout, annual PUE, availability | 8760-hour simulation: rear-door heat exchangers + warm water + free cooling give PUE about 1.17, room DX units about 1.38; N+1 availability by formula and Monte Carlo agree; the rack test bench is the delivery bottleneck |

Each case has eight steps: brief, concept, calculation, simulation, 3D & drawings, process, manufacturing, review; every step has buttons to open the software (circuit analysis, simulation, burn-in curves, energy…) to redo the numbers yourself.

## Links to the plant

- After case A the spread of the board's core-voltage deviation is 2.2 mV, from the design (was 3 mV by experience).
- Case B's heatsink resistance is within 4 % of the server value in the burn-in model (the model is slightly conservative).
- Case C step 7 tests 20 racks on the rack bench: rack power, heat-exchanger temperature difference, link errors.

```quiz
q: Why does case B not use the fin count with the lowest thermal resistance?
options:
  - That one does not fit | wrong | Every fin count has the same outline
  - The fewest fins that still work with one fan failed: wider gaps, less dust, lower cost | right | Meeting the requirement is enough; extra fins only add pressure drop, dust and cost
  - Fewer fins always give lower resistance | wrong | Too few fins lack area and the resistance rises
```
