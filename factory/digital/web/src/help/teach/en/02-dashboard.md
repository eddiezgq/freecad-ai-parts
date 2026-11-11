# Reading the home page

> The home page is the face of the whole plant: briefing, metrics, machines, orders, quality and materials on one screen. When something goes wrong in one place, several panels change together.

## How data reaches the home page

Numbers from the shop, ERPNext and every domain flow into the unified data bus and the historian; the home page and the Plant Insight Hub read the same copy:

```anim
name: flow
caption: Whatever happens at each stop becomes data, and the home page shows it all on one screen
```

```video
name: teach-home
caption: Home page: briefing, metrics, shop live, orders; when the grinder stops, several panels change together
```

## Try it now: stop the grinder

Press it and GRD-01 really stops for 2 hours (factory time). Watch the machine below turn red within seconds, then go back to the home page and look at the risk tags under “Orders & due dates”.

```try
action: stop-grinder
label: Stop the grinder for 2 hours
note: After pressing, watch the machine states below: GRD-01 turns red within seconds. On the home page click its card for its state and help.
```

```live
kind: machines
```

## This plant's metrics right now

```live
kind: kpi
```

```goto
tour: home-tour
label: Walk me through the home page
```

## Your pick

```quiz
q: A machine on the home page shows 🔒 and the operator clicks “Reset” on the shop terminal. What happens?
options:
  - The machine runs again | wrong | Reset does nothing while it is locked out
  - Nothing; the fix or PM must be finished and someone else must verify and unlock | right | 🔒 means a fix, PM or repair is in progress; unlocking needs verification by another person
  - The plant manager is notified to approve automatically | wrong | Unlocking comes from verification, not approval
more: #Machine states
```

```quiz
q: At 1× speed the numbers on the home page hardly move for minutes. What does that mean?
options:
  - The unified data bus is down | wrong | First check whether the bottom of the left sidebar says “Connected”; if it does, that is not the reason
  - Normal: 1× is real time, and a factory changes slowly | right | In class the teacher sets the speed to 20–30× in the teacher console
  - The dashboard is broken | wrong | The dashboard reads the same data as everywhere else
more: #The numbers on the home page do not move?
```

```ask
q: Which metric is furthest from its target today, and why?
```

:::查表

## What is on the home page

| Area | What to look at |
| --- | --- |
| AI daily briefing | The three or four things that matter most now; each states its source. In teaching mode it only points the way |
| Key metrics | On-time delivery, WIP, overall equipment effectiveness (OEE), first-pass yield, completed this week, cost variance; the colored note says how far from target |
| Shop live | Each machine's current state; the “Bottleneck” tag marks this week's most loaded machine; click a machine card for its state and help |
| Orders & due dates | Open orders by due date; the tag is the system's predicted delay risk |
| This week: plan vs actual | Hollow bars are plan, solid bars are actual completions |
| Quality | Control chart of a key dimension: red dashed lines are the tolerance limits |
| Key materials | Stock, in transit, days available; red means below safety stock or short for this batch |
| Alerts & to-dos | What your role needs to handle; in teaching mode, the lab tasks |

## Machine states

| Color or mark | State | Meaning |
| --- | --- | --- |
| Green | Running | Machining |
| Gray | Idle | No work, or waiting for material |
| Yellow | Setup | Changeover, tool change, wheel dressing, warm-up after standby |
| Red | Down | Fault; after handling it click “Done, reset” on the shop terminal |
| 🔒 | Locked out | A fix, PM or repair is in progress; someone else must verify and unlock; reset does nothing |
| 👤 | No operator | Nobody on this shift can run this machine (see “People & shifts”) |

## The alert bar at the top

When there is a critical anomaly, or a warning with options (downtime, shortage, due date), a “Plant Insight Hub” alert appears at the top of the home page; click “Handle it” to go to the command center.
Students in teaching mode do not see this alert: lab 7 wants you to find problems on the dashboard yourself.

## The numbers on the home page do not move?

- Check whether the bottom of the left sidebar says the “unified data bus” is “Connected”;
- At 1× speed changes are slow; that is normal. The teacher sets the speed in the teacher console of the “Scenario director”.
