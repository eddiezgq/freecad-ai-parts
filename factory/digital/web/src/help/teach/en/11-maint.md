# Maintenance

> A machine whose PM keeps being put off is more and more likely to fail; a failure means stopping, lockout and waiting for parts, which affects work orders and orders. Whether and when to do PM is worked out with failure rates and the what-if.

## How long can the machine hold out

Digital Factory Practice lab 6-1: Weibull reliability. Drag the run hours and watch the probability of failure rise:

```lab
id: weibull
preset: grd
height: 600
```

```video
name: teach-maint
caption: Maintenance: PM work order, lockout, verify and unlock
```

## Try it now: make the grinder's PM overdue

Press it and GRD-01's run hours are set to 1.4× its PM interval (use the “Maintenance technician” role). Watch “Machines with PM overdue” below grow, and the Plant Insight Hub report “PM overdue” with three options to compare.

```try
action: overdue-pm
label: Make the grinder's PM overdue
note: Clicking GRD-01 on the home page or in the 3D shop also shows “PM overdue by N hours” in the popup.
```

```live
kind: domain
domain: maint
```

## Play with it: how long should the PM interval be

Lab 6-2: too short and PM costs a lot, too long and failures rise. Find the point with the lowest total cost:

```lab
id: pmopt
preset: after
height: 640
```

## Your pick

```quiz
q: The grinder's PM is overdue and a rush order is being pushed. “PM now”, “PM after shift” and “do nothing” all keep the due date. Which is recommended?
options:
  - PM now: the sooner the better | wrong | Stopping the bottleneck now for a few hours loses money, and that counts
  - The one with the smallest “certain cost + expected loss” | right | The recommendation is the smallest total among options that keep the due date; often PM after shift
  - Do nothing: it saves money | wrong | The cost of doing nothing is the expected failure loss, which grows with every overdue hour
more: #PM: from anomaly to verify and unlock
```

```quiz
q: The maintenance technician finishes the PM and clicks “PM completed”. When does the machine come back?
options:
  - At once | wrong | It is still locked out
  - After someone else clicks “Verify and unlock” | right | Neither the person who did the work nor the one who applied for the lock can unlock it
  - After “Reset” on the shop terminal | wrong | The shop terminal cannot reset while it is locked out
more: #PM: from anomaly to verify and unlock
```

```ask
q: What is the probability that the cylindrical grinder fails in the next two weeks?
```

:::查表

## What this page has

Left sidebar “Support → Maintenance” (used most by maintenance technicians). Five numbers at the top: machines with PM overdue, open repair orders, breakdown downtime minutes in the last 7 days, mean time between failures (MTBF), inspection anomalies awaiting handling.

| Tab | What it does |
| --- | --- |
| Equipment register | One row per machine: asset number, hours run since last PM, PM interval, probability of failure in the coming run time, expected loss; click “Details” for the failure rate curve and parameters |
| PM | PM orders: state, duration, who did it and who verified; “PM completed”, “Verify and unlock” |
| Inspections | Choose a machine (or scan the QR code on it), mark each item “OK / abnormal”, submit |
| Repairs & spare parts | Spare parts stock, repair orders; “Repair completed”, “Verify and unlock” |

The asset register, PM plans, PM records and repair orders follow ERPNext's asset maintenance module, set up automatically on first opening.

```goto
tour: maint-tour
label: Show me the equipment register
```

## How failure rates are computed

Whether a machine fails follows a Weibull distribution:

- Probability of failure within t run hours F(t) = 1 − exp(−(t/η)^β);
- Having run t hours without failing, the probability of failure in the next H hours P = 1 − exp(−[((t+H)/η)^β − (t/η)^β]);
- Expected loss = P × (repair cost + mean time to repair × downtime loss per hour);
- PM resets t to 0.

β, η, the PM interval and repair cost are all under “Details”. What the platform computes, what you compute by hand and whether the simulated shop actually “draws” a failure all use the same parameters.

## PM: from anomaly to verify and unlock

1. The Plant Insight Hub reports “PM overdue” (M2) or “High failure risk” (M4).
2. The right panel has three options: **do nothing** (baseline; cost is the expected failure loss) / **PM now** / **PM after shift** (in 4 hours when running 24 hours). The recommendation is the smallest “certain cost + expected loss” among options that keep the due date.
3. Adopt it to create a “PM work order” action. The maintenance technician or plant manager starts it, the plant manager approves.
4. At the scheduled time the machine is **locked out** and stops in the shop, showing 🔒. The shop terminal cannot reset it while locked.
5. The maintenance technician finishes and clicks “PM completed”.
6. **Someone else** clicks “Verify and unlock”: neither the person who did the work nor the one who applied for the lock can unlock it.
7. The machine's “since last PM” goes back to 0, and ERPNext gains a PM record.

```goto
tour: maint-pm
label: Show me the PM order and verify-and-unlock
```

For a cheap machine not long overdue, “do nothing” may even be the better deal. That is exactly what lab 18 asks you to think through.

If a machine keeps failing before its PM, change the PM interval at the bottom of “Details” to create a “Change PM interval” action, effective after the plant manager approves.

## Repairs and spare parts

- When a machine stops on a fault, the platform records the failure and opens a repair order automatically; an inspection anomaly can adopt “Open a repair order”; maintenance can also open one by hand.
- Opening a repair order also opens a lockout permit and an asset repair order in ERPNext.
- When spare parts are short the repair order becomes “Waiting for parts”, the Plant Insight Hub reports “Repair waiting for parts”, and the options are an urgent purchase or waiting for normal purchasing.

## What the Plant Insight Hub reports

| Rule | When it reports |
| --- | --- |
| M1 Same machine stopping repeatedly | One machine alarms 3 or more times within 24 hours |
| M2 PM overdue | Run hours since last PM exceed the PM interval |
| M3 Inspection anomaly | An inspection has failed items not yet handled |
| M4 High failure risk | Probability of failure in the coming run time above 20% (critical above 40%) |
| M5 Repair waiting for parts | Spare parts for a repair order are short |
| M6 Repair overdue | Not fixed after 2× the mean time to repair |
| M7 MTBF falling | MTBF over the last 30 days is more than 30% below the previous 30 days |

The causal chains of M2–M6 link to this machine → operations queued on it → work orders → orders.

## Teaching mode

- **The shop breaks down**: above the “Equipment register” the teacher chooses “Teacher: shop reliability” off (no failures) / normal / accelerated ×5. Reloading the lab 7 scenario sets it back to “off”.
- The simulated maintenance technician finishes repairs and PM on time, waiting for your verification; if nobody verifies a finished breakdown repair for a while, the simulated shift lead verifies it for you, so the shop is not locked forever.
- **Lab 18** Maintenance strategy: deciding when to do PM: “Labs & tasks → Lab 18”. On the lab page the teacher sets a machine's run hours to overdue.
- **Two-week scenario** scene 6: grinder PM overdue.
