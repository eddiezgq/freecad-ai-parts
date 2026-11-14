# Release pipeline

| Step | Where | What |
|---|---|---|
| Merge & review | Team desks (three teams) | Code review, merge to main |
| Build & unit test | Build servers bld-1 … bld-4 | Compile, run thousands of unit tests |
| Integration test | Test farms | Modules tested together |
| Hardware-in-the-loop test | Benches hil-1 … hil-3 | RTOS and robot software on real joint drive boards and industrial PCs; latency of 20,000 interrupts |
| Soak test | Soak platform | OS, cloud and digital factory under full load for 4–12 h, memory logged every 10 min |
| Security scan | Security scanner | Known vulnerabilities, licenses, static analysis |
| Release gate | Release server | Pass rate ≥ 99.5 %, interrupt latency within limit, memory growth ≤ 5 MB/h — or no release |
| Sign & publish | Release server | Signed with the hardware security module, stored in the artifact repository |

## The "Release pipeline & service monitoring" page (pipeline tab)

Open [Release pipeline & service monitoring](/software-ops); the list shows recent releases, filterable by product and build server; above it: **pass rate by build server** and **interrupt-latency margin by bench**.
Click a release to see:

- the pipeline steps (green = passed, amber = failed tests but within the gate, red = gate failed);
- test count, failures, and how many of them are time-related (timeouts, timers, certificate validity);
- RTOS / robot software: **interrupt latency distribution** (log scale);
- OS / cloud / digital factory: **soak memory curve**, red dots = floor after each garbage collection.

## Three things to recognise

| Symptom | Means | Don't |
|---|---|---|
| Only builds on one server fail intermittently and pass when rerun elsewhere | An environment problem on that machine (clock, disk, cache) | "Just rerun and ship" — the flaky failure is hidden and shows up at the customer |
| The memory floor keeps rising | A memory leak: find the first bad release and revert that commit | Add memory, restart nightly |
| Only one bench measures high interrupt latency | That bench's board configuration is wrong, not the kernel | Tune the scheduler to "fix" the test result |
