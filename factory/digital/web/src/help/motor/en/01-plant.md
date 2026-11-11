# This plant: WenQuest Digital Industrial Park · Motor plant

> The park's sixth plant: it makes **permanent-magnet synchronous servo motors** for cobot joints and AGV drive wheels.
> All four motors are sold to the park's robot plant — which used to buy from “Example · Servo motor maker” and buys here from round 131 on.

## The park's chain

```
Chip plant (WQ-ENCIF) → PCB plant (driver board Rev B, read-head board) → Sensor plant (joint encoders) → Robot plant (joint modules, robots) ← Motor plant (servo motors, AGV motors)
```

The robot plant's items MTR-SV-100/200/400 and MTR-AGV-750 are ordered here (our item numbers WQ-SM100/200/400, WQ-AM750).
The purchase order arrives as a sales order here; this plant ships when done, and the robot plant inspects on arrival and receives into stock — the same way the other plants buy and sell from each other.

## What it makes

| Product | ID | Example price | Notes |
|---|---|---|---|
| Servo motor 100 W (with brake) | WQ-SM100 | $190 | 60 frame, small robot joints |
| Servo motor 200 W (with brake) | WQ-SM200 | $240 | 60 frame, medium robot joints |
| Servo motor 400 W (with brake) | WQ-SM400 | $320 | 80 frame, large robot joints |
| AGV drive motor 750 W | WQ-AM750 | $380 | 80 frame, no brake |

All four are 10-pole 12-slot (example). The motor-side encoder is not mounted on the motor; the joint driver board reads it.

## The shop

Three lines, 14 machines (layout, sizes and rates are example values):

- **Stator line**: incoming inspection bench, core stacking press, winding machines ×2 (wd-1, wd-2), coil insertion and forming bench, varnish oven, stator test bench;
- **Rotor line**: magnet bonding bench, magnetizer, balancing machine;
- **Final assembly line**: motor assembly bench, brake test bench, motor final test bench (dynamometer), packing bench;
- Raw material store, finished goods store and two logistics carts.

Open the [3D shop](/3d) to see the layout; [Motor final test waveforms](/motor-wave) is a page only this plant has.

## URL

https://motor.factory.wenquestrobotics.com (sign in with your WenQuest account as in the other plants; data is separate from the other plants).
