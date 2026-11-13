# Equipment, hidden problems and AI patrol

## Equipment

Maintenance, failure modes, power, hazards and checklists of the 29 machines feed [Maintenance](/maint), [Energy](/energy) and [EHS](/ehs) (all example values).
The reflow oven, burn-in room, memory tester and rack bench run unattended; the rest need someone present. Main hazards: X-ray (radiation), laser cutting (laser and fumes), powder coating (dust explosion), anodizing (acids and alkalis), racks (tipping and high-current power).

## Hidden problems the teacher can inject

Four problems can be injected in the Scenario director (students cannot see which; they trace it from the data):

| Problem | Symptom | Real fix |
|---|---|---|
| Dispenser dp-2 needle half blocked, too little paste | Only systems pasted by dp-2 run hot under full load | Clean the needle, check the dose by weighing, re-apply and retest |
| Reflow zone 7 too cool | Board BGA voids rise, memory timing margin drops with them | Replace the zone heater, profile the oven |
| Press-brake back gauge shifted | Chassis holes all off the same way, bend angles follow | Recalibrate the back gauge with a reference block, check the first piece |
| Poor contact in memory-tester socket 6 | Only modules tested in socket 6 read low (false rejects) | Replace the socket, verify with a golden module, retest rejects |

Plausible-looking but wrong measures: longer burn-in, a faster fan curve, relaxing system test limits, retraining operators, changing gauges.

## AI patrol (command-center rules, computer plant only)

| No. | Rule | Hint |
|---|---|---|
| CP1 | CPU full-load temperature high (by dispenser) | If only one has little margin, check its dose |
| CP2 | BGA voids rising | Profile the reflow oven |
| CP3 | Chassis holes off position | Recalibrate the back gauge |
| CP4 | One memory-tester socket reads low (by socket) | Verify with a golden module, replace the socket; do not scrap modules |
