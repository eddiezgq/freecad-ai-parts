# People and shifts

> Machines need people to run them. When a key operator is on leave, their machine stops that shift; if that machine is the bottleneck, the whole line and the orders suffer.

## What happens when one person is missing

Leave → the grinder's cell turns red → move someone in (another cell turns red) → switch to overtime cover:

```anim
name: shift
```

```video
name: teach-people
caption: Leave → short-staffed → shift swap or overtime
```

## Hands on: draft a shift swap

Under “Roster” click a cell, choose a person, click “Create action”. Once created, this step ticks itself (shift lead, planner or plant manager role). The action takes effect only after the shift lead or plant manager approves it.

```goto
tour: people-tour
label: Show me the roster and draft a swap
```

```live
kind: domain
domain: people
```

## Your pick

```quiz
q: The grinder's skilled operator on the early shift is on leave. Moving Chen Gang from lathe 2 leaves lathe 2's early shift empty; Zheng Tao from the late shift can cover on overtime. Which is better?
options:
  - Move Chen Gang: no overtime pay | wrong | Lathe 2 is now short; the what-if counts that cell too
  - Look at the what-if: overtime cover leaves other cells alone and costs overtime pay; choose it when delivery is better | right | The recommendation is the best delivery at the least cost; between equals, not the apprentice
  - Let an apprentice run the grinder | wrong | An apprentice runs at only 60% speed; the grinder is the bottleneck, so delivery suffers
more: #Options (staffing gap)
```

```quiz
q: In the skills matrix only one person is “proficient” in the grinder column. What kind of problem is this?
options:
  - Not a problem, he comes every day | wrong | The grinder stops as soon as he is on leave
  - Single-point dependency (H1): schedule skills training so a second person can run it | right | The options are “Schedule skills training” or “Do nothing for now”
  - Staffing gap (H2) | wrong | A gap means a shift really has nobody; a single-point dependency means only one person can run it
more: #What the Plant Insight Hub reports
```

```ask
q: Which machines can only one person run?
```

:::查表

## What this page has

Left sidebar “Support → People” (used most by shift leads). Five numbers at the top: attendance this shift, roster gaps within 24 hours, single-point machines, overtime hours this week, and whether the shop's “someone must be present” is on.

| Tab | What it does |
| --- | --- |
| Organization & employees | Employees, departments, posts, shifts, machines they can run (all names are fictional) |
| Skills matrix | Employee × machine: learning (apprentice, 60% speed), proficient (runs alone), master (can also coach apprentices); red columns have only one person who can run them |
| Roster | Early and late shifts; each cell is who runs this machine; red: nobody can run it, yellow: an apprentice with coaching. Click a cell to change the person |
| Attendance & overtime | Who is on duty this shift; record leave, lateness and absence (no reasons recorded); each person's overtime this week |

Employees, departments and posts follow ERPNext; skills, rosters and attendance are on the platform. From the roster the platform works out whether each machine has someone who can run it on each shift, and sends that to the simulated shop.

## Who does what

| Role | Can do |
| --- | --- |
| All roles | View the roster and skills matrix |
| Shift lead | Record attendance, pass assessments; start and approve shift swaps |
| Planner, plant manager | Start shift swaps, overtime cover, skills training |
| Plant manager | Approve overtime cover and skills training (they cost money) |

Details of leave and lateness are visible only to the plant manager, shift leads and teachers; others see only “on duty / not on duty”.

## What the Plant Insight Hub reports

| Rule | When it reports |
| --- | --- |
| H1 Key qualification single-point dependency | A machine has only one person at proficient or above |
| H2 Staffing gap | Within the next 24 hours, a staffed machine has nobody able to run it on some shift (critical for the bottleneck) |
| H3 Skill qualification expiring | Notice within 30 days of expiry, warning when expired |
| H4 Overtime over limit | Someone's overtime this week exceeds 12 hours |
| H5 Abnormal attendance | A team's absence rate over the last 7 days exceeds 10% |

## Options (staffing gap)

| Option | What it does |
| --- | --- |
| A Do nothing (baseline) | This machine stays stopped this shift |
| B Move someone in | Move a proficient worker in; their original post is empty that day, and the what-if counts that too |
| C Apprentice with coaching | An apprentice runs it with the shift lead present, at 60% speed |
| D Overtime cover | A proficient worker from the other shift covers on overtime, original posts unchanged; overtime pay |

The recommendation is the best delivery at the least cost; between equals, not the apprentice. For single-point dependency (H1) the options are “Schedule skills training” or “Do nothing for now”.

Another cell turned red after moving someone? That is the cost of moving people. Move another, or switch to overtime cover.

## Teaching mode

- **Someone must be present in the shop**: the teacher switches it at the top of this page. When off, machines need no people, as before; it turns off when the lab 7 scenario is reloaded.
- At the start of each shift the simulated shift lead randomly records a few people on leave or late; coaching passes its assessment automatically when due.
- **Lab 19** Shifts and skills: decisions when short-staffed: “Labs & tasks → Lab 19”. On the lab page the teacher puts someone on leave for the next shift.
- **Two-week scenario** scene 4: the grinder's skilled operator is on leave.
