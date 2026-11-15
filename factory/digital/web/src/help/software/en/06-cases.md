# Design cases: real-time scheduling, cloud storage, cloud capacity

> Left menu “Design cases”: three cases of the software company, from the design brief to its “production line” (release pipeline, subscription acceptance). Case A's real-time system runs on the PCB plant's joint drive board; cases B and C build the cloud in the computer plant's 20-rack hall (its case C). All numbers come from the scripts; these are example designs.

| Case | What | Worth a look |
|---|---|---|
| A Real-time task scheduling on the joint drive board | Six tasks on one MCU: 20 kHz current loop, speed loop, EtherCAT, position loop, diagnostics, logging | Utilization above the Liu–Layland bound can still be schedulable (exact response-time analysis); the draft current loop is blocked on a shared buffer and misses 25 μs, fixed with a lock-free double buffer; a 1,000-hyperperiod simulation never exceeds the analysis; **the worst interrupt latency measured at the release gate (≤ 8 μs) is the number used in the analysis** |
| B Cloud object storage: replicas or erasure coding | 64 nodes, 768 × 16 TB disks: capacity, repair, nines, read latency | Replicas alone do not fit; Markov-chain durability checked by Monte Carlo; erasure coding has a worse tail for small objects but is faster for large ones; hot data on replicas (with hedged reads), warm/cold on RS(6,3), a whole rack can fail |
| C Capacity planning for a 20-rack cloud | Subscriptions sellable in three years, gateways, tenant availability, payback | Overcommit without memory is useless (memory runs out first); 1.5× overcommit with 768 GB chosen; bin-packing simulation for fragmentation; Erlang C matches the queue simulation; average availability looks great but SLA misses come from bad months, so 99.9 % is offered only to dual-zone tenants; a noisy neighbour is caught at acceptance and fixed by isolating the tenant |

Each case has eight steps: brief, concept, calculation, simulation, 3D & drawings, process, manufacturing, review. Software has no 3D parts, so the drawing step shows task architecture, placement rules and hall zoning; the manufacturing step is the [Releases & services](/software-ops) line.

## Links to the plant

- Case A step 7 runs 20 real-time OS builds; the worst interrupt latency at the release gate is about 6.7 μs at most, and the current loop still has margin with it.
- Case B step 7 runs 10 platform builds and accepts 24 cloud subscriptions.
- Case C step 7 injects a noisy neighbour on zone A host 2: all 6 subscriptions fail acceptance; after the “isolate tenant” action they pass — the same entry teachers use to inject problems and students use to issue actions in [Quality](/work/quality).

```quiz
q: In case C, why does 1.5× CPU overcommit sell nothing extra with 512 GB of memory?
options:
  - The CPU is too busy after overcommit | wrong | With 512 GB the CPU never gets sold out, so it cannot get busy
  - Each vCPU needs 4 GB, so 512 GB covers only about 120 vCPU and memory runs out first | right | Sellable capacity is set by whichever runs out first, CPU or memory
  - Subscriptions are sold by memory only | wrong | They are sold by vCPU, but each vCPU needs memory
```
