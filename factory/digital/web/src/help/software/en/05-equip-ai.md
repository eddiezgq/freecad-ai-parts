# Equipment, hidden problems and AI patrol

## Equipment

Maintenance, failure modes, power, hazards and checklists of the 21 machines feed [Maintenance](/maint), [Energy](/energy) and [EHS](/ehs) (all example values).
Data-hall equipment (build servers, test farms, benches, soak platform, cloud hosts…) runs unattended; team desks need people.
Main hazards in the hall: **live parts** and **gas fire suppression** (leave as soon as the alarm sounds); at the desks, sitting and eye strain. A data-hall patrol robot swaps disks and delivers spares.

## Hidden problems the teacher can inject

Five problems can be injected in the Scenario director (students cannot see which; they trace it from the data):

| Problem | Symptom | Real fix |
|---|---|---|
| Build server 3 clock drift | Only releases built on bld-3 have extra intermittent failures | Fix clock sync, rerun failures on another machine, remove tests that depend on the local clock |
| A commit introduces a memory leak | Every later soak-tested release shows a rising memory floor | Compare releases to find the commit, revert it, add a soak regression test |
| HIL bench 2 cache misconfigured | Only hil-2 measures high interrupt latency | Reflash the standard configuration, verify with a signal source, retest |
| Zone A host 2 saturated by a "noisy neighbour" | Only subscriptions on cl-a2 are slow | Move the tenant, add limits, re-accept affected subscriptions |
| Bad configuration pushed to zone A | Subscriptions on both zone A hosts show high errors | Roll back, add canary checks to configuration releases |

Plausible-looking but wrong measures: rerun failed tests and ship, add hosts / build servers, relax gate and acceptance limits, retrain everyone.

## AI patrol (command-center rules, software company only)

| No. | Rule | Hint |
|---|---|---|
| SW1 | Low pass rate (by build server) | Fails only on one machine: check its clock and disk |
| SW2 | Soak memory keeps rising | Look at the floor after collection; find the first bad release |
| SW3 | High interrupt latency (by bench) | Same release fine on another bench: check the bench configuration |
| SW4 | High service latency (by host) | Check other tenants on the host |
| SW5 | High service errors (by zone) | Check recent configuration pushed to that zone |
