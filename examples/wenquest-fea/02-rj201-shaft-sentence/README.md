# 例子 2 · 肩关节空心轴 RJ-201（专业版）/ Example 2 · Shoulder hollow shaft RJ-201 (Pro)

**中文**

1. 打开 `RJ-201.step`，在模型树里选中零件，切到 FEM 工作台，点 **一句话起草（AI）**。
2. 写：

   > 肩关节空心轴 RJ-201，45 钢调质。Ø70 法兰那一端的端面固定，在 Ø42.75 花键段上加峰值扭矩 92.5 N·m。

3. 点 **起草**。AI 会追问两处：固定面是 F6（z = 0 的端面）还是 F8（法兰台阶面）；扭矩转向。在三维视图里核对，勾选“追问都已处理”，填确认人，点 **确认算例**。
4. 点 **计算并核查**，再点 **出报告**（中文或英文）。

结果：整体可信度 **不通过**。最大应力随网格加密一直增大（23.5 → 25.5 → 30.1 MPa），软件判为固定面边缘尖角处的应力奇异点，不给安全系数。
这不是软件出错：固定面是完全刚性的理想约束，它的边缘是尖角。实际设计时，改用更接近真实的支承（比如在法兰上做螺栓连接、用圆柱面支承），
或者看远离固定边缘的应力。最大位移 0.0039 mm 已经收敛，刚度结论可用。报告样张里写了这些。

**English**

1. Open `RJ-201.step`, select the part in the tree, switch to the FEM workbench and click **Draft from one sentence (AI)**.
2. Write (the AI also accepts English):

   > Shoulder hollow shaft RJ-201, 45 steel quenched and tempered. Fix the end face on the Ø70 flange end and apply a peak torque of 92.5 N·m on the Ø42.75 spline section.

3. Click **Draft**. The AI asks two questions: whether the fixed face is F6 (the end face at z = 0) or F8 (the flange shoulder), and the torque direction. Check in the 3D view, tick "All questions handled", enter who confirms and click **Confirm study**.
4. Click **Compute and check**, then **Report** (English or Chinese).

Result: overall credibility **fail**. The peak stress keeps rising as the mesh is refined (23.5 → 25.5 → 30.1 MPa); the software flags a stress singularity at the sharp edge of the fixed face and gives no safety factor. This is not a software error: a fully rigid fixed face is an idealized support with a sharp edge. In a real design, use a more realistic support (bolts on the flange, a cylindrical support) or judge stresses away from the fixed edge. The max displacement, 0.0039 mm, has converged, so the stiffness result is usable. The sample report says all this.

（仓库里的样张用的是中文那句话的录制回放。The samples in this repository replay the recording for the Chinese sentence.）
