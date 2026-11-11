# Equipment and AI patrol

## Equipment categories

Every machine has its own category (PM tasks, failure modes, power, hazards, inspection items, all example values), for example:

- **Foundry**: medium-frequency induction furnace (molten iron splash, furnace breakout), molding line (crushing at mold closing), shakeout and core knockout machines (noise, dust with free silica), aging furnace (thermocouple calibration);
- **Machining**: machining centers, drill-tap centers, washer (fixed nozzles, filters), leak test bench (calibrated reference leak), topcoat booth (paint mist, explosion protection);
- **Parts**: carburizing and hardening line, induction hardening machine (coil), straightening press, various grinders, hook point lapping machine;
- **Assembly**: assembly stations, adjustment stations, sewing machine run-in stands, factory test benches.

Heat treatment furnaces, baking ovens, cooling lines and run-in stands do not need someone watching all the time.

## AI patrol rules

| Rule | What it looks at | Points to |
|---|---|---|
| SW1 Sand moisture high | Mean sand moisture at pouring of the last 6 castings > 3.7 % | Sand mixer mix-1 |
| SW2 Casting hardness high | Mean hardness of the last 6 castings > 230 HB | Automatic pouring machine pour-1 (inoculation) |
| SW3 Needle bar bore position large | Last 10 lockstitch housings split by finish-boring HMC: one machine's mean > 0.022 mm, or more than 0.008 mm above the others | That HMC |
| SW4 Housing flatness worsening | Mean base flatness of the last 6 lockstitch housings > 0.016 mm | Aging furnace age-1 |
| SW5 Journal hardness low | Mean journal hardness of the last 6 shafts < 51 HRC | Induction hardening machine ihd-1 |

## Practice: five hidden problems

Inject under “Problems & fixes”:
- High sand moisture;
- Inoculation fading;
- Worn locating pin on HMC no. 3;
- Aging furnace thermocouple drift;
- Aged induction hardening coil.

Take a few orders and watch how measurement records, control charts and AI patrol find them.

Each problem has a fix that addresses the cause, plus a few that sound reasonable but do not:
- Loosening inspection tolerances;
- Switching the CMM to 100 % inspection;
- Reboring out-of-tolerance housings.

Choose a fix that misses the cause and the problem stays.

## Lab 32: tracing quality problems with 8D

The practice above as a graded lab: on the left, Labs & tasks → Lab 32.

1. The instructor injects one problem on the lab page (it can be a random one of the five; students can't see which).
2. Students find the characteristic and the rule that fired on the control charts on the Quality page.
3. On the lab page, compare means by the machining centre that fine-bored each housing: is only one machine off, or is everything off together? Then name the machine (e.g. hmc-3, mix-1, pour-1, age-1, ihd-1).
4. Open an 8D and choose an action; once the instructor approves, it goes to the shop. After another batch, it counts as effective only if every part is in tolerance and Cpk ≥ 1.33. For casting porosity, open the 8D on the pore count.
5. Write D7 and close.

The platform grades 60 points automatically; the lab report is worth 40. The guide and report template are at the top right of the lab page.
