# Shop floor: dispatch, start, watching the shop

> Once released, a work order is dispatched to machines operation by operation; operators start the work, parts flow between machines, AGVs carry them, and everything is published on the unified data bus.

## How a work order moves through the shop

Parts queue in front of the slowest operation — that is the bottleneck. Try adding a machine to it:

```anim
name: workorder
```

```video
name: teach-dispatch
caption: Choose a station, start work
```

## Try it now: what happens when the bottleneck stops

The grinder is one of this line's bottlenecks. Press this and it really stops for 2 hours (factory time); watch the machine states below, then look at the queue in front of it in the 3D shop.

```try
action: stop-grinder
label: Stop the grinder for 2 hours
note: Within seconds GRD-01 turns red; the Plant Insight Hub reports “Machine down”, and the causal chain links to the affected orders.
```

```live
kind: machines
```

```goto
tour: open-3d
label: Open the 3D shop and click a machine
```

## Your pick

```quiz
q: You are an operator and your station on the shop terminal has no “Start” button. The most likely reason?
options:
  - Your account lacks permission | wrong | Operators can start work; there is no button because no operation is dispatched here
  - Nothing is dispatched yet: the planner must first release the work order to the shop | right | Only machines with dispatched work have a “Start” button
  - The machine is broken | wrong | A machine that is down shows a red frame and “Reset”, not a missing start button
more: #Starting work on the shop terminal
```

```quiz
q: A machine shows “👤 Nobody can run it this shift”. Where do you handle it?
options:
  - Click “Reset” on the shop terminal | wrong | It is not a fault; reset does nothing
  - Change people under “People → Roster”, or look at the “Staffing gap” options in the command center | right | When the shop's “someone must be present” is on, a machine with nobody on the roster does not run that shift
  - Open a repair order in maintenance | wrong | The machine is fine; it is short of people
more: #Why the shop stops
```

```ask
q: Which machine has the longest queue right now?
```

:::查表

## Starting work on the shop terminal

“Shop floor” in the left sidebar opens the shop terminal (operator).

1. First choose your station. The dot color is the machine's current state.
2. Under “Operations dispatched to this station”, click “Start”.
3. When the machine stops, handle it and click “Done, reset”.

Only machines with dispatched work have a “Start” button; the planner must release the work order first. Clicked start but the part does not move? The previous operation has not delivered the part yet, or nobody has started the previous operation.

```goto
tour: operator-start
label: Help me start work on the shop terminal
```

## Why the shop stops

| What you see | Cause | What to do |
| --- | --- | --- |
| Red, down | Fault. In teaching mode machines fail randomly by failure rate (the teacher can turn this off) | Finish and verify the repair order, then reset; see “Maintenance” |
| 🔒 Locked out | A hazard fix, PM or repair is in progress | When done, someone else verifies and unlocks; reset does nothing |
| 👤 Nobody can run it this shift | Nobody on the roster for this machine this shift (when the shop's “someone must be present” is on) | Change people under “People → Roster”, or see “Staffing gap” in the command center |
| Run by an apprentice | Only an apprentice is on duty | Only 60% speed; delivery may be affected |
| Gray, waiting for material | Shortage or rejected incoming material | See “Purchasing & incoming” |

Each of these becomes an anomaly in the Plant Insight Hub, with options you can simulate.

## 3D shop

Machine positions, sizes, states and the AGVs are all live. Click a machine to see the work order it is on; the CNC lathe and keyway miller can also replay toolpaths.

```video
name: teach-3d
caption: 3D shop
```

## Unified data bus and virtual PLC

Every machine's state, events and measurements are messages on the bus, with topics like `wq/gearbox/machining/<machine ID>/status`.
The [unified data bus](/bus) page shows the live message stream. The press-fit station and sorting line are controlled by the [virtual PLC](/plc), and you can download programs you wrote.
