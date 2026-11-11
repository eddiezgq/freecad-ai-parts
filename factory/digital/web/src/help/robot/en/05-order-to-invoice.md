# Taking an order: from order to invoice

> Take the order, run MRP, confirm the proposal into ERPNext, release by level, finish in the shop, test and calibrate, receive into stock, and finally the sales invoice is created automatically.

## The path one order takes

As in the gearbox plant, AI and the system only draft; only a person's confirmation writes into ERPNext. The difference: one order has a string of work orders, built from the bottom of the BOM up.

```anim
name: workorder
caption: How a work order flows through the shop: the slowest operation decides how long the whole batch takes
```

```video
name: robot-order
caption: Taking an order for a cobot
```

## Step by step

1. **Take the order, run MRP** (planner): in “Orders & planning” choose product, quantity and due date, click “Run MRP”, and see which work orders and requests are needed;
2. **Submit, confirm**: a proposal is created; after confirmation the bridge writes the sales order, all work orders and the material request into ERPNext;
3. **Release by level** (planner): first release made parts (housings, hollow shafts, arm tubes, base); once they are **finished into stock**, release the joint modules, and finally the robot;
4. **Start** (operator): click “Start” on the shop terminal for a dispatched operation;
5. **Test, calibrate**: the joint test bench, robot calibration station and AGV commissioning area produce measurements for the quality page; the job card can only be submitted once the inspection exists;
6. **Finish into stock**: when the last operation is done, the good quantity goes into stock;
7. **Invoice**: when all the order's work orders are complete, the system creates a sales invoice in ERPNext automatically (auto-confirmed in the teaching edition), amount = price × quantity.

## Hands on: take an order and submit the proposal

Take an order in “Orders & planning”, run MRP, and submit. When the proposal appears in the proposal list, this step ticks itself.

```goto
tour: planner-order
label: Take me to take an order and submit
```

```live
kind: machines
```

## Your pick

```quiz
q: A joint module work order is done in the shop; with ERPNext not allowing negative stock, finishing into stock says “insufficient stock in WIP store”. What is the most likely cause?
options:
  - ERPNext is broken | wrong | It is following the rules: no material drawn, no finished goods receipt
  - The joint module was released before its housing and hollow shaft work orders were finished into stock | right | Release by level: only when a lower level is in stock can the level above draw material
  - The price was not filled in | wrong | Price only affects the invoice amount
more: #Step by step
```

```quiz
q: After a WQ-CR5 (example price $18,000) is finished and stocked, what happens?
options:
  - Accounting must invoice by hand | wrong | In the teaching edition the system invoices and confirms automatically when the order is done
  - The system creates an $18,000 sales invoice in ERPNext automatically | right | Amount = price × quantity; the invoice is visible in ERPNext
  - Nothing; wait for the customer to pay | wrong | The invoice comes first, then the customer pays
more: #Step by step
```

```ask
q: Which step is my order at now?
```

:::查表

## How it differs from the gearbox plant

| | Gearbox plant (teaching edition) | Robot plant |
|---|---|---|
| Work orders per order | One (the output shaft; teaching makes only this part) | Every made part and subassembly of the robot, plus the robot itself |
| Measurement data | CMM measures the output shaft | CMM, joint test bench, robot calibration station, AGV commissioning area |
| Purchase receipts | Supply chain domain: purchase orders, incoming inspection, receiving | Not in this phase: opening stock is used, material requests are only records |
| After invoicing | Business and finance: payment, reminders, receivables aging | This phase stops at invoicing |
