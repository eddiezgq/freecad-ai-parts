# Purchasing and incoming

> The life of material: material request → purchase order (choose a supplier) → arrival → incoming inspection → accepted into stock or rejected → which parts it went into → supplier rating. When a lot is rejected, assembly has to wait.

## What incoming inspection does

Lot after lot arrives; 5 pieces are sampled against the limits: accept into stock, or reject and quarantine. Try switching to a cheaper supplier:

```anim
name: inspect
```

```video
name: teach-supply
caption: Incoming inspection → rejected → return or switch supplier
```

## Hands on: inspect a lot

Under “Receipts & inspection” click “Inspect” on a lot, check each piece against the limits yourself, and judge pass or fail. Once a lot is judged, this step ticks itself (use the “Quality inspector” role).

```goto
tour: supply-inspect
label: Help me inspect a lot
```

```live
kind: domain
domain: supply
```

## Your pick

```quiz
q: 5 bearings are sampled from a lot; 4 pass completely and 1 has its bore 0.002 mm over the upper limit. How is the lot judged?
options:
  - Pass: only slightly over | wrong | Any item of any piece out of tolerance rejects the whole lot
  - Reject and quarantine; then choose return, rush order from another supplier or concession in the hub | right | Once rejected, the Plant Insight Hub reports W3 with options
  - Pick out that one piece and stock the rest | wrong | That is option D “concession, 100% inspection and sorting”, which needs approval; it is not decided at inspection
more: #Options (rejected incoming material)
```

```quiz
q: Supplier A is 8% cheaper than B, but its pass rate over the last 30 days is only 90% and it is often late. How do you compare them?
options:
  - Choose A, it is cheaper | wrong | Lateness and rejects both cost money: assembly waiting, returns, expediting
  - Compute the total cost of ownership: unit price + losses from lateness and rejects | right | With these counted, the cheap supplier is not necessarily cheaper; lab 20 task 5 asks you to compute it
  - Split evenly between the two | wrong | Work it out before splitting
more: #Options (rejected incoming material)
```

```ask
q: How are the suppliers' on-time and pass rates?
```

:::查表

## What this page has

Left sidebar “Order to cash → Purchasing & incoming”. Five numbers at the top: lots in transit, arrived awaiting inspection, rejected awaiting handling, on-time / pass rate over the last 30 days, and whether the supplier simulator is on.

| Tab | What it does |
| --- | --- |
| Purchase orders & in transit | Material requests without a purchase order: choose a supplier per row and click “Convert to purchase order”; the lot table shows each lot's state |
| Receipts & inspection | Click “Inspect” on a lot, look at the sample data, check each piece against the limits yourself, judge pass or fail |
| Lots | Enter a lot number or a part or unit serial number and click “Trace”: which parts this lot went into, and which units they were fitted in |
| Suppliers | Scorecards: price index, lead time, on-time rate, pass rate, in transit; default and alternative suppliers |

Purchase orders, receipts and incoming inspection records follow ERPNext. Each delivery is a lot, and the shop records which lot's material each part used.

## Who does what

| Role | Can do |
| --- | --- |
| All roles | View |
| Planner | Convert purchase orders, return, register arrivals |
| Quality inspector | Incoming inspection, judge suspect lots, return, concession |
| Plant manager | Approve purchase orders and developing alternative suppliers (cost money); approve concessions |

You cannot approve actions you started.

## What the Plant Insight Hub reports

| Rule | When it reports |
| --- | --- |
| W1 Shortage / below safety stock | Stock not enough for orders or safety stock |
| W2 Purchase order arriving late | Past the promised arrival date and not arrived |
| W3 Rejected incoming lot not handled | A lot judged rejected, not yet returned or accepted under concession |
| W4 Supplier on-time rate low | At least 3 lots in the last 30 days, on-time rate below 80% |
| W5 Supplier incoming pass rate low | At least 3 lots in the last 30 days, pass rate below 95% |
| W6 Single source | An item category has only one supplier in use |
| W7 Suspect lot already used in parts | A lot judged suspect has already gone into parts |

## Options (rejected incoming material)

| Option | What it does |
| --- | --- |
| A Do nothing (baseline) | This lot cannot be used; orders waiting for it keep waiting |
| B Return, wait for the original supplier to reship | No cost; reshipped within the original lead time |
| C Rush order with the alternative supplier | Markup, fast |
| D Concession, 100% inspection and sorting | One day of 100% inspection, usable parts stocked first; needs quality approval |

The what-if releases the waiting work orders on each option's arrival date and works out how many days late the order is. The recommendation is the cheapest option that keeps the due date.

**Total cost of ownership**: with lateness and rejects counted, a cheap supplier is not necessarily cheaper. Lab 20 task 5 asks you to compute it.

## Teaching mode

- Time is compressed: a supplier day = 2 real minutes (billing day).
- Supplier simulator (the teacher can switch it at the top): suppliers arrive late and sometimes send a bad lot. If nobody handles it, a simulated buyer and inspector do it for you (always after leaving you time to do it first).
- **Lab 20** Supply chain: rejected incoming material and supplier choice: “Labs & tasks → Lab 20”.
- **Two-week scenario** scenes 2 and 3: shortage, rejected incoming material.
