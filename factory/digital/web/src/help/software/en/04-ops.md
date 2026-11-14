# Cloud operations and service monitoring

## Data hall

The cloud hall has 4 racks bought from the computer plant (16 servers each, like case C), in two **availability zones**: zone A cl-a1, cl-a2 and zone B cl-b1, cl-b2.
If one zone fails, the other carries on. The monitoring platform mon-1 records latency, errors and availability of every subscription; on-call 24×7.

## Provisioning and acceptance

Each cloud (or digital factory) subscription is provisioned on one host and then **accepted over 24 hours**:

| Metric | How | Limit |
|---|---|---|
| Latency p99 | Per minute, the time within which 99 % of requests return; 24 h average | ≤ 50 ms |
| Error rate | Share of failed requests; 24 h average | ≤ 0.1 % |
| Availability | Share of good minutes (latency < 200 ms and errors < 1 %) | ≥ 99.9 % |

## The "Release pipeline & service monitoring" page (service tab)

In [Release pipeline & service monitoring](/software-ops) switch to "Service monitoring": filter by host; above the list: **latency by host** and **errors by zone**; click a subscription for its 24 h latency and error curves.

| Symptom | Means | Real fix |
|---|---|---|
| Only subscriptions on one host are slow, with latency spikes | Another tenant on the same host saturates CPU or disk (a "noisy neighbour") | Move that tenant, add resource limits |
| Both hosts in one zone show higher errors | A configuration pushed to that zone is wrong | Roll it back; push configuration to one host first (canary), check errors, then the whole zone |

Adding hosts fixes neither: the noisy neighbour is still on that host, the bad configuration still in that zone.
