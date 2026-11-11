# Assembly and final test

> Dicing, die attach, bonding, molding… every step has sampling; results are recorded per lot at the FT station and go into control charts.

## What each finished lot records

| Characteristic | Nominal (range, example) | Sampled at |
|---|---|---|
| Dicing chipping µm | 10 (0–25) | Sampled after dicing, maximum taken |
| Wire pull gf | 6.0 (≥ 3.0) | Pull test after bonding, minimum taken; **records which bonder** |
| Ball shear gf | 25 (15–40) | Shear test after bonding |
| Mold void rate % | 1.0 (0–3.0) | X-ray sampling after molding |
| FT yield % | 98 (95–100) | Final test |
| Operating current mA | 0.67 (0.4–1.0) | Nominal from the round 92 layout power |
| Schmitt hysteresis V | 0.648 (0.45–0.85) | Nominal from the round 93 transistor-level simulation |

An item has only one inspection template in ERPNext, so the bonding, molding and dicing sampling results are traced by lot and recorded together at FT.

## Four problems the teacher can inject

| Problem | How it shows in the data | The right fix |
|---|---|---|
| Probe card wear | Site 6 contact resistance rises wafer by wafer, that site regularly turns purple on the map, CP yield drops; FT not affected | Clean the probes, replace the probe card past its life |
| Dicing blade wear | Chipping grows lot by lot, FT yield drops slightly | Replace the dicing blade |
| Capillary wear on bonder wb-2 | **Only lots bonded on wb-2** lose pull and shear strength; wb-1 is normal | Replace wb-2's capillary |
| Molding compound absorbed moisture | Void rate rises | Quarantine the affected lot, warm up per procedure, use within the time limit |

Fixes that “sound reasonable but miss the cause” are listed too: retest all CP fails, raise bonding power, tighten FT limits… Students work an 8D on a quality issue, and only the right fix brings later lots back.

## Hands on: wire pull split by bonder

On the “Quality” page choose “WQ-ENCIF · Wire pull” and stratify by “Assembly station”: wb-1 and wb-2 separately.

```anim
name: spc
caption: Alarm first, then out of tolerance: pull strength keeps falling, check the capillary before it leaves the limits
```

## Your pick

```quiz
q: Wire pull drops only on lots bonded on wb-2; wb-1 is normal. What is the most likely cause?
options:
  - This spool of gold wire is bad | wrong | Both use the same wire lot; bad wire would be low on both
  - Capillary wear on wb-2 | right | Only one machine is low, so check that machine's own parts: capillary life, ultrasonic parameters
  - Molding compound absorbed moisture | wrong | Molding comes after bonding; it affects voids, not pull strength
more: #Four problems the teacher can inject
```
