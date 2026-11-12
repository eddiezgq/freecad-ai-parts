# From design to factory

> A part design releases a new version; the process plan is pre-checked by AI and approved by a person; then the shop works to the new drawing and the new process.

## How a new version reaches the shop

Change one thing in the design and the STEP, part drawing, machining program and ERPNext design revision all update together; when a work order is released, the new program goes to the machine with the operation:

```anim
name: flow
caption: Design → process → order → shop: a new version travels this line to the machine
```

## Hands on: release a new version

Design output shaft SH-301 online: change shaft segments, chamfers and the keyway, and the 3D model on the right follows at once. Once released, this step ticks itself (use the “Process engineer” role).

```goto
tour: engineer-design
label: Help me release a new version
```

```live
kind: plant
```

## Process plans and AI review

Write it following the reference plan and upload it: AI first checks locating error, clamping force and times, then the technical lead annotates and approves.

```goto
tour: process-plan
label: Help me submit a process plan
```

## Your pick

```quiz
q: The “Release new version” button is gray, with a red line below: “Keyway longer than its shaft segment”. What do you do?
options:
  - Try another browser | wrong | It is gray because the check failed; the browser has nothing to do with it
  - Shorten the keyway or lengthen the segment; when the check passes the button lights up | right | Red lines must be fixed; yellow lines are only notes that differ from the standard's recommended values
  - Release first; the shop will fix it | wrong | You cannot release when the check fails
more: #Designing online
```

```quiz
q: You changed the keyway length and released. Which operation in the shop uses the new version?
options:
  - Rough turning | wrong | Turning programs do not change with the keyway
  - Keyway milling: the new G-code goes to the keyway mill with this operation when the work order is released | right | The server generates keyway G-code from the new design
  - Cylindrical grinding | wrong | Grinding does not machine the keyway
more: #Designing online
```

```ask
q: After changing the keyway length, which operation in the shop uses the new version?
```

:::查表

## Three ways to release

| Where you design | Suits | How it reaches the factory |
| --- | --- | --- |
| Online design on the “Design & process” page | Demo part output shaft SH-301, just change parameters | Fill in the change note, click “Release new version” |
| Desktop CAD macro pack (FreeCAD 1.1 or SolidWorks, optional) | Students who want to learn real CAD | Download “My CAD macro pack” on the same page and run the release macro in CAD |
| “Design release & approval” page | Parts drawn in any CAD | Upload STEP (drawings and machining programs optional) |

In teaching mode it takes effect on submission. In production mode it takes effect only after an approver reviews, annotates and approves (the button becomes “Submit for approval”).

## Designing online

1. Open “Design & process” (process engineer).
2. In “Online design · Output shaft SH-301” change segment diameters and lengths, chamfers, shoulder fillets and the keyway. The 3D model on the right follows at once, with check results below.
3. Fill in the change note and click “Release new version”. The server generates STEP, the part drawing and keyway G-code, and the design revision in ERPNext goes up by one.
4. When a work order is released, the new G-code goes to the keyway mill with the “Keyway milling” operation.

When the check fails, “Release new version” is gray: read the red lines (e.g. keyway longer than its shaft segment). Yellow lines are notes that differ from the standard's recommended values; you can click “Use recommended value”, or release without changing.
The sign-in credential in the macro pack is valid for 7 days. When it expires, download it again from the “Design & process” page.

## Plant-wide BOMs and routings

At the bottom of Design & process is every item in the plant that has a BOM: the WQR-105 gear reducer and its sub-assemblies and parts. Pick one to see its BOM (click a made part to jump to its own BOM), its routing (minutes per piece, machines, pieces per load) and its standard cost. It is read-only; MRP uses exactly this data.

## Two steps of a process plan

1. **AI pre-check**: automatically checks locating error, clamping force and times. Out of tolerance is marked “Must change”; where there is margin it gives “Suggestions”.
2. **Technical lead annotates and approves**: once approved it becomes the effective version and the shop dispatches by it.

An approved process plan can generate the full set of process documents: process route card, operation cards, inspection card, tool card.

## Computation desks

After changing a design you can recheck it on the computation desks. Every desk has standard problems that compare with the textbook formulas.

