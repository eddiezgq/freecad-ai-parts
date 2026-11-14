# This company: WenQuest Digital Industrial Park · Software Company

> The ninth company in the park: **real-time OS, server / desktop OS, cloud platform, digital factory (industrial software) and robot software**.
> Software has no blanks or machine tools, but it still has a production line — the **release pipeline** — so everything in the digital factory applies under other names.

## Plant → software company

| In a plant | In the software company |
|---|---|
| Bill of materials | **Software bill of materials (SBOM)**: the open-source and commercial components used |
| Incoming inspection | Each open-source component is checked for its **license** (does GPL "spread"?) and **known vulnerabilities** (CVE) |
| Routing | **Release pipeline**: merge & review → build & unit test → integration test → hardware-in-the-loop / soak test → security scan → release gate → sign & publish |
| Work order | One build (one release) |
| Machines | Build servers, test farms, HIL benches, soak platform, cloud hosts |
| Final test | **Release gate**: no release unless pass rate, interrupt latency and memory growth are within limits |
| After-sales | **Service acceptance** of every cloud subscription (24 h latency, errors, availability), on-call, online updates |

## Products

| Product | Code | Example price | Notes |
|---|---|---|---|
| RTOS release | REL-RTOS | $15,000 | A build customised for one board (interrupt latency on HIL) |
| Server / desktop OS release | REL-OS | $20,000 | A distribution build (12 h soak test) |
| Cloud platform release | REL-CLOUD | $30,000 | Compute, storage, network, containers |
| Digital factory release | REL-MES | $12,000 | The software the park itself runs |
| Robot software release | REL-ROBOT | $15,000 | Motion control, vision |
| RTOS device license | LIC-RTOS | $3 / board | For the PCB plant's joint drive boards |
| OS license | LIC-OS | $25 / unit | For the computer plant's imaging station |
| Robot software license | LIC-ROBOT | $400 / robot | For the robot plant |
| Cloud subscription | SUB-CLOUD | $2,400 / 100 vCPU·month | 24 h acceptance after provisioning |
| Digital factory subscription | SUB-MES | $3,000 / plant·month | Same |

## The park chain

```
Computer plant ──WQ-RACK42 racks──→ Software company (cloud data hall)
Software company ──OS licenses──→ computer plant; ──robot licenses──→ robot plant; ──RTOS licenses──→ PCB plant
```

## Address

China https://software.factory.wenquestech.online , US https://software.factory.wenquestrobotics.com (sign in with your WenQuest account; data separate from the other plants).
In China the AI interface only uses registered models (such as DeepSeek).
