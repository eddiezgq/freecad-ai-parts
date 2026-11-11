# Plant Insight Hub: from anomaly to ERPNext

> Rules look over the whole plant every 20 seconds; on an anomaly they trace the cause and compute the impact; options are simulated first, then adopted as actions, and only after approval are they really executed and written back to the shop or ERPNext.

## How an anomaly is traced

Links light up one by one from root cause to impact; click any link to see its evidence:

```anim
name: causal
```

```video
name: teach-anomaly
caption: Tracing an anomaly: cause, impact, what-if
```

## Try it now: create an anomaly, then trace it

Press it and the grinder really stops for 2 hours. Within 20 seconds the Plant Insight Hub reports “Machine down”; open it, compare the options, and adopt one to create actions — once adopted, this step ticks itself.

```try
action: stop-grinder
label: Stop the grinder for 2 hours
note: Then click “Help me compare options” below and choose this “Machine down” in the left panel of the command center.
```

```live
kind: kpi
```

```goto
tour: ont-options
label: Help me compare options
```

## Play with it: the causal chain of one stop

Digital Factory Practice animation 3-1: change the situation and see what the same stop affects.

```lab
id: causal
preset: rush
height: 560
```

## Your pick

```quiz
q: In the what-if, option A is on time and costs $800 extra; option B is 1 day late and costs $200 extra. Which does the hub mark “Suggestion”?
options:
  - B, it costs less | wrong | On time first, then money
  - A: options are ranked “on time → less money → less overtime” | right | The first is marked “Suggestion”, with a sentence giving the reason
  - Neither; people choose | wrong | A suggestion is marked; only in compare mode is it hidden until you submit
more: #What-if and options
```

```quiz
q: You adopted an overtime option and created an action. What next?
options:
  - It is already executed | wrong | Adopting only creates the action; it needs approval
  - It goes to the action inbox; after the plant manager approves, the executor changes the shift roster and sends it to the shop | right | Actions that cost money need the plant manager; you cannot approve your own
  - Click “Approve and execute” yourself | wrong | You cannot approve actions you started
more: #Actions, approval, writing back to ERPNext
```

```ask
q: What is the most serious anomaly right now, and what caused it?
```

:::查表

## One main thread

| Step | Where | What |
| --- | --- | --- |
| 1 Anomaly | Left panel of “Anomalies” in the command center | Rules find a problem in the data and open an anomaly (number A-xxxxx) |
| 2 Causal chain | Middle panel | Look up for causes, down for impact: which machine, work order, order, customer |
| 3 What-if | Right panel “What-if & suggestions” | Restore a copy of the shop from a snapshot, apply the option and fast-forward; compute due date, cost, risk |
| 4 Options | Right panel | Several ways (including “do nothing” as a baseline) side by side; the first is marked “Suggestion” |
| 5 Action | Click “Adopt, create actions” | Creates an action needing approval, in the action inbox |
| 6 Approval | Action inbox | Someone with permission clicks “Approve and execute” or “Reject” |
| 7 Execute, write back | Executor | Sends to the shop, changes the shift roster, or creates documents in ERPNext |
| 8 Review | Below a closed anomaly | What-if and actual side by side |

All roles can open the Plant Insight Hub: left sidebar “Overview → Plant Insight Hub”.

## The whole plant on one screen

The command center's first screen is “Plant situation”: a value chain row and a support row, one card per domain.
Cards show one or two key metrics with a 7-day sparkline, and the number of open anomalies (red critical, yellow warning, blue notice). Click a card to see only that domain's anomalies.

The time bar at the top looks back to any moment in the last 7 days; when looking back, click “What-if from here” for a retrospective what-if of “what if we had done it differently”.

```goto
tour: ont-situation
label: Show me the plant situation
```

## Where anomalies come from and how they are traced

- The same problem opens only one anomaly; recurrences just add to the count; a higher severity alerts again.
- When the condition is gone for two consecutive checks, the anomaly clears itself with the reason stated.
- Every edge of the causal chain states its evidence: which ontology link, or which existing computation. Click an edge to see the evidence and open the raw record.
- Problems injected by the teacher show to students as “Cause to be found”. That link is for you to trace.

