# Quality and quality issues (8D)

> Every part is measured; read trends on the control chart, open an 8D when there is a problem, and the data improves only when the action addresses the cause.

## What the control chart is saying

Dots jumping around the center line are normal; when they drift to one side while parts still pass, the out-of-control rules already alarm — and this is when fixing it is cheapest:

```anim
name: spc
caption: The wheel slowly dulls: first an alarm, then out of tolerance
```

```video
name: teach-8d
caption: Control charts and quality issues (8D)
```

## Hands on: open a quality issue

Look at this plant's control chart right now and open an 8D for the characteristic with a problem. Once opened, this step ticks itself (use the “Quality inspector” role).

```goto
tour: quality-chart
label: Show me the control chart and open a quality issue
```

```live
kind: kpi
```

## Your pick

```quiz
q: The bearing seat diameter grows part by part, and the control chart reports “4 of 5 consecutive points beyond 1σ on the same side”, but all parts are still within tolerance. What now?
options:
  - They all pass, leave it | wrong | The trend continues; a few more parts and they will be out of tolerance
  - It has alarmed: find the cause (most likely a dull wheel), dress the wheel or open an 8D | right | The point of a control chart is to catch problems before nonconforming parts appear
  - Scrap all of these parts | wrong | These parts are good
more: #Control charts
```

```quiz
q: After the 8D action is approved and sent down, the shop makes 10 more parts, all good, but Cpk is 1.1. Can the 8D be closed?
options:
  - Yes, all good is enough | wrong | Process capability must also be enough: Cpk ≥ 1.33
  - No: verification needs all good and Cpk ≥ 1.33, and D7 must be written | right | Only an action that addresses the cause, with a stable process, counts as effective
  - Yes, once the teacher approved it | wrong | Approval is for the action; verification looks at the data
more: #Quality issues (8D)
```

```ask
q: Why does the bearing seat size grow part by part?
```

:::查表

## Control charts

The simulated shop's CMM data is synthesized by a machining error model: normally there is only random error and the part-by-part upward drift from wheel wear.
Each output shaft is measured on 6 items: left and right bearing seats, gear seat, keyway width, bearing seat runout and keyway symmetry.

Red dashed lines are the tolerance limits; the closer the dots get to them, the more attention they need. Out-of-control signals use Western Electric rules 1–4: 1 point beyond 3σ; 2 of 3 consecutive points beyond 2σ on the same side; 4 of 5 consecutive points beyond 1σ on the same side; 8 consecutive points on the same side of the center line. Out-of-tolerance parts automatically get a nonconformance, and the inspector chooses rework, scrap or concession.

## Quality issues (8D)

1. On the “Quality” page, when you find an anomaly, click “Open for current characteristic”;
2. Fill in D1–D8; for D5 choose a corrective action from the list, give the reason, and submit;
3. After the teacher approves, the action is sent to the simulated shop — only an action that addresses the cause makes the problem go away;
4. After the shop makes at least 10 more parts, click “Verify”: compare counts, means, out-of-tolerance parts and Cpk before and after. Effective only when all pass and Cpk ≥ 1.33;
5. It can be closed only after D7 is written (which process documents changed, what error-proofing was added).

## Quality and the other domains

- The Plant Insight Hub's quality rules (out of control, approaching tolerance limits, nonconformance not dispositioned, falling yield, 8D open too long) open anomalies whose causal chains trace to the part, tool or wheel, and machine.
- Incoming inspection is also done by quality; see “Purchasing & incoming”.
- Customer complaints trace to the shipped output shaft and the wheel that ground it; see “Customers & service”.
