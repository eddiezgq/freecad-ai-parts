# Equipment, safety and AI patrol

> As in the other three plants, maintenance, energy, business and finance, safety and environment, people and shifts, and AI patrol are all opened from this manifest.

## Equipment

16 shop machines, each category with PM tasks, failure modes, power, hazards and inspection items (all example values):

| Category | Machines | Watch for |
|---|---|---|
| Prober and tester | prb-1 | Probe card touchdown count, standard wafer retest |
| Backgrinder, dicing saw | bg-1, dc-1 | Wheel / blade life; wet processing, grinding wastewater |
| Die attacher, wire bonders | da-1, wb-1, wb-2 | Silver epoxy warm-up; capillary life, first-piece pull and shear |
| Molding press, cure oven | mld-1, cur-1 | 175 ℃ high temperature; molding compound warm-up and open-time limit |
| Laser marker, plating line | lm-1, plt-1 | Class 4 laser eye protection; acid and tin-bearing wastewater |
| Test handler, burn-in room | ft-1, bi-1 | Socket contact, standard parts; burn-in temperature |

The cure oven, plasma cleaner and burn-in room do not need someone watching all the time; the other machines do.

## AI patrol: the chip plant's rules

| ID | Rule | What it looks at |
|---|---|---|
| QS1 | CP yield sudden drop | Last 4 wafers more than 2.5 percentage points below the previous 12 |
| QS2 | Failures concentrated on one site (critical) | Last 3 wafers, one site's failure rate at least 2.5× the median of the others |
| QS3 | Wire pull dropping (by bonder) | One bonder's mean below 4.5 gf, or the two differ by more than 1 gf |
| QS4 | Mold void rate rising | Mean of the last 5 lots above 2 % |
| QS5 | Dicing chipping growing | Mean of the last 5 lots above 17 µm |
| QS6 | Molding compound open too long | Needs the raw material store to record opening time (data pending) |

These rules appear only in the chip plant's rule catalog; other plants do not see them.

## Links

- [Wafer map](/wafer-map)
- [Chip design](/chip-design) (rounds 92, 93): this chip's Verilog, layout, transistor level
- [PCB design](/pcb-design): Rev B of the driver board puts this chip on the board; the firmware reads it in Renode and turns the motor (rounds 98, 100, 102)

## Lab 38: tracing quality problems with 8D

This plant's hidden problems have a graded lab: on the left, Labs & tasks → Lab 38.

1. The instructor injects one problem on the lab page (it can be random; students can't see which).
2. Students find the characteristic and the rule that fired on the control charts on the Quality page.
3. On the lab page, compare means by wire bonder: is only one bonder off, or are all lots off together? Then name the machine (e.g. prb-1, dc-1, wb-2, mld-1).
4. Open an 8D and choose an action; once the instructor approves, it goes to the shop. After another batch, it counts as effective only if every part is in tolerance and Cpk ≥ 1.33.
5. Write D7 and close.

The platform grades 60 points automatically; the lab report is worth 40. The guide and report template are at the top right of the lab page.

```ask
q: What AI patrol alarms does the chip plant have now? Which comes first?
```
