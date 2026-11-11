# This plant: WenQuest Digital Industrial Park · Sensor plant

> The park's fifth plant: it makes the two sensors inside every cobot joint — the **absolute encoder** that measures angle and the **joint torque sensor** that measures torque.
> Encoders are sold to the park's robot plant; read-head boards are bought from the park's PCB plant.

## The park's chain

```
Chip plant (WQ-ENCIF encoder interface chip) → PCB plant (driver board Rev B, encoder read-head board ENC-RD) → Sensor plant (joint encoder WQ-ENC17) → Robot plant (joint modules, robots)
```

The robot plant's item “Joint absolute encoder ENC-ABS” is ordered here (our item number WQ-ENC17); this plant's read-head board ENC-RD is ordered from the PCB plant.
The purchase order arrives as the other plant's sales order; that plant ships when done and this one inspects on arrival and receives into stock — the same way the robot plant buys from the gearbox and PCB plants.

## What it makes

| Product | ID | Example price | Main operations |
|---|---|---|---|
| Joint absolute encoder (optical, 17-bit single-turn) | WQ-ENC17 | $120 | Disc cleaning → bonding and centering → read-head adjustment → accuracy calibration → temperature cycling → final test |
| Joint torque sensor (strain-gauge full bridge, ±200 N·m) | WQ-TS | $320 | Strain gauge bonding → adhesive cure → bridge wiring → temperature compensation → deadweight calibration → final test |

## The shop

Two lines, 15 machines (layout, sizes and rates are example values):

- **Encoder line (clean room)**: incoming inspection bench, disc cleaning bench, disc bonding and centering machines ×2 (cb-1, cb-2), read-head adjustment bench, encoder calibration bench, temperature cycling chamber, encoder final test bench;
- **Torque sensor line**: strain gauge bonding bench, cure oven, bridge wiring bench, temperature compensation chamber, deadweight calibration bench, torque final test bench;
- Shared packing bench, raw material store, finished goods store and two logistics carts.

Open the [3D shop](/3d) to see the layout; [Encoder error curves](/enc-curve) is a page only this plant has.

## URL

https://sensor.factory.wenquestrobotics.com (sign in with your WenQuest account as in the other plants; data is separate from the other plants).
