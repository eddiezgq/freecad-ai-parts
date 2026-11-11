# Safety and environment

> A hazard is not an isolated form: it can stop a machine and so affect work orders, orders and customers. For a major hazard, stop and lock out first, fix it, then someone else verifies and unlocks.

## How a major hazard goes

Risk = likelihood × severity; in the red zone, stop and lock out first, and after the fix someone else verifies and unlocks:

```anim
name: risk
```

```video
name: teach-ehs
caption: Report hazard → assess → lock out and fix → verify and unlock
```

## Try it now: report a major hazard

Press it and the demo plant really reports one: the grinder guard door interlock is bypassed. Watch the open hazards below gain one, then look at the options for “Major hazard not closed” in the Plant Insight Hub. Anyone can press it.

```try
action: major-hazard
label: Report a major hazard
note: Within 20 s the Plant Insight Hub reports E1, and the causal chain links to the grinder's work orders and orders.
```

```live
kind: domain
domain: ehs
```

You can also snap one yourself. Once submitted, this step ticks itself:

```goto
tour: ehs-tour
label: Help me report a hazard
```

## Your pick

```quiz
q: The grinder guard door interlock is bypassed and a rush order is being pushed. Among the hub's options, “A Do nothing, keep producing” is marked “failed checks”. Why is it listed?
options:
  - So you can choose it: you may skip stopping while rushing | wrong | Producing with a major hazard is not allowed by safety rules
  - Only for comparison: to see how late the order gets and how much stopping to fix costs | right | The recommendation first drops options that fail checks, then compares delivery, then money
  - It is a system error | wrong | It is listed on purpose as a baseline
more: #Options (major hazard)
```

```quiz
q: The maintenance technician fixes the interlock and clicks “Verify” himself. Is that allowed?
options:
  - Yes, he knows it best | wrong | The fixer cannot verify their own fix
  - No; the safety officer or plant manager, another person, verifies, and unlocks at the same time | right | Two people check, so the machine does not start before the job is done
  - Yes, but with a photo | wrong | Photos are for snapping hazards
more: #How a hazard goes
```

```ask
q: What safety risks does the cylindrical grinder have?
```

:::查表

## What this page has

Left sidebar “Support → Safety & environment” (used most by safety officers). Five numbers at the top: open hazards (how many major and overdue), on-time fix rate, machines locked out, trainings expiring within 30 days, near misses (last 30 days).

| Tab | What it does |
| --- | --- |
| Hazards | “Snap it”: choose a machine or area, a type and a level, write a sentence, take a photo, submit; the hazard source list is below |
| Work permits | Hot work, height, confined space, lockout; the worker's training is checked automatically on application |
| Incidents & near misses | Anyone can report; details are visible only to the plant manager and teachers |
| Training & qualifications | One cell per person per training type: red expired, yellow expiring within 30 days |
| Chemicals & waste | Stock of coolant, quench oil and lubricant; hazardous waste storage and disposal |

Fix work orders go to ERPNext through the bridge. Once a lockout is approved, the machine really stops in the shop.

## How a hazard goes

To assign → fixing (the safety officer assigns a fixer) → to verify (the fixer clicks “Fix completed”) → closed (the safety officer verifies).

- Major hazards are fixed within 1 day, normal ones within 7 days;
- The fixer cannot verify their own fix;
- A locked-out hazard is unlocked at verification.

## Who does what

| Role | Can do |
| --- | --- |
| All roles | Snap hazards, report near misses |
| Safety officer | Assign fixes, verify, approve work permits, record training, dispose of hazardous waste; verify and unlock, schedule training |
| Plant manager | Same as the safety officer; approve lockout fixes and fix work orders (they cost money) |

## What the Plant Insight Hub reports

| Rule | When it reports |
| --- | --- |
| E1 Major hazard not closed | A major hazard is open (critical) |
| E2 Hazard fix overdue | Past the fix deadline |
| E3 Work permit lacks qualification | The worker's training is not valid (critical) |
| E4 Safety training expiring | Expiring within 30 days or expired |
| E5 Machine running while locked out | Someone removed the lock without the permit (critical) |
| E6 Chemical stock abnormal | Below safety stock or above the on-site limit |
| E7 Hazardous waste stored too long | Hazardous waste stored more than 90 days |

The causal chain of a major hazard links to the machine → operations queued on it → work orders → orders, just like downtime.

## Options (major hazard)

| Option | What it does |
| --- | --- |
| A Do nothing (baseline) | Keep producing with a major hazard: not allowed by safety rules, fails checks, for comparison only |
| B Lock out and fix now | Stop now, fix in the standard time, unlock after verification |
| C Fix within a time limit | Interim guard, slower speed and an attendant first, stop later |
| D Lock out and fix + reassign / overtime | Only when a similar machine can take the work, or overtime is possible on shifts |

The recommendation first drops options that fail checks, then compares delivery; with equal delivery, stopping now comes first; money last.

## Teaching mode

- Every so often the simulator reports a normal hazard near a machine, and occasionally a near miss; coolant is consumed and steel chips produced as the shop runs.
- For locked-out fixes, a certified maintenance technician finishes after a while, waiting for your verification.
- **Lab 17** Identifying, assessing and stop decisions for safety hazards: “Labs & tasks → Lab 17”. On the lab page the teacher injects a major hazard, and can also “simulate an illegal lock removal”.
- **Two-week scenario** scene 5: the grinder guard door interlock is bypassed while rushing.