Each of the seven domains has its own rules (shortage, rejected incoming, staffing gap, major hazard, PM overdue, idle energy, overdue receivable…); see each domain's chapter. All rules are in the command center's “Rule catalog”.

```goto
tour: ont-anomaly
label: Help me trace an anomaly
```

## What-if and options

Open an anomaly and the right panel “What-if & suggestions” simulates several options from this anomaly type's playbook automatically.

- Each option gives: the affected orders' expected delivery (days late or spare), extra cost, overtime; energy options also give kWh, electricity cost and carbon.
- Options are ranked “on time → less money → less overtime”; the first is marked “Suggestion” with a sentence giving the reason. If doing nothing is enough, the suggestion is “do nothing”.
- Options that break rules (e.g. producing on with a major hazard) are marked “failed checks”, for comparison only.
- Customer complaint options are not simulated in the shop; they are estimated from the service engineers' roster.

The what-if simulates part by part and is more accurate than the rough estimate under “Orders & due dates” on the home page. When they differ, the what-if wins.

## What-if workbench

Under an option in the right panel click “Fine-tune in the what-if workbench”. On the left you can stack changes: reassign, resequence, rush order, overtime, expedite repair, urgent purchase, subcontract, split delivery, plus each domain's lockout fix, PM stop, roster and arrival date.

In the middle are the Gantt chart and the order table, switchable between “do nothing / this option”. On the right, save scenarios and compare up to 4 side by side.

## Actions, approval, writing back to ERPNext

After “Adopt, create actions” the action goes to the “Action inbox”. States: awaiting approval → approved and executed → done (or execution failed, rejected).

- Actions that cost money (overtime, urgent purchase, subcontracting, expedited repair, PM, dispatch…) need the plant manager; others are approved by the relevant role per each domain's rules.
- You cannot approve actions you started. In teaching mode the teacher may approve their own (class demo); students ask the teacher or another student.
- Before approving you can “Dry run again on the latest snapshot”: if things changed and the result differs, it tells you.

| Example action | Who does it after approval |
| --- | --- |
| Reassign, resequence, subcontract, expedite repair | Sent to the shop |
| Overtime | Changes the shift roster and is sent to the shop |
| Urgent purchase | Creates a material request in ERPNext |
| Split delivery | Leaves a delivery arrangement note on the ERPNext sales order |
| Service dispatch, fix work order, PM, repair | Opens a service order, fix order, PM record or asset repair in ERPNext |

```goto
tour: ont-inbox
label: Show me the action inbox
```

## Review and daily reports

- When an anomaly is handled and the affected work orders are done, the platform generates a review: what-if completion vs actual, possible causes of the deviation, and “what if we had chosen another option”.
- “Daily & weekly reports”: in teaching mode a button generates one at once, usable as lab material.

## AI factory assistant

“AI factory assistant” in the left sidebar, or “Ask the AI factory assistant” on the home page. Behind it is an AI agent: it looks things up in the Plant Insight Hub itself, traces causes, runs what-ifs and compares options.

- You can ask: which order will be late and why? Where is this week's bottleneck? How should an anomaly be handled? Or just give a number (machine ID, work order number).
- The [1] [2] after each conclusion are evidence; opening them shows the object page, anomaly, what-if scenario or raw message.
- Every number in the answer must be found in the data it looked up; any it cannot find is marked yellow “unverified”.
- Every anomaly in the command center has “Ask AI to analyze” at the top.

```video
name: teach-ai
caption: Asking the AI, checking the evidence
```

## The AI only drafts; people decide

```anim
name: ai-draft
```

- In teaching mode, the AI only gives students hints: which page and what data to look at; it does not give lab answers or draft anything.
- “Compare mode” in labs: until you submit your own choice, the right panel shows no “Suggestion”, and the AI also only gives hints.
- In production mode it can draft actions; you click “Submit (with dry run)” under “Action inbox → Started by me”, then it is approved per permissions.
