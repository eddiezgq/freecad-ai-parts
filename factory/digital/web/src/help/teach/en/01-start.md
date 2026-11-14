# Entering the factory

> Pick a name, a role and a mode — three steps into {{厂名}}; the left sidebar is grouped along the plant's value chain, and the top bar lets you change roles at any time.

## Whose hands does an order pass through

You are entering a factory that is running: orders, materials, machines, people and money are all connected. Watch how one order goes around:

```anim
name: flow
caption: From design to the Plant Insight Hub: who is responsible at each stop, and how the documents change
```

## Three steps into the factory

Enter your name (it is your grade account), choose a post, choose a mode. Teaching mode has labs and scoring, and the machines are simulated.

```video
name: teach-login
caption: Signing in, choosing a role, the two modes
```

## Take a look at the shop right now

This plant's machines right now; the color of each light is its state. Open the 3D shop and click a machine — once you do, this step ticks itself.

```live
kind: machines
```

```goto
tour: open-3d
label: Open the 3D shop and click a machine
```

## Your pick

```quiz
q: Lab 18 asks you to start a PM work order, and you are signed in as “Planner”. What do you do?
options:
  - Sign out and register a new account | wrong | No need. Your name is your grade account; a new account would split your scores
  - Change the “Role” dropdown in the top bar to “Maintenance technician” | right | The same name can change roles at any time; PM work orders are started by maintenance
  - Ask the teacher to do it for you | wrong | Starting it is your job; only actions that cost money need the plant manager's (teacher's) approval
more: #Roles
```

```quiz
q: Where do the machine states on the home page, 3D shop, Plant Insight Hub and ERPNext come from?
options:
  - Each page simulates its own | wrong | Then they would not match. They all look at the same data
  - The same message on the unified data bus | right | Every machine's start, stop and tool change is published on the bus, and every page reads it
  - The teacher enters them by hand | wrong | The shop is driven by the simulator; states are live
more: #A factory that is running
```

```ask
q: I am the planner. What do I do first today?
```

:::查表

## A factory that is running

Orders, materials, work orders, machines, inspection and cost are all moving; there are also seven domains: customers and service, purchasing, people, safety, maintenance, energy and finance.
The machines in the shop are driven by a simulator; every start, cut, tool change and stop of every machine is published on the “unified data bus”. The dashboard, 3D shop, Plant Insight Hub and ERPNext all see the same data.

```live
kind: plant
```

## Signing in

Open the address your teacher gives you in a browser (on your own computer it is `http://localhost:8100`).

| Where you come in | How to sign in |
| --- | --- |
| From a course on the WenQuest learning platform (online) | Click “Sign in with WenQuest account”; no separate registration |
| School lab or your own computer (local version) | Enter your name. Your name is your grade account; use the same name every time |

| Mode | What it is for | AI factory assistant |
| --- | --- | --- |
| Teaching mode | Labs, hints and scoring; machines are simulated; the teacher can inject problems | Only points the way, does not do it for you |
| Production mode | The plant's daily workbench, no labs or scoring; only for teachers and company members | Can draft documents for you; they take effect only after you confirm |

## Roles

One factory; each post sees its own workbench. Items in the left sidebar marked “Mine” are the pages your current role uses most. Change roles any time with the “Role” dropdown in the top bar.

The plant name on the left of the top bar is a dropdown too: pick another plant in the park (robot, PCB, software …) to open it (each plant has its own accounts, so sign in there the first time). The WenQuest logo at the top left goes to the WenQuest home page; this plant's home is the first sidebar item, “Home · Operations overview”.

| Role | Main page | What they do |
| --- | --- | --- |
| Planner | Orders & planning, Purchasing & incoming | Take orders, run MRP, release work orders; convert purchase orders; start actions from the what-if |
| Process engineer | Design & process | Change part designs and release new revisions; write process plans |
| Operator | Shop floor (shop terminal) | Click “Start” on dispatched operations; after handling a stop click “Done, reset” |
| Quality inspector | Quality | Read control charts; disposition nonconforming parts; open quality issues (8D); incoming inspection |
| Customer service | Customers & service | Log complaints, dispatch, follow up |
| Maintenance technician | Maintenance | PM, inspections, repairs, lockout |
| Shift lead | People | Rosters, attendance, shift swaps |
| Safety officer | Safety & environment | Hazards, work permits, training, verify and unlock |
| Plant manager | Business & finance | Teachers only. Approves actions that cost money; in teaching mode the teacher uses it to run scenarios |

Production mode also has the “Approver” and “Sales” posts.

## How the left sidebar is grouped

| Group | Contains |
| --- | --- |
| Overview | Home · operations overview, Plant Insight Hub, My tasks, AI factory assistant |
| Order to cash | Customers & service, Orders & planning, Purchasing & incoming, Shop floor, Quality, Business & finance |
| Support | Maintenance, People, Safety & environment, Energy & environment |
| Design & process | Design & process, Process plans & AI review, Design release & approval, Configurator, 3D shop |
| Teaching (teaching mode only) | Scenario director (teachers only), Labs & tasks |
| Resources | Part & robot library, Company members, Help |

Below that are “Engineering software” (ERPNext, simulation, CNC programming, digital twin, virtual PLC…) and the connection state of the “unified data bus”. Every page has “Help” at the top right, which opens the notes for that page.
