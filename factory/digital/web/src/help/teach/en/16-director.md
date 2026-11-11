# Teachers only: scenario director and teacher console

> The scenario director uses one rush order to string the seven domains into a two-week play of eight scenes, played one at a time; the teacher console at the bottom of the page controls speed, fault injection, shifts and reset. Each domain's switches are on its own page.

## One rush order through seven domains

The eight scenes fall in turn on orders, purchasing, people, safety, maintenance, energy and business; the cost of actions adopted in every scene is charged to this order's margin:

```anim
name: flow
caption: Every stop an order passes can be a scene in the play
```

```video
name: teach-director
caption: Scenario director: start the two-week scenario, next scene, review
```

## Try it now: give the shop a problem

The same path as “Inject a fault” in the teacher console: the grinder stops for 2 hours. Press it in class and let students trace it in the Plant Insight Hub.

```try
action: stop-grinder
label: Stop the grinder for 2 hours
note: To restore: “Reset the lab 7 scenario” in the scenario director, or “Start the two-week scenario” again.
```

```live
kind: machines
```

```goto
tour: director-tour
label: Show me the scenario director
```

## Your pick

```quiz
q: Next class you want to run the two-week scenario from the start without clearing students' existing lab scores. What do you click?
options:
  - “Reset the lab 7 scenario” in the teacher console with “Also clear student scores” ticked | wrong | Ticking it clears scores
  - “Start the two-week scenario” | right | It clears the shop history and reloads the scenario; student scores are kept
  - Sign out and back in | wrong | The scenario is still running
more: #How to run it
```

```quiz
q: The demo has only 30 minutes, and scene 8 must wait until the order is finished to invoice. What do you do?
options:
  - Set the speed to 300× and keep waiting | wrong | Possible, but fast-forward is easier
  - Click “Fast-forward until the order is done” | right | Fast-forward before scene 8; for demos also tick “Auto demo”
  - Skip scene 8 | wrong | Scene 8 is key to reviewing the margin
more: #How to run it
```

```ask
q: What decision do students make in scene 4 of the two-week scenario?
```

:::查表

## Where the scenario director is

Left sidebar “Teaching → Scenario director”. Teaching mode only, teachers only; use the “Plant manager” role to start.
Students follow along in “Labs & tasks → Lab 23”.

## The eight scenes

| Scene | Script day | What happens | Domain | Plant Insight Hub reports |
| --- | --- | --- | --- | --- |
| 1 | Day 1 | A customer places a rush order; order, work order and material request go into ERPNext, the output shaft work order is released to the shop | Customers & service, Orders & planning | — (timeline checks “order released”) |
| 2 | Day 2 | Bearings short; a purchase order goes to the supplier | Purchasing & incoming | W1 shortage |
| 3 | Day 4 | The lot arrives, incoming inspection finds out-of-tolerance pieces, the whole lot is rejected | Purchasing & incoming, Quality | W3 incoming rejected |
| 4 | Day 6 | The cylindrical grinder's skilled operator is on leave next shift | People | H2 staffing gap |
| 5 | Day 7 | While rushing, the grinder guard door interlock is bypassed | Safety & environment | E1 major hazard |
| 6 | Day 9 | The grinder's run hours exceed the PM interval | Maintenance | M2 PM overdue |
| 7 | Day 11 | The band saw keeps idling; heat treatment is loaded at peak | Energy & environment | N2 high idle energy |
| 8 | Day 14 | The order is done and invoiced; that invoice is overdue and unpaid without a reminder | Business & finance | F2 receivable overdue |

“Day N” is the script day, only a label: clicking “Next scene” makes it happen at once. The scenario has a single main order; the cost of actions adopted in every scene is charged to its margin, and the invoice overdue in scene 8 is its own.

## How to run it

1. Choose the speed (20–30× in class, 30–60× for demos), and decide whether to tick “Auto close-out”: ticked, fixes and PMs due with nobody closing them are finished and unlocked by “people in the scenario”; unticked, students do it themselves.
2. Click “Start the two-week scenario”: it clears the teaching-mode shop history and reloads the lab 7 scenario; you can start in a dozen or so seconds. Student scores are kept.
3. Click “Next scene”. On the timeline the scene shows “Waiting for Plant Insight Hub”, and ticks when the anomaly appears; click the anomaly name to open it in the command center.
4. In each scene let students read the causal chain, compare options and adopt them as actions in the command center; you approve them in the “Action inbox”.
5. Scene 8 waits for the shop to finish this order. If short of time, click “Fast-forward until the order is done”.
6. Click “Review”: this order's margin breakdown, the money each scene spent on it, the cross-domain causal chain, and the two weeks' weekly reports.

For demos tick “Auto demo”: after each scene's anomaly appears it waits N seconds and moves to the next scene.

| | Class version (lab 23) | Demo version |
| --- | --- | --- |
| Time | Two weeks, one or two scenes per class | All at once, 20–30 minutes |
| Speed | 20–30× | 30–60×, fast-forward before scene 8 |
| Auto close-out | May be unticked so students do it | Ticked |

## Teacher console

At the bottom of the scenario director page. Commands go over the bus to the simulated shop.

| Function | How |
| --- | --- |
| Simulation speed | 1×–300×, click “Apply” |
| Inject a fault | Choose machine, downtime minutes and cause, click “Inject” |
| Shop shifts | 24-hour continuous, or by shift (Mon–Fri); only by shift do the hub's options include “overtime” |
| Reset the lab 7 scenario | Clears teaching-mode history and reloads the scenario; scores are cleared only if “Also clear student scores” is ticked |

```goto
tour: teacher-console
label: Open the teacher console
```

“Start the two-week scenario” does not clear student scores; to clear them use “Reset the lab 7 scenario” here with the box ticked.

## Teacher switches in each domain

Students cannot see these. After reloading the lab 7 scenario, all the simulators below go back to “off” (the shop behaves as before, without these problems).

| Where | Switch or injection |
| --- | --- |
| Quality → Problem scenarios (teacher) | Inject hidden machining problems: grinder tailstock offset, wheel dressing interval too long, grinder not warmed up, keyway fixture locator worn, poor center holes, blunt dressing (grinding burn); students open an 8D and you approve the action |
| Maintenance → Equipment register → Teacher: shop reliability | Off (no failures) / normal / accelerated ×5 |
| People → top | Shop “someone must be present” on / off |
| Purchasing & incoming → top | Supplier simulator on / off |
| Energy & environment → bottom of Overview | Energy simulator: switch, inject, clear |
| Business & finance → bottom of Receivables & payables | Finance simulator: switch, inject “a customer does not pay an invoice” |
| Lab 15–22 pages → Teacher: inject / settings | Set up this lab's scenario per section III “Preparation” of the lab guide |
| Lab 23 page → Teacher: whole class | Each group's and each person's scores |

## Students and scoring

- Online, students use WenQuest accounts; the local version signs in by name, and the name is the grade account.
- Automatic lab scores are in the class table in each lab page's “Teacher” block; reports are graded in the learning platform course.
- Engineering task sheets under “My tasks” are reviewed by the teacher.
- Company members: the teacher can authorize certain accounts to use given roles in production mode.
