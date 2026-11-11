# Business and finance

> Bringing money into the factory: order → invoice → payment received, purchase → supplier invoice → payment; every domain's costs add up to each order's margin, and every domain's metrics hang on the business objectives.

## How much did an order make

Digital Factory Practice lab 10-1: subtract material, labor, electricity, scrap, expediting and warranty from revenue item by item, and what remains is the margin. Try another order:

```lab
id: waterfall
preset: robot
height: 600
```

```video
name: teach-finance
caption: Receivable overdue → reminder → cash
```

## Try it now: make an invoice overdue

Press it and the latest unpaid receivable invoice becomes 15 days overdue, and the customer does not pay unless reminded. Watch “of which overdue” below grow, and the Plant Insight Hub report “Receivable overdue”.

```try
action: overdue-invoice
label: Make an invoice 15 days overdue
note: If there is no unpaid receivable invoice, it asks you to try again after an order is finished and invoiced.
```

```live
kind: domain
domain: finance
```

## Play with it: remind or not, how much cash differs

Lab 10-2: no reminder, a reminder, or stopping shipments — see the lowest cash point over the next 8 weeks:

```lab
id: cashflow
preset: dun
height: 600
```

## Your pick

```quiz
q: An invoice is 20 days overdue and cash is enough for the next two weeks. The hub offers “do nothing / send a reminder / credit hold”. How do you think about it?
options:
  - Cash is enough, leave it | wrong | The longer it waits the harder it is to collect, and DSO gets worse
  - Look at the what-if: how many days until payment for each option and the week with the lowest cash, then decide | right | After a reminder customers usually pay within 3 days; a credit hold affects later orders
  - Credit hold at once | wrong | The harshest move; compare the costs first
more: #Options
```

```quiz
q: The order margin computed here differs from what accounting computes in ERPNext. Which is wrong?
options:
  - This one is wrong | wrong | They use different bases; neither is wrong
  - Neither: this is the management basis, counting labor, electricity, scrap, action costs and warranty | right | It shows what an order really made and in which scene the money went
  - ERPNext is wrong | wrong | The accounting basis follows accounting standards
more: #Teaching mode
```

```ask
q: How much receivable is overdue now? Is cash enough?
```

:::查表

## What this page has

Left sidebar “Order to cash → Business & finance” (used most by the plant manager). Five numbers at the top: gross margin (completed orders), receivables and overdue, DSO, cash, budget used this month.

| Tab | What it does |
| --- | --- |
| Objectives | Metric tree of seven objectives: on-time delivery, gross margin, first-pass yield, OEE, idle energy share, major hazards, DSO; green met, yellow slightly off, red off target |
| Order margin | Each completed order: revenue − material − labor − electricity − scrap − rush/overtime/subcontract/expedite − warranty; click “Breakdown” for each item's source |
| Receivables & payables | Receivables aging, customer credit, 8-week cash flow forecast, payables |
| Budget | Seven cost centers against monthly budget; the vertical line is month progress |
| Production & cost | OEE per machine, deliveries this month, work order cost breakdown (formerly a separate page) |

Invoices and payments follow ERPNext. In teaching mode an order is invoiced automatically when all its work orders are done. Production mode only drafts proposals, which accounting confirms.

```goto
tour: finance-tour
label: Show me business & finance
```

```goto
tour: finance-production
label: Show me production & cost
```

## Who does what

| Role | Can do |
| --- | --- |
| All roles | View |
| Plant manager | Change objectives and budgets; approve reminders, credit holds, budget changes and payments (sales can also approve reminders) |
| Planner, sales, plant manager | Start reminders, credit holds, payments, budget changes |

## What the Plant Insight Hub reports

| Rule | When it reports |
| --- | --- |
| F1 Work order cost variance over limit | Actual work order cost deviates too far from standard |
| F2 Receivable overdue | An invoice is past due and unpaid |
| F3 Customer over credit limit | Receivables + orders in progress not invoiced > credit limit |
| F4 Not enough cash to pay bills due | Cash forecast drops below 0 within two weeks |
| F5 Order margin below target | A completed order's margin is more than 5 percentage points below target |
| F6 Budget overrun | A cost center's actual this month > budget × progress × 1.1 |
| F7 Business metric off target | A metric is red now and was red on at least 5 of the last 7 days |

**The money causal chain**: for overdue receivables and low margin the chain is invoice → order → action costs charged to the order → which anomaly the action came from, tracing across domains back to the source.

## Options

| Anomaly | Options |
| --- | --- |
| F2 Receivable overdue | Do nothing / send a reminder / credit hold; each gives the expected days to payment and the week with the lowest cash |
| F3 Over credit limit | Do nothing / credit hold / temporary limit increase |
| F4 Not enough cash | Do nothing / defer payments / speed up collection |
| F6 Budget overrun | Do nothing / adjust budget |
| F5, F7 | Breakdown and where to look; no what-if |

## Teaching mode

- **Billing day**: 1 day = 2 real minutes, so 30-day terms take about an hour.
- Finance simulator (at the bottom of “Receivables & payables”, switched by the teacher): customers pay late by their own habits and usually pay within 3 days of a reminder; the teacher can inject “a customer does not pay an invoice”.
- The margin here is the management basis (labor, electricity, scrap, action costs and warranty all counted), different from ERPNext's accounting basis.
- **Lab 22** Business: order margin, receivables and cash: “Labs & tasks → Lab 22”.
- **Two-week scenario** scene 8: delivery and invoicing, overdue receivable; the review looks at this order's margin.
