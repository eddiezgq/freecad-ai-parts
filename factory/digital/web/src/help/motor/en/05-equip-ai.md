# Equipment, hidden problems and AI patrol

## Equipment

The 14 machines' PM, failure modes, power, hazards and inspection items are wired from the manifest into [Maintenance](/maint), [Energy & environment](/energy) and [Safety & environment](/ehs) (all example values).
The varnish oven does not need someone watching all the time; the other machines need someone while running. Hipot testing (high voltage), the magnetizer (strong magnetic field) and varnishing (volatiles) are this plant's main hazards.

## Hidden problems the teacher can inject

The scenario director can inject four problems (students cannot see what was injected and must trace it from the data):

| Problem | Symptoms | The right fix |
|---|---|---|
| Magnet bonding bench locating fixture worn | Cogging at 12 and 24 per revolution grows, harmonic distortion grows | Replace the locating fixture, recheck with a reference rotor |
| Magnetizer capacitors aged, magnetizing voltage low | Back-EMF constant drops motor by motor, no-load current rises | Repair the magnetizer, remagnetize rotors already done |
| Winder wd-2 tension unsteady | Only stators wound on wd-2 show three-phase resistance unbalance and larger turn-to-turn differences | Repair wd-2's tensioner, retest |
| Varnish oven temperature low | Hipot leakage current rises | Measure the oven temperature profile, replace heating elements, rebake at the normal temperature |

Several fixes look reasonable but miss the cause: loosening final test limits, compensating cogging torque in drive parameters, rebaking at the original temperature, training operators, replacing inspection gauges.

## AI patrol (Plant Insight Hub rules, only in the motor plant)

| ID | Rule | Hint |
|---|---|---|
| MT1 | Cogging torque growing | Look at harmonics: if 12 and 24 grow, check the magnet bonding fixture |
| MT2 | Three-phase resistance unbalance high (split by winder) | If only one winder is high, check its tensioner |
| MT3 | Back-EMF constant dropping | Check the magnetizing voltage |
| MT4 | Hipot leakage current rising | Check the varnish oven temperature |

## Lab 35: tracing quality problems with 8D

This plant's hidden problems have a graded lab: on the left, Labs & tasks → Lab 35.

1. The instructor injects one problem on the lab page (it can be random; students can't see which).
2. Students find the characteristic and the rule that fired on the control charts on the Quality page.
3. On the lab page, compare means by winding machine: is only one machine off, or is everything off together? Then name the machine (e.g. wd-2, vo-1, mg-1, mz-1).
4. Open an 8D and choose an action; once the instructor approves, it goes to the shop. After another batch, it counts as effective only if every part is in tolerance and Cpk ≥ 1.33.
5. Write D7 and close.

The platform grades 60 points automatically; the lab report is worth 40. The guide and report template are at the top right of the lab page.