| Computation desk | What it does | Lab |
| --- | --- | --- |
| [Simulation & analysis](/cae) | Finite elements: strength, fatigue, thermal | Lab 8, Lab 11 |
| [Motion & dynamics](/mbd) | Multibody dynamics: joint torque, motor selection | Lab 9 |
| [CNC programming](/cam) | Generate turning and milling programs from the part, replay toolpaths | Lab 10 |
| [Design optimization](/opt) | Lightweighting, parameter optimization | Lab 11 |
| [Digital twin](/twin) | Condition monitoring and predictive maintenance of a gearbox | Lab 13 |
| [Flow analysis](/cfd) | Fluid flow and heat transfer of fan cooling | Lab 14 |
| [Virtual PLC](/plc) | Control programs for a press-fit station and a sorting line | — |
| [Circuit analysis](/circuit) | Driver board circuits: DC, AC (Bode plot), transient, tolerance; netlist mode | — |
| [Virtual instruments](/instruments) | Oscilloscope, multimeter, signal generator, logic analyzer, data logger measuring 6 kinds of sensors | — |
| [PCB design](/pcb-design) | KiCad design of the joint driver board: schematic, PCB, 3D, BOM, manufacturability check | — |
| [Chip design](/chip-design) | Encoder interface chip WQ-ENCIF: Verilog, simulation waveforms, synthesis, layout (SKY130), checks; connect an encoder and watch the logic analyzer | — |

## Circuit analysis

[Circuit analysis](/circuit) (round 79) uses ngspice to compute circuits on the robot joint servo driver board DRV-JOINT. Each example has a schematic (click a component with parameters to jump to its input), adjustable parameters and curves;
every reading sits in one table with the hand-calculation formula, stating the allowed difference; the formulas are approximate, and the note under the table explains why they differ.

| Example | What it computes | Analyses used |
| --- | --- | --- |
| 1 Phase current sensing amplifier | Shunt resistor and gain put the peak current into the ADC range; bandwidth; gain error with 1% resistor deviation | DC sweep, AC, Monte Carlo |
| 2 Gate drive and switching time | Gate resistor vs switching speed, Miller plateau, turn-off delay (sets dead time) | Transient; gate charge method |
| 3 Bus capacitor and input filter | Bus ripple, resonance of cable inductance with bus capacitance | Transient, AC |
| 4 Encoder signal receiver and filter | Whether the RC filter eats fast pulses, comparator delay | Transient, AC |
| 5 24 V → 5 V buck supply | Inductor current ripple, output ripple, efficiency | Transient |
| 6 Motor current loop | Electrical time constant, PI rise time and bandwidth, whether the voltage is enough | Transient, AC |

For “Where to compute”, choose **Browser**: ngspice compiled to WebAssembly runs on your own computer (about 5 MB to download the first time, fast after that); choose **Server**: ngspice on the server does it. Both use the same netlist and give the same readings.
Tolerance analysis and netlist mode run on the server. Netlist mode does not support reading or writing files or `.control` sections. “Download calculation report” generates Word: parameters, comparison table, curves, tolerance results and netlist.

All parameters are example values (48 V bus, torque constant 0.15 N·m/A, 400 W servo motor), and devices use generic models; they do not represent any manufacturer's product.

## Virtual instruments

[Virtual instruments](/instruments) (round 82) measures the way a lab bench does: the device under test and wiring are already set up; adjust the instrument, read, click “Record”, and finally “Submit to the platform for checking” the results you computed, getting ✓ or ✗ for each item (correct values are not shown).
Each person's sensor parameters scatter around the nominal value (fixed per signed-in person), so numbers cannot be copied. All parameters are example values.

| Task | Instrument | Compute |
| --- | --- | --- |
| 1 Torque sensor calibration | Multimeter (10 V bridge excitation) | Sensitivity (mV/V), zero, nonlinearity, hysteresis (%FS) |
| 2 Encoder speed and decoding | Oscilloscope, logic analyzer | Direction, speed, counts per revolution, Z pulse interval |
| 3 IMU static bias and Allan variance | Data logger (2 hours at rest) | Bias, angle random walk, bias instability |
| 4 Hall current sensor | Current source, multimeter, signal generator, oscilloscope | Sensitivity, zero, −3 dB bandwidth |
| 5 Thermistor temperature curve | Constant-temperature bath, multimeter | B value, R25 |
| 6 Laser rangefinder noise and averaging | Data logger | Standard deviation at 1 m and 5 m, and after averaging 16 times |

