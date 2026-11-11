# Functional test bench

> After burn-in, driver boards are tested item by item on the functional test bench; this page replays each board's test with virtual instrument screens, and you can retest a board yourself.

## Test program

Factory test of driver board DRV-JOINT (specs are example values):

| Step | What it tests | Instrument | Spec |
|---|---|---|---|
| 1 | Shunt resistance (in-circuit test) | Four-wire multimeter: voltage drop at 10 A test current | 2.00 ± 0.02 mΩ |
| 2 | Bus voltage reading | Programmable supply 48 V + multimeter; the board reports its reading over CAN | Error ±1 % |
| 3 | Phase current sensing | Current source injects 10 A; the board reports its reading | Error ±2 % |
| 4 | Gate dead time | Oscilloscope CH1 high-side gate, CH2 low-side gate | 160–240 ns |
| 5 | Encoder interface | Encoder simulator sends 4000 counts | ±2 counts |
| 6 | Current zero after burn-in | Read the board with no current applied | ±50 mA |

The bench uses the same instrument models as “Virtual instruments”: the multimeter has ranges and resolution, the oscilloscope has bandwidth, quantization and noise.

```anim
name: spc
caption: Each board's results go into the quality record: sensed current error keeps rising — first check whether it is the same reel of shunts
```

## Replay and retest

On the left are boards that have had functional test (with shunt reel number); click one to see each step's instrument screen — the readings are the values the shop recorded at the functional test station.

**Retest**: read the four quantities yourself (shunt resistance, bus voltage error, phase current error, dead time), judge the board pass or fail, and click “Submit retest”.
The platform checks two things: how far your readings are from the shop record (instrument error allowed), and whether your verdict is right. The retest record goes into this board's unit history without changing the shop's original measurements.
After the teacher injects “incoming shunt resistor lot”, boards from that reel on have high resistance and current error — a retest should fail them.

## Hands on: open a quality issue

On the “Quality” page look at the control chart of the driver board's “phase current sensing error” and open an 8D for the high boards. Once opened, this step ticks itself (use the “Inspector” role).

```goto
tour: quality-chart
label: Show me the control chart and open a quality issue
```

```live
kind: kpi
```

## Your pick

```quiz
q: In a retest the gap between the two gate waveforms on the oscilloscope is 300 ns. How should this board be judged?
options:
  - Pass — more dead time is safer | wrong | Too much dead time lengthens freewheeling through the diodes, increasing losses and waveform distortion; the spec is 160–240 ns
  - Fail | right | Outside the 160–240 ns spec
  - Cannot tell; test again | wrong | The oscilloscope reading is far outside the spec, well beyond instrument error
more: #Test program
```

```ask
q: How many driver boards failed functional test recently?
```
