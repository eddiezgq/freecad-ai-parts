# Customers and service

> From customer to follow-up in one thread: lead → opportunity → quotation → contract → order → delivery → complaint → trace → service → follow-up. Complaints become anomalies in the Plant Insight Hub, and dispatch options are estimated from the engineers' roster.

## How far a complaint traces

A complained-about unit has a serial number, so it can be traced to factory data: which customers' units got shafts ground by the same wheel. Choose an option to see which units get a visit:

```anim
name: recall
```

```video
name: teach-service
caption: Complaint → trace → recall scope → dispatch decision
```

## Hands on: log a complaint

On the “Complaints” tab enter the serial number, symptom and severity, and click “Register”. Once logged, this step ticks itself (use the “Customer service” role); within 20 seconds the Plant Insight Hub opens an anomaly.

```goto
tour: service-tour
label: Help me log a complaint
```

```live
kind: domain
domain: service
```

## Your pick

```quiz
q: A port customer's reducer makes noise. The trace finds shafts ground by the same wheel in 8 more units, 3 of them with low health. Which option will the hub recommend?
options:
  - Option A: fix only the complained unit | wrong | Cheap, but it misses the high-risk units in the search scope
  - Option B: fix this one + inspect the high-risk units | right | The recommendation is “the cheapest that misses no high-risk unit”
  - Option C: visit all 8 units | wrong | It misses nothing either, but costs more than B; healthy units need no hurry
more: #Options (dispatch)
```

```quiz
q: A complaint was logged 3 hours ago and nobody has contacted the customer; the contract response time is 2 hours. What happens?
options:
  - Nothing | wrong | The response time is a contract term, and the hub watches it
  - The Plant Insight Hub reports “complaint response overdue” (C3) | right | It reports when the customer has not been contacted within the contract response time
  - A penalty is deducted automatically | wrong | Penalties are for late orders and are used in the what-if and review
more: #Where contract terms are used
```

```ask
q: What has been going on with the port customer recently?
```

:::查表

## What this page has

Left sidebar “Order to cash → Customers & service”. Five numbers at the top: satisfaction (last 30 days), open complaints (average response hours), service visits pending (first-time fix rate), warranty cost, pipeline value (won this month).

| Tab | What it does |
| --- | --- |
| Sales pipeline | Add lead → convert to opportunity → quote → sign contract (three terms: penalty, response time, warranty) → convert to order |
| Complaints | Log a complaint: equipment serial number, symptom, severity, channel, contact; also opens an Issue in ERPNext |
| Service & roster | Service engineers' roster for the next 14 days, service jobs, completion |
| Follow-ups & satisfaction | Follow-up scores after completion (1–5) |
| Customer 360 | One customer's contracts, orders, field units, complaints, service jobs and satisfaction on one page |

Leads, opportunities, quotations, contracts and service jobs are written to ERPNext; complaints, dispatch rosters and follow-ups are done on the platform.

## Who does what

| Role | Can do |
| --- | --- |
| All roles | View |
| Customer service | Log complaints, “Customer contacted”, dispatch, complete, follow up; approve customer notices |
| Sales (production mode), plant manager | Sales pipeline, convert to order; can also do customer service's work |
| Plant manager | Approve dispatches and spare-part issues that cost money |

## Where contract terms are used

- **Late penalty**: the late penalty of an order in the what-if and review is computed from the customer's contract.
- **Response time**: if nobody contacts the customer within it, “complaint response overdue” is reported.
- **Warranty**: service cost is split into “paid by the factory under warranty” and “charged to the customer”.

## What the Plant Insight Hub reports

| Rule | When it reports |
| --- | --- |
| C1 Customer complaint | Every open complaint is an anomaly; urgent ones, or with a contract penalty, are critical |
| C2 Satisfaction falling | A customer's average over the last 3 follow-ups is below 3.5 |
| C3 Complaint response overdue | The customer has not been contacted within the contract response time |
| C4 Several complaints in one batch | Output shafts of two or more complained units come from the same wheel or work order |
| C5 Quotation expiring | A quotation expires within 3 days |
| R3 Delay triggers a late penalty | An order may be late and the contract has a penalty |

**Trace**: for complaints with a serial number, the causal chain traces all the way to factory data: unit → factory assembly → output shaft → the wheel that ground it → other shafts ground by the same wheel → which units and customers they went into. That is the **search scope**.

## Options (dispatch)

| Option | What it does |
| --- | --- |
| A Fix only the faulty one | Visit only the complained unit |
| B Fix + inspect high-risk | Also the high-risk units in the search scope |
| C Check the whole batch | Visit and inspect everything in the search scope |

Each option is worked out: which engineers, how many days, how many spare parts, how much money (under warranty / charged to customer), how many customers, and whether any high-risk unit is missed.
The recommendation is “the cheapest that misses no high-risk unit”.

Adopting creates three kinds of action: **service dispatch** (ERPNext service order), **spare-part issue** (ERPNext stock issue), **customer notice** (only for B and C; recorded only, not sent, in teaching mode).

## Teaching mode

- Simulator: field units whose health worsens call in complaints; engineers finish on their scheduled days; follow-ups are scored automatically; a new lead comes in every so often.
- **Lab 16** Trace, recall and service decisions for customer complaints: “Labs & tasks → Lab 16”. On the lab page the teacher injects batch complaints.
- **Two-week scenario** scene 1 “Customer places a rush order” goes from this sales pipeline to the order.
