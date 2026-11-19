# 例子 2：带型腔和孔的块（2.5 轴铣，免费版） / Example 2: block with a pocket and a hole (2.5-axis milling, free edition)

**零件**：`block.step`，100×60×30，顶面 40×20×8 的型腔，Ø8.5 通孔。材料 45 钢（C45E）。

**步骤**
1. 打开 `block.step`，选中零件，按“新建铣削作业”（零件包围盒当毛坯，毛坯就是零件外形）。
2. 作业面板里刀长填 `EM10=120, DR8.5=140`，工件顶面离工作台 40，夹具填 `10`（平口钳夹底下 10 mm）。
3. 按“规则起草”：铣型腔用 Ø10 立铣刀（型腔窄边 20 的一半），孔用 Ø8.5 钻头；刀路由 FreeCAD CAM 算，程序由问渠CAM 出。两道工序都是草稿，逐个双击确认。
4. 双击作业，按“计算并检查”：约 57.8 s（型腔分两层、之字形清中间再贴壁一圈），整机仿真通过（未知项：外来刀路没有目标形状，过切 / 残留看仿真结果）。通孔多钻一个钻尖长，孔底钻透。按“回放…”勾“色差”：型腔四个直角转角是蓝的——Ø10 立铣刀铣不到直角，检查清单里有一条“三维比对：多留”的提示。
5. 试一试：工具栏“新建工序”→“铣外轮廓”，确认后再算——铣到底的外轮廓会撞平口钳的钳口，整机仿真不通过，程序不出，检查清单里写着撞在哪一行。

**Part**: `block.step`, 100×60×30 with a 40×20×8 pocket in the top face and a Ø8.5 through hole. Material C45 steel (C45E).

**Steps**
1. Open `block.step`, select the part and press "New milling job" (the part's bounding box is the stock, i.e. the stock is the part outline).
2. In the job panel enter tool lengths `EM10=120, DR8.5=140`, workpiece top 40 above the table, fixture `10` (the vise grips the bottom 10 mm).
3. Press "Rule draft": a Ø10 end mill for the pocket (half the 20 mm narrow side) and a Ø8.5 drill for the hole; FreeCAD CAM computes the tool paths, WenQuest CAM writes the program. Both operations are drafts; double-click each to confirm.
4. Double-click the job and press "Calculate and check": about 57.8 s (the pocket in two levels, zigzag clearing plus a final pass along the walls); the machine simulation passes (unknown item: imported tool paths have no target shape, so check overcut / leftover material in the simulation result). The through hole is drilled one drill-point length deeper so it breaks through cleanly. Press "Replay…" and tick "Deviation": the four sharp pocket corners are blue — a Ø10 end mill cannot reach a sharp corner — and the check list has a "3D comparison: material left" warning.
5. Try this: on the toolbar choose "New operation" → "Contour milling", confirm it and recalculate — a contour milled to the bottom hits the vise jaws, the machine simulation fails, no program is released, and the check list says on which line it hits.
