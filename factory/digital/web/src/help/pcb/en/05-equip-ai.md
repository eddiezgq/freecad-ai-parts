# Equipment, energy, safety, people and AI patrol

> Maintenance, energy, business and finance, safety and environment, and people and shifts are all opened for this plant's 13 machines; AI patrol adds several electronics plant rules.

## Equipment categories

Each machine takes defaults by category (original value, PM tasks and intervals, failure modes, power, hazards, all example values):

| Category | PM | Typical failures | Hazards |
|---|---|---|---|
| Solder paste printer | Clean stencil and squeegee, calibrate vision alignment | Vision misalignment, wiper paper jam | Squeegee pinching hands, paste on skin |
| Placement machine | Clean and replace nozzles, calibrate nozzle centers, check feeders | Nozzle wear, feeder misfeeds | Fast-moving placement head |
| Reflow oven | Profile the oven, clean the flux recovery | Aging heaters, convection fan motor failure | Burns, flux fumes |
| Selective soldering | Remove dross, replace nozzles | Clogged nozzle, solder pump failure | 280 ℃ solder pot, flammable flux |
| Conformal coater | Clean the spray valve | Clogged spray valve | Solvent vapors |
| Functional test bench | Calibrate measurement channels with a reference source | Poor fixture contact, channel drift | 48 V live testing |

The reflow oven and burn-in room are automatic and can run without someone watching; the other machines “need someone”. The reflow oven draws the most power and is the most visible machine on the energy page.

```anim
name: energy-day
caption: A day's electricity: the reflow oven uses power whenever it is on, and standby is not low either
```

## AI patrol: the electronics plant's rules

Besides the rules every plant has (downtime, due dates, shortages, nonconforming parts…), this plant has five more:

| ID | Rule | What it looks at |
|---|---|---|
| QE1 | AOI defect rate sudden rise | Defect rate of the last 20 boards at least 3× the earlier rate |
| QE2 | Reflow temperature out of window | Peak temperature or time above liquidus outside the process window, or hugging its edge |
| QE3 | Paste volume low | Mean of the last 10 boards below 85 % |
| QE4 | Current sensing error high by lot | Driver board phase current sensing error high, stratified by shunt reel number |
| QE5 | Moisture-sensitive parts open too long without baking | Needs the component store to record opening time (next step) |

QE1–QE4 can all report the four problems the teacher injects.

## Hands on: inspect a machine

As “Maintenance technician”, do an inspection of a machine in “Maintenance” (e.g. the reflow oven: oven profile still valid, exhaust normal). Once done, this step ticks itself.

```goto
tour: maint-inspect
label: Help me inspect a machine
```

```live
kind: domain
domain: maint
```

## Your pick

```quiz
q: QE1 reports “AOI defect rate sudden rise”; chip component offset is normal and IC offset has grown. What do you check next?
options:
  - The stencil | wrong | Clogged stencil apertures show as falling paste volume and insufficient solder, not offset
  - The nozzles of multi-function placer PP-2 | right | ICs and MOSFETs are placed by PP-2 and chip components by PP-1; only what PP-2 placed is off
  - The reflow oven | wrong | For oven problems look at the oven log
more: #AI patrol: the electronics plant's rules
```

## Lab 37: tracing quality problems with 8D

This plant's hidden problems have a graded lab: on the left, Labs & tasks → Lab 37.

1. The instructor injects one problem on the lab page (it can be random; students can't see which).
2. Students find the characteristic and the rule that fired on the control charts on the Quality page.
3. On the lab page, compare means by shunt-resistor reel: if it is off only from one reel onward, it is the incoming lot, so write the reel number (e.g. SH-001); if every reel is off, it is one process step's machine, so write the machine ID (e.g. sp-1, pp-2, rf-1).
4. Open an 8D and choose an action; once the instructor approves, it goes to the shop. After another batch, it counts as effective only if every part is in tolerance and Cpk ≥ 1.33.
5. Write D7 and close.

The platform grades 60 points automatically; the lab report is worth 40. The guide and report template are at the top right of the lab page.

```ask
q: Which machine's PM is about to come due?
```
