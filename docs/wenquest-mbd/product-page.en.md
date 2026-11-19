# WenQuest MBD · Product page content (English)

For the product page under "Enterprise solutions" on the WenQuest website (the page itself is built in the website repository). Only what the software really does; numbers come from the verification manual and the getting-started examples.

## Hero

**Import the assembly. Get the motor torque.**

Import the STEP file of a robot arm into FreeCAD. The program finds the joints in the geometry, AI helps select them, and you confirm. Give the joints a motion profile, click Compute, and get the torque each motor needs and the force on every joint, with the parts moving in FreeCAD. Every run comes with trust checks and a report your reviewer can sign.

Buttons: Free download (Windows) · Sample report

## What it computes

1. **Motion and drive loads**: from constant-speed or profiled drives, positions, velocities, accelerations, drive torques and joint reactions, for sizing motors, gearboxes and bearings.
2. **Dynamics**: free motion under gravity, springs, bushings, contact and gear mesh; closed loops with controllers (PID, state space, FMU co-simulation).
3. **Vibration**: natural frequencies and mode shapes by linearization, rotor whirl.
4. **Flexibility**: deformation and stress contours of parts (CalculiX reduction); large deflection, buckling and spin stiffening of slender rods (large-deformation beams).

## Why you can trust it

- **44 benchmark problems, 74 compared values, all within tolerance**: simple pendulum, Andrews squeezing mechanism, slider-crank power balance, Hertz impact, gear backlash, rotor whirl, cantilever (against a direct CalculiX solution on the same mesh), Mattiasson's elastica, Euler buckling load and more. The verification manual (Chinese and English) ships with the software; every number in it was computed by running the tests of that version.
- **Every joint has geometric evidence**: coaxial shafts and holes, mating guide faces, each stated; the AI only picks among these candidates and cannot invent joints.
- **Every run is checked**: constraint residual, degrees of freedom, energy conservation, stability; failures are reported as they are.
- **The program fills in the report numbers**: AI explanations may only cite numbers the program gives; Chinese and English reports have the same numbers and result fingerprint.
- **Your data stays on your computer**: only part names, volumes and the candidate joint list are sent to the AI.

## Free and Pro

| | Free | Pro |
| --- | :---: | :---: |
| Kinematics, statics and dynamics of rigid mechanisms (up to 15 parts) + checks | ✓ | ✓ |
| STEP import with joints drafted from the geometry; curves, animation | ✓ | ✓ |
| AI joint selection | | ✓ |
| Flexible parts, large-deformation beams | | ✓ |
| Contact, friction, clearance, gears, controllers, vibration modes | | ✓ |
| Formal reports (Word / PDF) | | ✓ |
| Price | Free | from $990 / year (see the sales plan) |

## Getting-started examples

1. **Slider-crank (Free)**: import the STEP file; the program drafts three revolute joints and one translational joint; crank at 1200 rpm: peak crank torque about 1.7 N·m, peak crank bearing reaction about 133 N.
2. **Two-joint arm (Pro)**: import the STEP file; the AI picks the shoulder and elbow joints; the shoulder turns 60° and the elbow −90° in 1 s; peak motor torques 1.79 N·m and 0.25 N·m (self-weight only); Chinese and English reports.
3. **Slender pushrod buckling (Pro)**: a pinned-pinned steel rod φ20 × 1000 mm; the first bending frequency under different compressive loads extrapolates to a buckling load of 16.0 kN, 0.4 % from Euler's formula.

## FAQ

- **Do I need to install FreeCAD?** No. FreeCAD 1.0.2, CalculiX and Gmsh are included.
- **No FreeCAD assembly?** Import a STEP file and let the program draft the joints, or write a model file.
- **Does the AI cost money?** You use your own DeepSeek or Claude key and pay the provider; every calculation works without AI.
- **How does it relate to WenQuest FEA?** Same code base, separate installers; one license file can enable both Pro editions (bundle price).
- **Can I use the results directly?** Results must be reviewed by a qualified engineer; the report includes a review checklist.