Instruments are modeled on real ones: the oscilloscope has bandwidth, 8-bit quantization and a noise floor; the multimeter has ranges, resolution and accuracy class, with type B (accuracy ÷ √3), type A (last 10 readings) and combined uncertainty shown next to the reading.
A few tips: for a sine amplitude on the oscilloscope, “AC RMS × √2” is more accurate than peak-to-peak; read ARW from the short-τ part of the Allan curve (slope −1/2); the bias instability estimate itself scatters by about ±30%, so the platform's tolerance is wider.
On the circuit analysis page, click “Send to oscilloscope” on a transient curve to view the simulated waveform here. Each task can export CSV and a Word lab record.

## PCB design

[PCB design](/pcb-design) (round 88) is a KiCad design of the joint servo driver board DRV-JOINT. **Example design, not hardware-verified, not for direct production**;
chips are example selections from devices in the official KiCad libraries (pins from the official libraries), and resistor and capacitor values are computed from circuit formulas — the same set of numbers as the “Circuit analysis” examples.

| Tab | What to see |
| --- | --- |
| Schematic | 7 sheets: 48 V input and bus, auxiliary supply, three-phase bridge, gate drive, phase current sensing, MCU, encoder and CAN; each sheet has notes, and four jump to the circuit analysis example of the same name |
| PCB | 4-layer board 100 × 70 mm, each layer switchable; half-bridge midpoints and bus run on copper pours, ground on an inner plane |
| 3D | Component shapes from the official KiCad 3D model library; download STEP to open in FreeCAD |
| BOM | One row per item; the item number is the one in the PCB maker's list (the SMT board and finished board BOMs use this design's quantities) |
| Manufacturability check | Checked against an example board maker's process capability: track width and spacing, holes and annular rings, solder mask bridges, component to board edge, component spacing, polarized component orientation, ICT test point coverage, high-current track width; each item says “why the board maker cares”, and a click marks the location on the PCB |
| Downloads | KiCad project, Gerber and drill, BOM, placement coordinates, STEP |

How the design is made: a design description (devices, values, which net each pin connects to) → a script writes the KiCad schematic and PCB → the open-source autorouter Freerouting routes it →
KiCad design rule check and export. On every push the automated tests export it again with KiCad, and it must match the repository exactly (3D excepted).

At the top of the page you can switch **Rev A / Rev B** (round 98). Rev A is the version the PCB maker is producing; the MCU counts encoder pulses directly.
Rev B puts the encoder interface chip WQ-ENCIF from “Chip design” below on the board: encoder A/B/Z go through the original filter into the chip, the chip counts, the MCU reads it over SPI, plus a 50 MHz crystal and a 1.8 V regulator.
Rev B's “What changed A→B” lists new components, which MCU pins changed, the extra BOM items and the firmware configuration to change. **Rev B is only a design comparison, not for production** — the chip has not been taped out and cannot be bought.

Rev B also has a “**Firmware (Renode simulation)**” section (round 100): example firmware for the MCU reading this chip (C, no vendor libraries, every register address cites the manual),
the real compiled firmware runs in the open-source MCU simulator Renode, with the chip and motor simulated. Six scenarios — power-up, forward 600 rpm, reverse through zero, Z phase, chip error, chip not responding —
each plot “what the firmware read” and “what the motor actually did” together and judge each item. The board has no debug UART; the firmware puts results in a “telemetry area” in memory, like reading variables over SWD with a debugger.
The source can be viewed file by file or downloaded as a bundle (with fw.elf and simulation scripts); install Renode locally to reproduce it.

Round 102 added the driver board's real job to this firmware: **field-oriented control (FOC) to actually turn the joint, CAN to receive commands and send status, and fault protection**. Above the “Firmware” section switch to “Motor control & CAN”:
the control block diagram (position loop 1 kHz → speed loop 2 kHz → current loop 20 kHz → PWM → inverter bridge → motor → 1:100 gearbox → swing arm),
six scenarios — power-up alignment, current loop step, speed loop, position loop 90° turn, holding under gravity with sudden load, protection (overcurrent, encoder fault, communication timeout, undervoltage) —
each with curves, criteria and a CAN bus log (alarm frames in red); below are the CAN protocol and parameter table, each parameter's source stated as the parts library, the driver board design or an example value.

