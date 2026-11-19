# 例子 1：带螺纹的阶梯轴（车削，免费版） / Example 1: threaded stepped shaft (turning, free edition)

**零件**：`shaft.step`，轴线沿 Z、右端在上。外圆 Ø30×40、Ø40×60、Ø35×25、Ø24×30；Ø24 段根部 3 宽、底径 20 的退刀槽；右端 Ø16×20、Ø12×15 内孔。材料 45 钢（Kienzle 行 C45E，ISO P）。

**步骤**
1. 打开 `shaft.step`，切到“问渠CAM”工作台，在模型树里选中零件，按“新建车削作业”：读出外圆 4 段、槽一个、内孔两段，建好右端、左端两次装夹。
2. 螺纹在模型上没画，在作业面板“螺纹”里手填一行：`0, -26, 24, 1.5`（右端面起车 26 mm 的 M24×1.5，车到退刀槽里）。
3. 机床“示例数控车床（虚构）”，数控系统 FANUC，工件材料 C45E，夹具“15, 80”（卡爪夹左端 15 mm、外径 80）。
4. 按“规则起草”：右端 6 道（粗车、精车、切槽、车螺纹、钻孔、镗孔）、左端 2 道（粗车、精车）工序建在模型树里，都是草稿；刀和参数从示例刀具库按样本范围取中间值。
5. 在模型树里逐个双击工序，看过刀和参数后按 OK 确认。
6. 双击作业，按“计算并检查”：两次装夹各一个程序，合计约 2.6 min（右端 119.7 s、左端 38.6 s）。整机仿真“通过，有未知项”——未知项是车刀刀杆外形还没有数据，只查了刀尖。
7. 按“保存程序与工艺卡…”。程序头写着仿真指纹，以及“首件须空运行、单段试切”“后处理未经实机验证”。指纹也算进了零件名，零件名和 `results.json` 一样（“带螺纹的阶梯轴（示例）”）时指纹就一样。

**Part**: `shaft.step`, axis along Z with the right end up. OD Ø30×40, Ø40×60, Ø35×25, Ø24×30; a relief groove 3 wide, Ø20 at the root of the Ø24 section; bore Ø16×20 and Ø12×15 from the right end. Material C45 steel (Kienzle row C45E, ISO P).

**Steps**
1. Open `shaft.step`, switch to the "WenQuest CAM" workbench, select the part in the tree and press "New turning job": 4 OD sections, one groove and two bore sections are read, and two setups (right end, left end) are created.
2. Threads are not modelled; in the job panel's "Threads" enter one line: `0, -26, 24, 1.5` (M24×1.5 from the right end face, 26 mm long, running out into the groove).
3. Machine "示例数控车床（虚构）" (example lathe, fictional), control FANUC, material C45E, fixture "15, 80" (jaws grip 15 mm of the left end, outer diameter 80).
4. Press "Rule draft": 6 operations for the right end (rough and finish turning, grooving, threading, drilling, boring) and 2 for the left end (rough and finish turning) appear in the model tree as drafts; tools and cutting data come from the example library at the middle of the catalogue ranges.
5. Double-click each operation in the tree, check the tool and cutting data, and press OK to confirm.
6. Double-click the job and press "Calculate and check": one program per setup, about 2.6 min in total (right end 119.7 s, left end 38.6 s). The machine simulation "passes with unknown items" — the unknown item is that turning-tool holder shapes have no data yet, so only the tool tip is checked.
7. Press "Save programs and process card…". The program header carries the simulation fingerprint, "first part: dry run and single block" and "post not verified on a real machine". The fingerprint includes the part name; with the same name as in `results.json` ("带螺纹的阶梯轴（示例）") it is identical.
