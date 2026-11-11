# Wafer test and wafer maps

> The prober touches 8 dies at a time and the tester bins each one; the results for the roughly 38,000 dies on a wafer are drawn as a wafer map. From the pattern you can tell whether the chips are bad or the probing was.

## What CP records per wafer

| Characteristic | Nominal (range) | Where it comes from |
|---|---|---|
| CP yield % | 92 (85–100) | Counted from the wafer map — the map and the yield are the same data |
| Probe contact resistance Ω | 1.0 (0–3.0) | Average of the 8 sites |
| Quiescent current IDDQ µA | 1.0 (0–10) | Median |
| Schmitt upper / lower threshold V | 1.254 / 0.607 | Nominal from the round 93 transistor-level simulation |

## Reading the wafer map

The [Wafer map](/wafer-map) page: one small cell per die, green for pass, others colored by failure bin:

| Bin | Looks like on the map | Most likely |
|---|---|---|
| Functional fail (red) | Scattered points, occasionally a small cluster | Random process defects, particles — talk to the foundry |
| IDDQ over limit (orange) | More around the edge | Process non-uniformity at the wafer edge |
| Open / poor contact (purple) | Regularly **every 4 columns and every other row** | Not bad chips — one site of the probe card is making poor contact |

The probe card touches **2 rows × 4 columns** at a time: sites 1–4 in the upper row, 5–8 in the lower. The bar chart on the right counts failure rate per site —
chips do not fail by “site”, so if one site is much higher it is certainly a test problem. The row below shows each site's contact resistance.

## The cost of false fails

Dies touched by the poorly contacting site are actually good, but are failed at CP, marked and not packaged — **good chips thrown away for nothing**.
FT yield is not affected (the bad ones were all stopped at CP), so looking only at FT will not reveal this problem.

## Your pick

```quiz
q: Purple fails on the wafer map appear every 4 columns and every other row; site 6 fails 40 %, the others 4 %. What do you do?
options:
  - Tell the foundry this wafer lot has process defects | wrong | Process defects do not line up with probe card sites
  - Clean the probes, measure each site's contact resistance, replace the probe card if past its life | right | Only one site is high, so that site's probe is worn or dirty; the falsely failed wafers can be retested to recover good chips
  - Retest all CP fails and the problem is solved | wrong | Retesting recovers good chips on these wafers, but without fixing the probe the next wafer is falsely failed too
more: #Reading the wafer map
```

```ask
q: What is the CP yield of the last few wafers? Which site fails most?
```
