# Equipment, energy, finance, safety and people

> The robot plant also has “Maintenance”, “Energy & environment”, “Business & finance” (round 59) and “Safety & environment”, “People & shifts” (round 61): the register is the robot plant's own 15 machines, energy is recorded by their power, finance uses the robot plant's customers and products, and hazards and staff are generated from the shop's machines.

## What the three pages have

- **Maintenance**: each machine's asset number (written into ERPNext), PM plan, run hours since last PM, probability of failure in the next two weeks and expected loss; inspections, PM and repairs all open lockout permits.
- **Energy & environment**: one meter per machine, one reading every 15 minutes (plant time); time-of-use tariffs, demand, carbon, energy per part, idle energy; oil mist in the machining area, shop noise.
- **Business & finance**: invoices when orders are done, customer payments (the teaching simulator pays late by habit), receivables aging, credit limits, cash flow, each order's margin, monthly budget.

They work as in the gearbox plant; see the maintenance, energy and business and finance chapters of the “Teaching edition” volume.

When these domains have problems (PM overdue, inspection anomaly, energy per part spike, receivable overdue, over budget, hazard overdue, staffing gap, single point of dependency, incoming nonconformance…), AI patrol raises alarms in the “Plant Insight Hub” with options; you can also ask the AI assistant directly, e.g. “Which machine's PM is overdue?”, “Which customer's receivable is overdue?” (round 67).

```live
kind: domain
domain: maint
```

```live
kind: domain
domain: energy
```

## How long can a machine hold out

Whether a machine fails follows a Weibull distribution; drag the run hours and watch the probability of failure rise (the preset here is the gearbox plant's grinder; the robot plant's grinder GRD-R1 uses the same example parameters):

```lab
id: weibull
preset: grd
height: 600
```

## Hands on: inspect a machine

In “Maintenance → Inspections” choose a machine (e.g. calibration station CAL-1), tick each item and submit. Submit once and this step ticks itself.

```goto
tour: maint-inspect
label: Help me inspect a machine
```

## Where the numbers come from

The robot plant's machines take defaults by **category**, all **example values** that do not correspond to any real machine:

| Category | Machines | Original value ($) | PM interval (run hours) | Running / idle / standby (kW) |
|---|---|---|---|---|
| Saw | SAW-R1 | 18,000 | 800 | 7.5 / 2 / 0.3 |
| CNC lathe | CNC-R1, CNC-R2 | 65,000 | 600 | 15 / 5 / 0.6 |
| Machining center | VMC-R1, VMC-R2 | 110,000 | 600 | 15 / 5 / 0.6 |
| Grinder | GRD-R1 | 120,000 | 500 | 11 / 4 / 0.5 |
| Measuring equipment | CMM-R1 | 90,000 | 1000 | 2 / 1 / 0.2 |
| Assembly station | JA-1, JA-2, RA-1, AA-1 | 25,000 | 1000 | 3 / 1 / 0.2 |
| Test bench | JT-1 | 60,000 | 1000 | 8 / 1.5 / 0.3 |
| Calibration station | CAL-1 | 150,000 | 1000 | 2.5 / 1 / 0.2 |
| Run-in stand | RUN-R1 | 50,000 | 1000 | 12 / 1.5 / 0.3 |
| Commissioning area | AT-1 | 20,000 | 1000 | 4 / 0.8 / 0.2 |

If the plant manifest gives a machine `maint` (original value, purchase year, PM tasks and duration, repair cost, downtime loss, Weibull parameters) or `power_kw` (running, idle, standby), the manifest is used.
Customer credit limits default to 4, 3 and 2.5 × the price of the main product WQ-CR5, and the monthly budget is 3 × the gearbox plant's; both can be changed in the manifest's `finance` section.

The teaching simulator's problems use the general kinds first: random Weibull failures, machines left on after hours, machine degradation, compressed air leaks, oil mist collector failure.
Problems specific to the gearbox plant (heat treatment furnace on at peak, etc.) do not occur in the robot plant. Customers and service (robots in the field) are done separately later.

```goto
tour: maint-tour
label: Show me the equipment register
```

```quiz
q: The robot plant's calibration station CAL-1 has a 3 % probability of failing in the next two weeks; one repair costs $900, with 3 hours down at $100 lost per hour. About how much is the expected loss?
options:
  - About $36 | right | 0.03 × (900 + 3 × 100) = $36
  - About $1200 | wrong | That is the loss if it fails; the expected loss multiplies by the probability of failure
  - About $27 | wrong | That counts only the repair cost; downtime loss counts too
more: #Where the numbers come from
```

## Safety and environment

Hazards are attached to the robot plant's machines by category (examples): grinder “wheel bursting and flying out”, “grinding dust”; lathe “caught in the chuck”; assembly “crushing during press-fit”;
joint test bench “joint turning unexpectedly (powered commissioning)”; calibration station “robot moving unexpectedly (powered calibration)”, “laser in the eyes (class 2 laser tracker)”;
load run-in stand “robot moving under load hits a person”; AGV commissioning area “AGV collision”. Chemicals are cutting fluid, way lubricant and harmonic drive grease; hazardous waste is registered as usual and disposed of within 90 days.
Lockout permits opened for PM and repairs check the qualifications of the robot plant's maintenance technicians.

```live
kind: domain
domain: ehs
```

## People and shifts

The robot plant has 23 people (all fictional): three crews — machining, assembly, and test and calibration — each with a crew lead; one main operator (skilled) for each machine that needs someone;
one apprentice each in machining and assembly; 2 maintenance technicians in the equipment group, 1 safety officer in EHS, and 1 each of planner and storekeeper. **Day shift only** (8–17).
The joint test bench and load run-in stand are automatic and run without someone watching.

Teaching point: **only one person can run robot calibration station CAL-1** (the main operator, skilled). The day he is on leave robot calibration stops — in “People & shifts → Skill matrix” it is marked “single point”,
and the fix is to have someone apprentice with him (about 40 hours).

```live
kind: domain
domain: people
```

```quiz
q: In the robot plant's skill matrix, only one person is “skilled” on robot calibration station CAL-1. What should be done first?
options:
  - Have someone apprentice with him and learn calibration | right | Remove the single point of dependency: someone else can run it when he is on leave
  - Give him more overtime | wrong | Overtime does not solve “nobody can do it when he is away”
  - Nothing; the calibration station is automatic | wrong | Calibration needs a person to run the tracker and judge results; the automatic ones are the joint test bench and load run-in stand
more: #People and shifts
```
