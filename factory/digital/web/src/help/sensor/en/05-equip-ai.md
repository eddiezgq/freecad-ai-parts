# Equipment, hidden problems and AI patrol

## Equipment

The 15 machines' PM, failure modes, power, hazards and inspection items are wired from the manifest into [Maintenance](/maint), [Energy & environment](/energy) and [Safety & environment](/ehs) (all example values).
The temperature cycling chamber, temperature compensation chamber and cure oven do not need someone watching all the time; the other machines need someone while running.

## Hidden problems the teacher can inject

The scenario director can inject four problems (students cannot see what was injected and must trace it from the data):

| Problem | Symptoms | The right fix |
|---|---|---|
| Centering fixture on bonding machine cb-2 worn | Only encoders bonded on cb-2 show the first harmonic growing unit by unit | Replace cb-2's centering fixture, recheck with a reference disc |
| Read-head adjustment bench feeler gauge worn | Signal amplitude drops, interpolation error grows | Replace and calibrate the gauge, recheck units already assembled |
| Clean room filter clogged | Spots land on discs: amplitude dips somewhere, spikes on the curve | Replace the filter unit, measure particle counts, reclean the discs |
| Cure oven temperature low | Torque sensor creep, hysteresis and temperature drift grow | Measure the oven profile, calibrate the controller, post-cure |

Several fixes look reasonable but miss the cause: redoing the compensation table, raising read-head gain, tightening final test, training operators, replacing inspection gauges.

## AI patrol (Plant Insight Hub rules, only in the sensor plant)

| ID | Rule | Hint |
|---|---|---|
| SN1 | Encoder accuracy worsening | Open the error curve and look at its shape |
| SN2 | First harmonic high (split by bonding machine) | If only one machine is high, check its fixture |
| SN3 | Read-head signal amplitude dropping | Check the gap; do not just raise gain |
| SN4 | Disc spots (amplitude dips) | Check the clean room |
| SN5 | Torque sensor creep rising | Check the cure oven |

## Lab 36: tracing quality problems with 8D

This plant's hidden problems have a graded lab: on the left, Labs & tasks → Lab 36.

1. The instructor injects one problem on the lab page (it can be random; students can't see which).
2. Students find the characteristic and the rule that fired on the control charts on the Quality page.
3. On the lab page, compare means by disc bonding machine: is only one machine off, or is everything off together? Then name the machine (e.g. cb-2, hm-1, dcl-1, cur-1).
4. Open an 8D and choose an action; once the instructor approves, it goes to the shop. After another batch, it counts as effective only if every part is in tolerance and Cpk ≥ 1.33.
5. Write D7 and close.

The platform grades 60 points automatically; the lab report is worth 40. The guide and report template are at the top right of the lab page.
