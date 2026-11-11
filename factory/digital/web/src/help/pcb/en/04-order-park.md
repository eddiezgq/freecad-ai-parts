# Orders, purchasing and taking orders from the robot plant

> The PCB plant's orders come from two sources: orders taken by the teacher or planner, and purchase orders sent by the robot plant through the industrial park. Either way, when done they go into stock, are shipped and invoiced.

## From order to invoice

As in the other two plants: take the order → MRP (two work orders, SMT board and finished board; missing components requested) → order and work orders written into ERPNext → released to the shop →
the SMT line and back end finish operation by operation (inspection operations produce measurements; job cards and inspections go into ERPNext) → finished into stock → invoice when the order is done.

```anim
name: mrp
caption: Component requests come from MRP: gross requirement − stock − on order + safety stock
```

## The robot plant buys its driver boards here

In the robot plant's manifest, the supplier of driver boards (Rev B DRV-JOINT-B from round 118) and AGV control boards CTRL-AGV is “WenQuest PCB plant”:

1. The robot plant takes an order and runs MRP; when driver boards fall below safety stock they are requested; once the purchase order is in its ERPNext, the platform **sends it here**, and this plant gains a “park order”;
2. The planner here **takes the order** in “Orders & planning”: MRP, order and work orders written into this plant's ERPNext, released to the shop.
   The teacher can turn on “Auto-accept” (on by default): if nobody takes it within 3 minutes, the platform takes, releases and starts it;
3. When all this order's work orders are done, it is **shipped**: the lot number and each board's serial number go back to the robot plant;
4. On arrival the robot plant does incoming inspection as usual (factory test report, ESD packing), receives it into stock and builds it into joint modules.

If this plant cannot be reached, the robot plant treats the purchase order as an ordinary external supplier and the page says why. Only “orders” and “shipments” pass between the two plants; neither sees the other's stock or costs.

## Driver board Rev B: buying the encoder interface chip from the chip plant

From round 106 this plant can also take **driver board Rev B DRV-JOINT-B** (pilot production): compared with Rev A it adds an encoder interface chip WQ-ENCIF, a 50 MHz oscillator, a 1.8 V regulator and 5 capacitors
(exactly what the round 98 Rev B design added; see [PCB design](/pcb-design?rev=B&tab=diff)).

WQ-ENCIF is bought from the park's **WenQuest chip plant**. The chip plant sells by wafer lot — about 34,000 chips per lot — so this chip has two things in the manifest:

- `pack: 34000`: MRP requests in whole multiples of 34,000 (a real purchase's full pack / minimum order quantity); even for 2 boards a whole lot is bought and the rest stays in stock;
- `park_item: WQ-ENCIF`: when the purchase order is sent to the chip plant it is converted to their item number and quantity — 34,000 chips here is 1 lot of WQ-ENCIF there.

The chip plant takes the order, does wafer test, assembly, final test and ships; this plant receives it, does incoming inspection (moisture-barrier packing, humidity card, reel label) and stocks it — the same as the robot plant buying driver boards here.
In reality the chip has not been taped out and Rev B is not in production; this is pilot production inside the park.

## Component arrival and moisture-sensitive parts

The component suppliers (board fab, chip distributor, passive and connector supplier, soldering materials supplier) are all examples; arrivals get incoming inspection:
bare boards — measure thickness and check appearance; chips — check vacuum packing and the humidity indicator card; solder paste — check shelf life and arrival temperature. Shunt resistors are stocked by reel and used first-in first-out by reel at in-circuit test.

## Hands on: inspect an incoming lot

As “Inspector”, click a lot in “Purchasing & incoming → Arrivals & inspection”, look at the sample data and judge pass or fail. Once a lot is judged, this step ticks itself.

```goto
tour: supply-inspect
label: Help me inspect an incoming lot
```

```live
kind: domain
domain: supply
```

## Your pick

```quiz
q: At which step does a driver board the robot plant buys here become a sales order here?
options:
  - When the robot plant takes its order | wrong | At that point it is only the robot plant's own sales order
  - The robot plant's purchase order enters its ERPNext, the platform sends it here, and taking the order here writes it as a sales order | right | The planner can take it, or “Auto-accept” does it
  - When this plant ships | wrong | Shipping comes after the order is done
more: #The robot plant buys its driver boards here
```

```ask
q: How many park orders are in progress now?
```
