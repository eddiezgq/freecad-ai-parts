# Labs and tasks

> One entry in the left sidebar, “Teaching → Labs & tasks”: a card each for labs 7, 15–23 and 33. In every lab you do it yourself first, then compare with the hub's suggestion; the platform scores part automatically from facts, and the teacher grades the report.

## Decide yourself first, then see the suggestion

Labs use compare mode: until you submit your choice, the hub shows no suggestion and the AI only gives hints; after submitting you compare. The AI and the hub only draft; people decide:

```anim
name: ai-draft
```

```video
name: teach-labs
caption: Labs & tasks: choose a lab, do the tasks, see the score
```

## Hands on: open lab 18

Click the “Lab 18” card; entering the lab page ticks this step. Then follow “Show me a lab page” to learn the lab guide, score bar and tasks.

```goto
tour: labs-tour
label: Help me open Labs & tasks
```

```goto
tour: lab-page
label: Show me a lab page
```

```live
kind: kpi
```

## Your pick

```quiz
q: Lab 18 task 3 asks you to choose a PM option. The right panel of the command center shows only the what-if numbers, no “Suggestion”. Why?
options:
  - The system is broken | wrong | This is compare mode
  - Compare mode: no suggestion until you submit your own choice | right | After submitting you see the hub's suggestion and compare it with yours
  - Your role lacks permission | wrong | It has nothing to do with roles; even the teacher compares after submitting
more: #Compare mode
```

```quiz
q: Where does a lab's automatic platform score come from?
options:
  - How long you stay on the lab page | wrong | Only facts count
  - Only facts in the platform: bus records, the answers you submit, the actions you started that were executed | right | Nothing done means no score; guessing does not work
  - The teacher scores it | wrong | The teacher grades the 40 points of the report
more: #Scoring
```

```ask
q: Where does lab 18's first task start?
```

:::查表

## Entry

Labs appear only in teaching mode. Switch the top bar to “Teaching mode”, then left sidebar “Teaching → Labs & tasks”.

Each card shows: lab number, domain, title, class hours, number of tasks, my score (automatic) and report score, and which task I am on.
The colored bar on the left: gray not started, yellow partly done, green all done. “Lab guide” on the card downloads directly.

## Which labs there are

| Lab | Content | Domain | Where |
| --- | --- | --- | --- |
| Lab 7 | Digital factory closed loop: dashboard, order and MRP, design release, shop floor, inspection, cost | Order to delivery | [Lab 7](/teach) |
| Lab 15 | Root cause, what-if and decisions for shop anomalies | Plant Insight Hub | [Lab 15](/lab15) |
| Lab 16 | Trace, recall and service decisions for customer complaints | Customers & service | [Lab 16](/lab16) |
| Lab 17 | Identifying, assessing and stop decisions for safety hazards | Safety & environment | [Lab 17](/lab17) |
| Lab 18 | Maintenance strategy: deciding when to do PM | Maintenance | [Lab 18](/lab18) |
| Lab 19 | Shifts and skills: decisions when short-staffed | People | [Lab 19](/lab19) |
| Lab 20 | Supply chain: rejected incoming material and supplier choice | Purchasing & incoming | [Lab 20](/lab20) |
| Lab 21 | Energy: idle, peak shifting and carbon per part | Energy & environment | [Lab 21](/lab21) |
| Lab 22 | Business: order margin, receivables and cash | Business & finance | [Lab 22](/lab22) |
| Lab 23 | Two-week scenario: plant-wide decisions on a rush order (two-week course project, groups of 4–6) | All seven domains | [Lab 23](/lab23) |
| Lab 33 | One engineer-to-order job from inquiry to payment (estimate, quotation, design, schedule, shop, quality, milestone billing) | Orders & planning | [Lab 33](/lab33) |

There are also labs 8–14 done on the computation desks (strength and fatigue, joint torque, CNC programming, heat balance and lightweighting, digital design of a shaft, digital twin, flow); see the computation desk table in “From design to factory”.

## What a lab page has

- At the top: title, “Lab guide” and “Report template” downloads;
- Score bar: my score and the state of compare mode; links next to it (e.g. “Open the anomaly you chose”) go straight to that anomaly in the command center;
- A block only the teacher sees: inject problems or set up the scenario, and the class score table;
- Below are tasks 1–5, each with instructions, hints and a form to fill; scores and feedback come right after submitting.

## Compare mode

Labs 15–23 all use compare mode:

1. First trace the cause, run the what-if, choose an option and write your reasons yourself, then submit;
2. Before submitting, the command center's right panel shows no “Suggestion” or reasons (what-if numbers are visible as usual), and the AI only gives hints;
3. After submitting, you see the hub's suggestion and compare it with your choice.

Lab 23 counts by group: while your group has scenes without a decision, those anomalies show no suggestion in the command center.

Teachers are not limited by compare mode. In the local version everyone who signs in has teacher permissions, so compare mode does not work there (see “How this course uses the digital factory”).

## Scoring

| Lab | Automatic platform score | Lab report |
| --- | --- | --- |
| Lab 7 | 100 points (6 tasks) | — |
| Labs 15–22 | 60 points (5 tasks each) | 40 points, handed in to this lecture's assignment in the course, graded by the teacher |
| Lab 23 | 60 points (4 tasks, by group) | 40 points, group report |

Automatic scoring counts only facts in the platform: records on the unified data bus, the answers you submit, and the actions you started that were executed. Nothing done means no score; guessing does not work.

Automatic scores do not go into the learning platform gradebook yet. Attach a screenshot of your score on the lab page when handing in the report, and the teacher enters the grade from it.

## A few reminders

- Labs need different roles: e.g. PM work orders need “Maintenance technician”, dispatch needs “Customer service”, rosters need “Shift lead”. Switch at the top right.
- Actions that cost money need the plant manager's approval — ask the teacher.
- Shop time runs faster than real time (speed multiple); suppliers and terms count in billing days: 1 day = 2 real minutes.
- In labs the AI factory assistant is a teaching assistant: it tells you where to find data and explains concepts, but does not give answers directly.
