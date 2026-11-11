# Orders and planning (MRP)

> An order comes in: explode it through the BOM, subtract stock and in transit, and work out what to request and which work orders to create; it is written to ERPNext only after confirmation.

## How MRP is computed

Drag the order quantity and watch each row change with it:

```anim
name: mrp
```

```video
name: teach-order
caption: Take an order, run MRP, confirm, release
```

## Try it now: a rush order

Press it and the demo plant really receives a rush order of WQR-105 × 5 due in 5 days; the proposal is confirmed automatically and written to ERPNext (use the “Planner” role). Then look at it under “Orders & planning”.

```try
action: rush-order
label: Place a rush order
note: The order, work order and material request reach ERPNext within tens of seconds; “Orders & due dates” on the home page gains a row.
```

```live
kind: kpi
```

## Take one yourself

Fill in the order, click “Compute materials”, submit the proposal. When the MRP result appears and when the proposal is created, each gets a tick.

```goto
tour: planner-order
label: Help me take an order and run MRP
```

```goto
tour: planner-release
label: Help me release the work order to the shop
```

## Your pick

```quiz
q: After clicking “Compute materials”, what is in ERPNext?
options:
  - Sales order, work order and material request are all created | wrong | MRP is only a preview; nothing is written
  - Nothing; it is written only after you submit the proposal and someone confirms | right | The AI and the system only draft; confirmation makes it take effect
  - Only the material request | wrong | This step writes nothing
more: #Taking an order on the workbench
```

```quiz
q: An item has 30 in stock, another open order has 20 allocated, the new order needs 25, nothing in transit, no safety stock. What is the net requirement?
options:
  - 0, stock is enough | wrong | The 20 allocated cannot be used again
  - 15 | right | Net requirement = need 25 + allocated 20 + safety stock 0 − stock 30 − in transit 0 = 15
  - 25 | wrong | 10 usable in stock must still be subtracted
more: #How MRP is computed
```

```ask
q: Which order will be late, and why?
```

:::查表

## Taking an order on the workbench

1. The planner fills in customer, product, quantity and due date under “New order” in “Orders & planning” and clicks “Compute materials”. This step writes nothing.
2. When it looks right, click “Submit (create a proposal to confirm)”.
3. Confirm it under “Proposal”. After confirmation, ERPNext has a sales order, work orders and material requests.
4. In the “Work orders” table click “Release to shop”; the work order is dispatched to machines operation by operation along the routing.

Net requirement = this order's need + other orders' allocations + safety stock − stock − in transit; only when above 0 is a request (rounded up to the lot size) or work order created.

MRP on the workbench uses real data: stock from ERPNext's latest stock snapshot, in transit from purchase orders and material requests, allocations from other open orders and unstarted work orders.

## Engineer to order (ETO): no drawing exists yet

A one-off order (a different ratio, a longer shaft, a special coating…) has no bill of materials yet: estimate and quote first, then design and build after the order. One page does it all: “Orders & planning → **Engineer to order (ETO)**”.

| Step | Who | Needs a person to confirm? | What ERPNext gets |
| --- | --- | --- | --- |
| Estimate: material, bought-out, operations, outside work, engineering (AI can draft) | Sales | No (nothing goes to ERPNext) | — |
| Quotation | Sales | Yes (proposal) | Project, quotation |
| Order (with a payment schedule) | Sales | Yes (proposal) | Sales order |
| Design: draft from the estimate, “copy as new” the parts that change, release | Process engineer | Yes (proposal) | Items, BOMs |
| MRP and backward schedule from the due date | Planner | Yes (proposal) | Work orders, material requests |
| Release to the shop, start each operation | Planner, operator | Release: yes (proposal) | Job cards |
| Inspection plan, first article, final inspection | Inspector | Plan is approved; results: yes (proposal) | Quality inspections |
| Shipping and customer acceptance | Sales | Shipping: yes (proposal) | Delivery note |
| Invoicing by milestone | Sales | Yes (proposal) | Sales invoices |

A “proposal” shows a person what will be written to ERPNext; nothing is written until they click “Confirm”. In teaching mode the teacher (plant manager) or another student confirms.

The rules (all decided by the platform from facts, never by AI):

- One “unknown” line blocks the quotation; the quoted revision is frozen and later changes start a new one.
- Work orders must use the released design; after a design change, run MRP again.
- Too few final inspections, an unapproved plan or an open nonconformance blocks shipping.
- Each installment is invoiced once, and only after its milestone (order, shipment, acceptance) is reached.

Step-by-step details and FAQs are in the document “Engineer to order (ETO)”; to practise, do lab 33.

## Where else orders come from

- Sales pipeline: under “Customers & service” a lead, opportunity, quotation and contract turn into an order, opening the same “take order and compute materials” preview (see “Customers & service”).
- In production mode the AI factory assistant can draft orders; you still confirm them.
- Sister plants in the industrial park (round 51): the WenQuest Digital Industrial Park robot plant buys WQR-105 from this plant (for the AGV drive units); its purchase order arrives
  under “Industrial park orders” in “Orders & planning” (teaching mode only). The planner clicks “Accept”: MRP, order and work orders are written to ERPNext; then release them under “Work orders”.
  The teacher can turn on “Auto-accept” (on by default): if nobody accepts within 3 minutes, the platform accepts, releases and starts. When the order's work orders are all done, the platform ships automatically,
  sending the lot and serial numbers back to the robot plant; the order is invoiced as usual, with “WenQuest Robot Plant” as the customer.

## After the material request

Converting material requests into purchase orders, supplier shipping and incoming inspection are done in “Purchasing & incoming” (see “Purchasing & incoming”).
