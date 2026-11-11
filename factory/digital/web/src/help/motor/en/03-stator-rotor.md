# Stator and rotor

## Stator: laminations → coils → varnish

1. **Core stacking**: stack electrical steel laminations one by one, press and interlock them; the stack height must be right.
2. **Winding**: a needle winder winds magnet wire into the 12 slots. **Tension** must be steady — if it swings, the wire is stretched thin and turns drift, so the three phase resistances differ, and the enamel is easily scratched between turns.
3. **Insertion and forming**: insert slot wedges, lace and form the end turns.
4. **Varnish and bake**: vacuum-impregnate with insulating varnish, then bake through in the oven. **If the oven is too cool the varnish does not fully cure**, insulation is poor and hipot leakage is high.
5. **Stator test**: measure three-phase resistance (is it balanced), turn-to-turn surge (compare the area difference of two coils' surge waveforms), hipot (apply 1500 V and watch the leakage current).

Stators from both winders wd-1 and wd-2 record the “winding machine” (the stratification field of the measurement record), so [Quality](/work/quality) and [Motor final test waveforms](/motor-wave) can both split them by winder.

## Rotor: bond magnets → magnetize → balance

1. **Magnet bonding**: 10 NdFeB magnets are bonded onto the rotor core using a locating fixture. **When the fixture wears, magnets are bonded crooked** — a few tenths of a degree off, and cogging torque grows.
2. **Magnetizing**: a capacitor discharge saturates the magnets at once. **If the capacitors age and the magnetizing voltage is too low**, the magnets are not saturated, the back-EMF constant is low across the board, and the same output takes more current.
3. **Balancing**: measure the rotor's unbalance and remove or add weight.

Magnets are bonded first and magnetized after: unmagnetized magnets do not grab steel parts, so they are easy and safe to bond.
