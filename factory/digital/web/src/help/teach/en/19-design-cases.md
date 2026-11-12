# Design cases

> Left menu “Design & process → Design cases”: three complete cases per plant, from the design brief all the way to the shop floor. A is one part or module, B is a sub-assembly, C is the whole product — and A and B are parts of C.

```goto
tour: cases-walk
```

The plant right now (step 7 of each case is made in this plant's simulated shop):

```live
kind: plant
```

## Every case has eight steps

| Step | What | Software used |
|---|---|---|
| 1 Design brief | Purpose, performance, duty, constraints | — |
| 2 Concept | Compare two or three concepts, choose one | Online design, design release |
| 3 Calculation | Hand calculation by the textbook methods: strength, life, electromagnetics, circuits… | Calculation sheet |
| 4 Simulation | FEA, fatigue, modal, thermal, multibody dynamics, circuit simulation… | Simulation & analysis, motion & dynamics, circuit analysis |
| 5 3D model & drawing | 3D model (STEP), part drawing / schematic and PCB | Online design, parts library, PCB design |
| 6 Process planning | Routing, CNC programs / placement programs / test programs | Process plans, CNC programming |
| 7 Manufacturing | Make and inspect in this plant's simulated shop; yield, process capability and cost | Orders & planning, shop-floor terminal, quality |
| 8 Review | All checks (the case only passes when every one passes), what changed, questions for you | — |

```anim
name: flow
```

Each step has “open software” buttons so you can redo the numbers yourself. The check list in step 8 states the requirement and the source of every item.

## Gearbox plant, case A: output shaft SH-301

One shaft from the brief to the shop floor. Worth a look:

- **Step 2**: the current rev A cannot take the 6207 bearing and neither key can carry 350 N·m, so the shaft must be redesigned; rev B in 45 steel fails in fatigue, so 40Cr is used;
- **Step 4**: the FEA reactions and plain-shaft stress are first checked against hand calculation, then the fatigue life is computed from the run-in bench torque record — unchecked FEA results are not to be used;
- **Step 7**: the first 20 parts are all in tolerance, but the bearing-seat Cpk is only about 1; after shortening the wheel-dressing interval the second batch exceeds 1.33. In tolerance is not the same as reliably in tolerance.

All numbers are computed by programs (the same code as the textbook *Machine Design* chapter 33 and the digital factory's FEA, CNC programming and simulated shop). **This is an example design; it has not been built and tested.**

```quiz
q: In case A all 20 shafts of the first batch are in tolerance. Why change the wheel-dressing interval anyway?
options:
  - One shaft was out of tolerance | wrong | none of the 160 measurements in batch 1 was out of tolerance
  - The bearing-seat Cpk is only about 1, so volume production will sooner or later go out of tolerance | right | in tolerance describes these 20 parts; Cpk describes whether the operation can keep making good parts
  - To save grinding wheels | wrong | dressing more often uses slightly more wheel
```

## Cases, labs and the textbook

- A case shows the whole method once; a lab has you do one part of it yourself. Gearbox case A goes with lab 8 (strength and fatigue), lab 10 (CNC programming), lab 12 (digital design of a shaft) and chapter 33 of *Machine Design*.
- Cases for the seven plants are being added; levels not ready yet show “in preparation”.
