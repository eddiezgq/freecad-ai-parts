# Encoder line and error curves

> How good an encoder is comes down to “at each angle, how far off is the reading”. At final test the encoder is coupled to a more accurate reference encoder and turned one revolution, recording the error at every angle — that is the full-turn error curve.

## Operations

| Operation | What it does | What goes wrong if done badly |
|---|---|---|
| Disc cleaning | Ultrasonic cleaning, air shower, handled by the edge in the clean room | Spots on the disc block light, weakening the signal at that angle |
| Bonding and centering | Bond the disc to the hub, align the track center to the shaft under a microscope camera, cure with UV | 1 µm of eccentricity adds about 16″ of first harmonic to the full-turn error |
| Read-head adjustment | Set the read-head to disc gap with a feeler gauge, watch the sine/cosine amplitude | Too large a gap gives low amplitude and large interpolation error |
| Accuracy calibration | Measure full-turn error against the reference encoder and write a compensation table | The table reduces repeatable error, but the eccentricity itself is still there |
| Temperature cycling | Cycle −20 to 85 ℃ several times so adhesive and mechanical stresses settle | — |
| Final test | Remeasure the full-turn error curve and signal amplitude | Pass/fail against the spec |

## What final test records

| Characteristic | Nominal | Spec (example) |
|---|---|---|
| Accuracy (full-turn error peak-to-peak) | About 50″ | ≤ 100″ |
| First harmonic (eccentricity) | About 12″ | ≤ 30″ |
| Interpolation error | About 8″ | ≤ 20″ |
| Signal amplitude (mean) | 100 % | 80 – 120 % |
| Signal amplitude (lowest over the turn) | About 95 % | ≥ 70 % |

17-bit single-turn = 131,072 counts per revolution, one count about 9.9″; 100″ accuracy is about 10 counts.

## Finding the cause from the curve

Open [Encoder error curves](/enc-curve):

| What you see on the curve | Meaning | Where to look |
|---|---|---|
| One big swing per revolution, first harmonic very high in the harmonic breakdown | Disc eccentricity | The bonding and centering machines — split by cb-1 / cb-2; if only one is high it is that machine's fixture |
| Amplitude low overall, interpolation error large | Read-head gap too large | The read-head adjustment bench's feeler gauge |
| A spike at one angle, with an amplitude dip at the same angle | A spot on the disc | Clean room (pressure difference, particle count, filters), disc cleaning |

**A common trap**: with large eccentricity, redoing the compensation table can “flatten” the full-turn error at final test — but the eccentricity is still there, and once it is mounted in a joint, with different mounting and temperature, the error comes back.
What you need to find is why it is eccentric, not how to hide it.
