# 例子 2：带型腔和孔的块（2.5 轴铣，免费版） / Example 2: block with a pocket and a hole (2.5-axis milling, free edition)

**零件**：`block.step`，100×60×30，顶面 40×20×8 的型腔，Ø8.5 通孔。材料 45 钢（C45E）。

**步骤**
1. 打开 `block.step`，在“数控编程”面板里加工方式选“铣削”，选中零件按“从选中零件读取”。
2. 铣削工序只勾“型腔”“钻孔”（毛坯就是零件外形，不铣外轮廓）。刀长填 `EM10=120, DR8.5=140`，工件顶面离工作台 40，夹具填 `10`（平口钳夹底下 10 mm）。
3. 按“规则起草”：型腔用 Ø10 立铣刀（型腔窄边 20 的一半），孔用 Ø8.5 钻头；刀路由 FreeCAD CAM 算，程序由问渠CAM 出。
4. 按“计算并检查”：约 29.7 s，整机仿真通过（未知项：外来刀路没有目标形状，过切 / 残留看仿真结果）。
5. 试一试：把“外轮廓”也勾上再算——铣到底的外轮廓会撞平口钳的钳口，整机仿真不通过，程序不出，检查清单里写着撞在哪一行。

**Part**: `block.step`, 100×60×30 with a 40×20×8 pocket in the top face and a Ø8.5 through hole. Material C45 steel (C45E).

**Steps**
1. Open `block.step`; in the "CNC programming" panel choose "Milling", select the part and press "Read from the selected part".
2. Tick only "Pocket" and "Drilling" (the stock is the part outline, so no contour). Tool lengths `EM10=120, DR8.5=140`, workpiece top 40 above the table, fixture `10` (the vise grips the bottom 10 mm).
3. Press "Rule draft": a Ø10 end mill for the pocket (half the 20 mm narrow side) and a Ø8.5 drill for the hole; FreeCAD CAM computes the tool paths, WenQuest CAM writes the program.
4. Press "Calculate and check": about 29.7 s; the machine simulation passes (unknown item: imported tool paths have no target shape, so check overcut / leftover material in the simulation result).
5. Try this: tick "Contour" as well and recalculate — a contour milled to the bottom hits the vise jaws, the machine simulation fails, no program is released, and the check list says on which line it hits.
