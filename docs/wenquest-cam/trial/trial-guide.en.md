# WenQuest CAM trial guide

Thank you for trying WenQuest CAM. The purpose of the trial is to find problems: wrong results, places where you get stuck, things that are awkward,
and differences from how your shop works. **Every problem you find helps us**, however small it seems.

## 1. Installation

1. Run `WenQuest-CAM-Setup-<version>.exe` (Windows 10 / 11, 64-bit; FreeCAD and all components are included).
2. Start "WenQuest CAM" from the Start menu; the first start opens the WenQuest CAM workbench.
3. The Start menu also has the user guide, the verification manual and the getting-started examples.

## 2. The two getting-started examples (half an hour)

Follow the two "first steps" chapters of the user guide:

- Example 1: a stepped shaft (two setups, groove, thread);
- Example 2: a block with a pocket and holes.

For each: draft → confirm operations → calculate and check → replay → save programs and process card. Compare your program with the sample in the example folder.

## 3. What to try, by role

**Training course participants** (focus: can you use it, can you understand it)

- [ ] Take a turned part you modelled yourself from model to program;
- [ ] Take a 2.5-axis milled part you modelled yourself (pocket, contour, holes, tapped holes) from model to program;
- [ ] Replay: drag the slider; does the program window follow the tool?
- [ ] Open the process card: are the part, setup and tool drawings clear, are the numbers the ones you set?
- [ ] For every red, amber and grey item in the check list: do you know what to do?

**Partner shop process engineers** (focus: are the results right, can they be used directly)

- [ ] Create your machines in the "Machines" window and your usual tools in the "Tool library" window;
- [ ] Write a post configuration in your shop's style (user guide, "Post configurations"), or send us one of your programs and we write it;
- [ ] Program a part your shop is making now and use "Compare programs…" in the job panel against your current program: tools, speeds, feeds, time;
- [ ] Could the process card go to the shop floor as it is? What is missing, what is superfluous?
- [ ] On the machine: **always dry-run and single-block the first part**. Note the real time and the time the software calculated.

## 4. When something goes wrong

1. In the WenQuest CAM menu choose "Feedback…";
2. Write a few words: what you did, what went wrong, what you expected (send screenshots separately if you have them);
3. Press "Make feedback package…" and choose a folder; a `wenquest-cam-feedback-<date>-<time>.zip` is created;
4. Send the zip to us (WeChat or e-mail).

The package contains your description, software and system versions, a copy of the current document, your tool library / machine / post
configurations and the error text. **It does not contain your license file.** If the part model is confidential, tell us first and we will find
another way (for example a similar part that shows the same problem).

We log every report in the issue list and tell you which version fixes it.
