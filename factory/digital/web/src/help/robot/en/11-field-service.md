# Customers and service: robots in the field

> Once a robot reaches the customer's site, it sends back a run summary every site day. The as-built record traces all the way to joints and harmonic drive lots: joints whose backlash grows fast in the field often share the same bad lot of gearboxes (round 64).

## What is recorded when a robot ships

When robot calibration is done, the platform creates a record for this WQ-CR5:

- Which joint module each of the 6 joints is (joints tested on the joint test bench are assigned **first-in first-out** by size), which harmonic drive lot it uses, its as-built backlash;
- Absolute positioning error after calibration, production work order, sales order.

Once the order is invoiced, the robot counts as shipped to the customer's site, and from that day it reports every site day: run hours, each joint's backlash, peak temperature, RMS current, collision count.
In teaching mode 1 minute = 1 site day. There are also 8 robots “already in use before the scenario starts” (examples), spread over three customers.

## What goes wrong in the field

| Symptom | Cause (example model) | How to handle |
|---|---|---|
| Backlash slowly grows toward / past the limit (1.0′ for large and medium joints, 1.2′ for small); the customer says “noise, picks are off” | Harmonic drive wear; **problem lots wear fast** (those that actually had problems on arrival, were quarantined, or had high as-built backlash) | Replace the joint module on site (spares are the plant's own WQJ-L / M / S finished goods) |
| Joint peak temperature over 70 ℃ | Grease aging (after about 540 site days) | Regrease on site |
| After one heavy collision, positioning is off | The zero has shifted | Recalibrate remotely |

The platform raises warnings on these (rule RS1), and when two or more robots with the same gearbox lot exceed the limit it raises “multiple alarms in one lot” (RS2), prompting a check of that lot's incoming inspection and joint test data.
Open the alarm in the “Plant Insight Hub” to see the options (the matching service dispatch, preventive replacement for the same lot), or ask the AI assistant directly “Which robot in the field is alarming?” (round 67).

```anim
name: recall
caption: One unit has a problem, trace it to the lot, then check the others shipped from that lot
```

```live
kind: kpi
```

## Hands on: register a complaint and dispatch

In “Customers & service → Complaints & service orders”, choose a robot, write one sentence on the symptom and register it — an issue is opened in ERPNext at the same time.
Back in “Robots in the field”, click this robot to see its backlash trend and as-built record (which joint, which lot), and choose a service option to dispatch; the engineer finishes on the day, and the customer follow-up records satisfaction.

```goto
tour: rservice-complaint
label: Help me register a complaint
```

```quiz
q: Two robots in the field both have J2 backlash over the limit, and their as-built records show their J2 used the same harmonic drive lot. What should be done next?
options:
  - Replace J2 on just these two | wrong | Other robots shipped with the same lot will have problems sooner or later
  - Replace J2 on these two, find which other robots carry this lot, schedule preventive replacement, and check this lot's incoming inspection | right | One unit has a problem, trace to the lot, check the same lot — that is how a recall works
  - Recalibrate every robot | wrong | Backlash is gearbox wear; calibration cannot make it up
more: #What goes wrong in the field
```

```quiz
q: A robot's J5 peak temperature is 74 ℃, backlash is normal, and it has not collided recently. Which service option?
options:
  - Regrease on site | right | Normal backlash with high temperature is most likely aged grease
  - Replace the joint module on site | wrong | Backlash is within limits; replacing the module is too expensive
  - Recalibrate remotely | wrong | Calibration fixes zero and geometric errors, not temperature
more: #What goes wrong in the field
```

## Lab 29: tracing one robot after sale

Do it under “Labs & tasks → Lab 29”: the platform plants a scenario for you — the same bad gearbox lot is in J2 of 3 robots, 1 already over the limit and 2 not yet.
Find the robot and joint in alarm, read the as-built record (lot number, as-built backlash), judge the cause, set the recall scope (which other robots carry the same lot), dispatch and complete the matching service orders,
and compare the cost of preventively replacing the whole lot with replacing only when they alarm. The platform scores 60 points automatically and the report is 40; the lab guide and report template (bilingual) are at the top right of the lab page.