Round 107 added four more scenarios: **reading the output-side absolute encoder at power-up** (the joint knows where it is wherever it stopped, no longer treating the power-up position as 0°), **output encoder wire broken**, **gearbox slipping** (the two encoders disagree; it stops at 0.5°), and
**controlled stop** (when communication is lost, decelerate to a stop first and hold position without cutting power; only when undervoltage makes holding impossible is the output turned off).

Round 110 added a **brake driver** to the Rev B circuit (U16, Q7, D5, J6 in “What changed A→B”), with the brake timing in firmware and four more scenarios: **power-up braked, stabilize then release**, **undervoltage: stop, brake, output off**, **dangerous fault: output off and brake at once** (the swing arm is caught after dropping a tenth of a degree), **“Stop”: stop, brake, output off**. Remember two rules: torque first, then release the brake; brake first, then remove torque. The brake coil is PWM-fed from the 48 V bus (24 V average), and with no MCU output it brakes — fail-safe.

Round 114 added **brake coil current sensing** (R39 shunt → PB0), so brake state is no longer just guessed from time: **brake wire broken**, **coil shorted** and **switch transistor failed short (cannot brake)** all report fault 7. When the brake has a problem the firmware first makes the motor hold in place, and turns off the output only after it measures the coil current really drop (braked); if it cannot brake it keeps holding — better the motor works harder than the arm falls.

Round 115 added a **multi-joint master** on the “Firmware” page: one master program (`fw/master/master.py`, written in Python that students can read) drives two driver boards at once as a horizontal two-joint arm. The master ticks every 10 ms: receive frames → supervise → compute the next point of the end effector on the line → inverse kinematics to two joint angles → send commands to both joints at once. Three scenarios: **end effector moves in a straight line** (deviation under 0.5 mm), **one joint alarms, all stop together**, **one joint drops off, all stop together**. Drag the slider under the arm drawing to see frame by frame how the two joints work together.

## Chip design

[Chip design](/chip-design) (round 92) is a small chip designed for the driver board: **encoder interface chip WQ-ENCIF**, taken from Verilog all the way to layout (GDS).
**Example design, not taped out, not silicon-verified**; the process is the open-source SKY130 (130 nm).

What it does: encoder A, B, Z pulses → synchronizer → digital filter (removes glitches shorter than N+1 clocks) → 4× decoding (one step per edge; A and B changing at once reports “missed step”)
→ 32-bit count, Z latch → read by the MCU over SPI. Clock 50 MHz.

| Tab | What to see |
| --- | --- |
| Spec | How the five internal blocks connect, pins, register table, SPI frame format |
| Verilog | The chip's source code; simulation, synthesis and layout are all generated from this one source |
| Simulation | 9 cases (forward/reverse, high speed, glitches, missed steps, Z phase, overflow, SPI read/write, reset, random): RTL compared **cycle by cycle** with a Python reference model, each with waveforms |
| Synthesis | How many standard cells (flip-flops, adders, AND/OR gates…), area, power estimate |
| Layout | The whole chip, switchable by device layers and each metal layer; zoom in to see individual standard cells |
| Checks | Design rules (DRC), layout vs schematic (LVS), setup and hold times, antenna effects: all must pass before GDS |
| Transistor level | The input Schmitt trigger (round 93): SKY130 device models + ngspice compute the upper and lower thresholds and hysteresis; on the same slow edge with ±0.3 V interference, a plain inverter toggles many times while the Schmitt trigger toggles once (one answer to the “noise immunity of encoder signals” problem in chapter 1 of *Digital Integrated Circuit Design*) |
| Connect an encoder | Adjust speed, glitch count and width, filter length N; the logic analyzer shows raw A/B, filtered A/B, count and SPI read frames; with N too small glitches get through and the count jumps back and forth |
| Downloads | Verilog, testbench, reference model, flow configuration; GDS, gate-level netlist, all reports |

Try it: in “Connect an encoder” set the filter length to 0 and add more glitches — watch “passed through the filter” and “extra count jumps”; set it back to 3 and see them go to 0.
