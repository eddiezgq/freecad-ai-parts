# Motor final test and test waveforms

The motor final test bench is a **dynamometer**: the motor under test and a load motor are joined by a coupling. Final test does three things:

1. **Back-EMF**: the motor under test is unpowered; the load motor drives it one revolution at constant speed while the three line voltages are recorded.
2. **Cogging torque**: unpowered, turn it slowly one revolution and record the torque — the small torque of the magnets and stator teeth “pulling back and forth”.
3. **No-load current**: power the motor under test and run it unloaded (3000 rpm), and watch the current.

## Reading the “Motor final test waveforms” page

Open [Motor final test waveforms](/motor-wave); on the left are recently tested motors — click one to see its waveforms:

| Where to look | Normal | What abnormal means |
|---|---|---|
| Three-phase back-EMF | All three phases equally high, 120° apart | All three low together → magnets not saturated (check the magnetizer); one phase low → a problem in that phase's winding |
| Line back-EMF harmonics | Fundamental at 5 per revolution (10 poles), everything else very small | “Sub-harmonics” such as 4, 6, 9, 11 rising → the 10 magnets differ in strength or position |
| Cogging torque | Mainly 60 per revolution (the design value for 10 poles 12 slots) | 12 and 24 per revolution growing → magnets bonded crooked (check the magnet bonding fixture) |
| The 10 magnets | Similar strength, position error within a few tenths of a degree | Position errors over 1° in red |

**Back-EMF constant, three-phase unbalance, harmonic distortion and cogging torque are computed from the curves**, so the curves and the measurement record always agree.

## Why cogging at 12 per revolution is normally zero

Each magnet passing the 12 slots produces torque ripple at 12, 24… per revolution. The 10 magnets are evenly spaced around the circle, so their ripples are exactly out of phase and cancel when added,
leaving only the 60-per-revolution term (the least common multiple of 10 and 12). Once a magnet is bonded crooked, the phases are no longer evenly spread and the 12 and 24 terms no longer cancel.

**Compensating cogging torque in the drive** makes the motor run smoother, but the magnets are still crooked: change the drive or the temperature and the problem returns — that is “masking”, not “correcting”.
