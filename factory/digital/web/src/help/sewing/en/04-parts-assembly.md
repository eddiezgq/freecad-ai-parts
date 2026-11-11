# Key parts and assembly

## Key part inspection

| Part | Inspection items (example) |
|---|---|
| Upper shaft, lower shaft, overlock main shaft | Bearing seat Ø12 k5, radial runout ≤ 0.01, journal hardness 50–55 HRC, crank clamping flat phase ± 0.5° |
| Needle bar | Diameter Ø8 h5, straightness ≤ 0.005/100, hardness 58–63 HRC |
| Rotary hook | Hook point to mounting datum ± 0.01 (every piece), surface hardness 58–64 HRC |
| Eccentrics | Eccentricity ± 0.01, phase ± 0.5°, hardness 58–63 HRC |

**Aging induction coil → low journal hardness**: the coil erodes and heating is insufficient, the hardened layer is shallow, and the journal wears quickly in its bushing. Replace the coil, and section the first piece to check the hardened layer.

## Metrology lab sampling

Shop gauges measure every piece; the metrology lab does first pieces and sampling, measures what shop gauges cannot, and also rechecks the shop's gauges. The rule: **the first piece of every work order is always sampled, then 1 in every N**. Sampling is not on the routing, so parts keep moving; a few minutes later the metrology equipment produces a measurement record.

| Part | Equipment | Sampled items (example) | Frequency (example) |
|---|---|---|---|
| Castings | CMM (scanning) | Minimum stock on machined faces ≥ 2 mm, core shift | 1 in 20 |
| Housings | Roughness profiler | Bore Ra ≤ 0.8 µm | 1 in 30 |
| Upper shaft, lower shaft, overlock main shaft | Roundness tester / CMM | Bearing seat roundness ≤ 0.003; crank flat phase recheck ± 0.5° | 1 in 10 / 1 in 30 |
| Needle bar | Roundness tester | Diameter roundness ≤ 0.002 | 1 in 30 |
| Rotary hook | CMM | Hook point to mounting datum recheck ± 0.01 | 1 in 50 |
| Eccentrics | CMM | Keyway to eccentric phase ± 0.5° | 1 in 30 |

The housing's full geometric tolerance CMM check is its own operation on the routing (H105). Sampled measurements can be chosen on the “Quality” page (the name ends with “metrology lab sample”); out of tolerance also opens a nonconformance report, but no inspection record is created in ERPNext.

## Lockstitch assembly (textbook 23.4)

Assemble from inside out and bottom up:
- First the upper shaft, lower shaft and timing belt;
- Then feed, stitch length and needle bar / take-up;
- Then the rotary hook, scanning its lot when it is fitted;
- Finally the oil pump, covers, motor and controls.

The adjustment station sets five things:
- Needle bar height;
- Hook timing: loop-taking timing deviation ± 1.5°;
- Hook point gap: 0.04–0.10 mm, target 0.07;
- Feed dog height;
- Presser foot pressure.

Run-in 30 min measures the temperature rise at the bearings; the factory test bench tests three things:
- Test sewing with no skipped stitches;
- Needle stop position error within ± 1°;
- Noise no more than 83 dB(A).

## Overlock assembly

After final assembly five adjustments:
- Needle bar height;
- Lower looper timing;
- Needle to lower looper clearance (0–0.05 mm);
- Differential ratio;
- Knife overlap (0.5–1.0 mm).

During run-in watch oil spraying in the oil window and check for oil seepage. Factory test sews a 514 stitch and checks the trimmed edge at the same time.
