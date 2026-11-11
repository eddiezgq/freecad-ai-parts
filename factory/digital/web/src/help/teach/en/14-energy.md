# Energy and environment

> Machine state → power → meter readings → energy per part → electricity cost (peak/flat/valley) → carbon. Machines left on with no work and furnaces loaded at the most expensive hours all show up here, and are reported in the Plant Insight Hub.

## Where a day's electricity goes

Gray is on with no work (idle), orange is the heat-treat furnace. Tick the two switches and see how electricity, cost and carbon change:

```anim
name: energy-day
```

```video
name: teach-energy
caption: Idle alarm → auto standby; furnace at peak → peak shifting
```

## Try it now: leave the band saw on after shift

Press it and the band saw stays on with no work, idling 4 hours (factory time). After a few readings the idle share below rises, and the Plant Insight Hub reports “High idle energy”.

```try
action: idle-saw
label: Leave the band saw on after shift
note: One reading every 15 minutes (factory time); at low speed it takes a while.
```

```live
kind: domain
domain: energy
```

```goto
tour: energy-tour
label: Help me find the machine with the most idle energy
```

## Your pick

```quiz
q: Heat treatment is moved from 9:00 (peak) to after 11:00. What is saved?
options:
  - Electricity, money and carbon | wrong | The furnace burns the same electricity, and the carbon is the same
  - Only money: the electricity moved to a cheaper time; energy and carbon unchanged | right | Peak shifting saves money; standby saves electricity, and money and carbon with it
  - Nothing | wrong | Peak prices are higher; moving to flat hours lowers the bill
more: #A few terms
```

```quiz
q: The band saw's idle energy share over the last 12 hours is 45%. Which of the hub's options is recommended?
options:
  - Do nothing | wrong | That is the baseline
  - The cheapest option that keeps the due date, e.g. “auto standby after 10 minutes idle” | right | Idle options use the shop what-if to compute the next 24 hours' energy, cost, carbon and delivery
  - Just switch the band saw off | wrong | It must be on again when the next work order comes; from standby it only needs a few minutes of warm-up
more: #Options
```

```ask
q: How much electricity was used yesterday? What share was at peak?
```

:::查表

## What this page has

Left sidebar “Support → Energy & environment”. Six numbers at the top: electricity, cost (peak / flat / valley kWh), peak share, idle energy, carbon, and this month's demand / contract demand.

| Tab | What it does |
| --- | --- |
| Overview | Main shop meter curve (red peak, yellow flat, blue valley, dashed contract demand); energy bars per machine, gray is idle; energy-saving settings in use |
| Meters | Choose an electricity meter, flow meter or environment monitor to see its curve |
| Energy per part | Run energy per part of each machine vs baseline; idle over the last 12 hours; compressor and peak hours |
| Carbon & environment | Carbon this month, carbon footprint per product, oil mist and noise, parameters (prices, emission factor, contract demand, limits) |

The data lives in the platform's own tables, not in ERPNext. In teaching mode the simulated shop sends one reading every 15 minutes (factory time), the same interval as real meter reading.

## A few terms

| Term | Meaning |
| --- | --- |
| Idle | Machine on, no work |
| Standby | With “auto standby after N minutes idle” set, it switches to standby itself when idle long enough; restarting needs a few minutes of warm-up |
| Off | Machines with nobody on a shift are switched off by the people leaving; if forgotten they idle the whole time |
| Peak shifting | No new furnace loads at peak; parts wait and go in together after the peak |
| Carbon footprint | Electricity × grid emission factor |

Peak shifting saves **money** (the electricity moves to another time), energy and carbon unchanged; standby saves **electricity**, and money and carbon with it.

## Who does what

| Role | Can do |
| --- | --- |
| All roles | View |
| Planner, maintenance technician, plant manager | Start energy-saving settings and peak shifting |
| Plant manager | Change prices, emission factor, contract demand, environmental limits; approve energy-saving settings and peak shifting |

## What the Plant Insight Hub reports

| Rule | When it reports |
| --- | --- |
| N1 Jump in energy per part | A machine's energy per part over its last few parts is more than 25% above baseline (usually degrading) |
| N2 High idle energy | A machine's idle energy over the last 12 hours is more than 30% of its total; heat-treat furnace holding excluded |
| N3 High peak-hour share | Peak-hour energy over the last 24 hours is more than 30% |
| N4 High compressed air base load | The compressor draws noticeably more than needed, possibly a leak |
| N5 Demand near contract demand | This month's maximum 15-minute mean power is above 90% of contract demand |
| N6 Shop environment over limit | Oil mist or noise over the last hour averages above the limit |

## Options

| Anomaly | Options |
| --- | --- |
| N2 idle | Do nothing (baseline) / this machine auto standby after 10 minutes idle / 30 minutes / all machining machines 10 minutes |
| N3 peak, N5 demand | Heat-treat peak shifting / do nothing |
| N1 jump in energy per part | Open a repair work order / do nothing for now |
| N4 leak, N6 environment over limit | Fix work order / do nothing for now |

Idle and peak-shifting options use the shop what-if to compute the next 24 hours' energy, cost, carbon and delivery. The recommendation is the cheapest option that keeps the due date.

## Teaching mode

- Energy simulator (“Teacher: energy simulator” at the bottom of “Overview”): produces machines left on after shift, air leaks, machine degradation and oil mist collector failures; the teacher can inject or clear them.
- **Lab 21** Energy: idle, peak shifting and carbon per part: “Labs & tasks → Lab 21”.
- **Two-week scenario** scene 7: the band saw idles and heat treatment is loaded at peak hours.
