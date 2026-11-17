# WenQuest FEA · Product page content (English)

For the product page under "Enterprise solutions" on the WenQuest website (the page itself is built in the website repository). Only what the software really does; numbers come from the verification manual and the getting-started examples.

## Hero

**One sentence to a stress report.**

Select a part in FreeCAD and write "45 steel, quenched and tempered; fix the end face on the Ø70 flange; 92.5 N·m peak torque on the spline." AI drafts the constraints and loads, the program checks every item, and you confirm. Every solve is checked for mesh convergence, reaction balance and singularities, and ends in a report a reviewer can sign off.

Buttons: Download free (Windows) · See a sample report

## Three buttons

1. **Draft from one sentence**: AI places constraints and loads from your words. Any proposal whose face cannot be found, whose numbers don't match your sentence or whose direction makes no sense is dropped; where AI is unsure, it asks. Unconfirmed studies cannot be solved.
2. **Compute and check**: three meshes from coarse to fine show whether results converge; loads are checked against reactions; the peak stress is checked for a sharp-corner singularity. The verdict is pass, fail or unknown — no safety factor without a pass.
3. **Report**: Word / PDF, in English or Chinese, with conclusions, the study and its basis, material sources, checks, contour plots, a reviewer checklist and result fingerprints. Every number is filled in by the program.

## Why you can trust it

- **42 benchmark problems, 64 comparisons, all within tolerance**: cantilever, thick-walled cylinder, stress concentration at a hole, NAFEMS LE1 / LE10 / FV52, Euler column, Hertz contact, plasticity, large deformation, harmonic response and more. The verification manual ships with the software; every number in it was computed by that version's tests.
- **AI drafts, never decides**: pass or fail is always decided by the program and an engineer.
- **Materials with sources**: every value in the material library cites GB/T, ASTM or a handbook; Chinese and US grades (45, 40Cr, Q235, Q355, 6061-T6, 7075-T6, 304 and more).
- **Your data stays on your computer**: only your sentence and the list of part features go to the AI.

## Free and Pro

| | Free | Pro |
| --- | :---: | :---: |
| Static, modal, buckling of a single part, with checks | ✓ | ✓ |
| Thermal analysis, fatigue life | ✓ | ✓ |
| AI drafting and explanation | | ✓ |
| Formal report (Word / PDF) | | ✓ |
| Multi-part contact, bolts, plasticity, large deformation, vibration, shells, beams, load combinations | | ✓ |
| Price | Free | from $990 / year (final per the sales plan) |

## Getting-started examples

1. Joint housing J2-HSG: built with the FEM tools; runs in the free edition (credibility: pass).
2. Shoulder hollow shaft RJ-201: one sentence for a torque case → reports in English and Chinese.
3. Robot upper arm ARM-UPPER: one sentence; AI asks four questions; answer, confirm → report.

The reports for examples 2 and 3 conclude "fail": the stress at the sharp edge of the fixed face keeps rising as the mesh is refined, so the software flags a singularity, gives no safety factor, and says what to change. That is exactly what sets it apart from software that only draws a colorful contour plot.

## FAQ

- **Do I need to install FreeCAD separately?** No. The installer includes FreeCAD 1.0.2, CalculiX and Gmsh.
- **Does the AI cost extra?** You use your own DeepSeek or Claude key and pay the provider's rates; every solver feature works without AI.
- **Can I use the results directly?** Results must be reviewed by a qualified engineer; every report includes a reviewer checklist.
