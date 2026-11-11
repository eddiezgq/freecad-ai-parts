# Purchase receipts and supply from the gearbox plant

> Shortage → request → purchase order → supplier ships → arrival → incoming inspection → stock. The WQR-105 purchase order goes to the WenQuest gearbox plant, becomes a sales order there, and is shipped back when done.

## How purchased items arrive

The robot plant's “Purchasing & incoming” is the same as the gearbox plant's:

1. Take an order and run MRP; missing purchased items and raw materials become **material requests**;
2. If nobody converts a request within 3 minutes, the buyer (teaching simulator) converts it to a **purchase order** with the default supplier and writes it into ERPNext;
3. The supplier ships (in transit). In teaching mode one supplier day = 2 real minutes, so the harmonic drive's 20-day lead time ≈ 40 minutes;
4. On arrival do **incoming inspection**: harmonic drives — backlash; servo motors — no-load current and insulation resistance; aluminum bar — material certificate and hardness; WQR-105 — noise and leakage;
5. Passing lots are received into stock (ERPNext purchase receipt + incoming inspection) with the lot number recorded; failing lots are returned or accepted under concession.

Suppliers' on-time rate, pass rate, lead time and alternative suppliers are all **example values**, written in the robot plant's manifest.

```video
name: robot-order
caption: Take an order and run MRP: where material requests come from
```

## WQR-105: the two plants really connected

WQR-105's supplier is the WenQuest gearbox plant — another plant in the park. Its purchase order does not stay on paper:

1. Once the robot plant's purchase order is in ERPNext, the platform **sends it to the gearbox plant** (teaching mode), which gains a “park order”;
2. The gearbox plant's planner **takes the order** in “Orders & planning”: MRP, order and work orders written into the gearbox plant's ERPNext, released to the shop.
   The teacher can turn on “Auto-accept” (on by default): if nobody takes it within 3 minutes, the platform takes, releases and starts it;
3. When all the gearbox plant's work orders for this order are done, it is **shipped**: the lot number and each unit's serial number go back to the robot plant;
4. At the robot plant this lot becomes “in transit”; after 1 day of transport (≈ 2 minutes) it arrives and gets incoming inspection and stocking as usual.

**A third plant**: the supplier of joint driver boards (Rev B DRV-JOINT-B from round 118, with brake driver and output-side absolute encoder reading) and AGV control boards CTRL-AGV is the WenQuest PCB plant, the same way — when driver boards fall below safety stock they are requested,
the purchase order goes to the PCB plant, that plant ships back when done, and on arrival the factory test report and ESD packing are checked.

If the gearbox plant (or PCB plant) cannot be reached, or does not take this item, the purchase order is treated as an ordinary external supplier (lead time 10 days, example) and the page says why.
Only two kinds of message pass between plants, “order” and “shipment”; neither sees the other's stock, costs or customers.

```anim
name: mrp
caption: WQR-105 requests come from MRP: gross requirement − stock − on order + safety stock
```

## Tracing lots all the way to the supplier

When joints are assembled, harmonic drives are used **first-in first-out** by arrival lot: the lot numbers in “stratify by gearbox lot” on the quality page and in lab 25 are the incoming inspection lot numbers.
Enter a lot number in “Purchasing & incoming → Lots” to see which joints it went into; conversely enter a joint number to find which lot, supplier and purchase order it used.
The lab 25 fix “quarantine the problem lot” fails the lot in use and returns it to the supplier, who ships a new lot.

## Hands on: inspect an incoming lot

First take an AGV or a cobot and wait for purchased items to arrive (or have the teacher turn off the supplier simulator in “Purchasing & incoming” and register arrivals yourself).
As “Inspector”, click a lot in “Arrivals & inspection”, look at the sample data and judge pass or fail. Once a lot is judged, this step ticks itself.

```goto
tour: supply-inspect
label: Help me inspect an incoming lot
```

```live
kind: kpi
```

## Your pick

```quiz
q: The robot plant placed a purchase order for 10 WQR-105 with the WenQuest gearbox plant. What happens at the gearbox plant?
options:
  - Nothing; it is just a piece of paper | wrong | Since round 51 the two plants are connected: the purchase order is sent to the gearbox plant
  - A “park order” appears; once the planner takes it (or the platform auto-accepts) it becomes a sales order, and it is shipped back when done | right | The buyer's purchase order is the seller's sales order
  - The gearbox plant's stock drops by 10 directly | wrong | It must be taken and produced (or in stock) before shipping; each plant keeps its own stock
more: #WQR-105: the two plants really connected
```

```quiz
q: A lot of harmonic drives is sampled on arrival; 2 of 8 have backlash over the 1.0′ limit. How is it judged?
options:
  - Pass: most are within tolerance | wrong | Any item of any piece in the sample out of tolerance fails the whole lot
  - Fail: return it or accept under concession (100 % inspection to pick out usable ones) | right | A failing lot in the shop makes joint backlash high — that is where the “lot problem” in lab 25 comes from
more: #How purchased items arrive
```

```ask
q: If the gearbox plant's WQR-105 delivery slips a week, what happens to the robot plant's AGV orders? What can be done?
```

:::查表

## Lab 27: one order between two plants

Do it under “Labs & tasks → Lab 27”: take 2 AGVs, run MRP (how many WQR-105 to request), send the purchase order to the gearbox plant (enter the park order number), inspect and stock on arrival (ticks itself),
compute the lead time, compute safety stock and reorder point (SS = 1.65 · σ_d · √L, ROP = d · L + SS), review sharing demand information between the two plants. The platform scores 60 points automatically and the report is 40;
the lab guide and report template (bilingual) are at the top right of the lab page.


## The robot plant's suppliers (example values)

| Category | Supplier | Lead time | On-time / pass rate | Alternative | Incoming inspection |
|---|---|---|---|---|---|
| Aluminum | Example · East China Aluminum | 5 days | 95% / 99% | Example · North Aluminum (10 % dearer, active) | Material certificate, hardness 95–120 HBW |
| Harmonic drives | Example · Harmonic drive distributor | 20 days | 85% / 90% | Example · Precision Drives (15 % dearer, must be developed first) | Appearance and rotation, backlash ≤ 1.0′ |
| Servo motors | Example · Servo motor supplier | 14 days | 90% / 97% | — | No-load current 0.2–0.8 A, insulation resistance ≥ 100 MΩ |
| Gearboxes | WenQuest gearbox plant (park) | 10 days | Based on actual deliveries | — | No-load noise ≤ 75 dB(A), leak check |
| Electronics, standard parts, AGV parts | Example | 3–10 days | 90–95% / 98–99% | — | — |

## Orders between plants: who does what

| Step | Robot plant | WenQuest gearbox plant |
|---|---|---|
| Order | Request → purchase order (ERPNext) → sent to the gearbox plant | A “park order” appears (awaiting acceptance) |
| Accept | — | The planner accepts or the platform auto-accepts: MRP, order and work orders into ERPNext, released |
| Produce | Waiting (purchase order “sent to sister plant, in production”) | The shop works the WQR-105 order's work orders |
| Ship | Receives lot and serial numbers; this lot is “in transit” | All work orders done → ship and report back; the order is invoiced as usual |
| Receive | Arrival → incoming inspection → received into stock | — |

From round 118, “joint test” of joint modules has two more items: **brake holding torque** (output side) and **dual-encoder cross-check difference** (motor-side converted vs output-side absolute encoder) — features only the Rev B driver board firmware has, measured at outgoing inspection. That connects the chain: the chip plant makes the encoder interface chip → the PCB plant makes the Rev B driver board → the robot plant builds it into joint modules.
