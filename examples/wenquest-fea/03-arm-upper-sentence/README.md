# 例子 3 · 大臂 ARM-UPPER（专业版）/ Example 3 · Upper arm ARM-UPPER (Pro)

**中文**

1. 打开 `ARM-UPPER.step`，选中零件，点 **一句话起草（AI）**，写：

   > 大臂 ARM-UPPER，6061-T6。肩部 Ø138 减速器座固定；肘部 Ø107 减速器座上加 j3 峰值扭矩 46.4 N·m。

2. AI 追问四处：扭矩转向；要不要算自重；肩部固定的是 Ø138 孔壁（F6）还是安装台阶面；有没有末端负载。
   这些都是原话没说清的地方——AI 不猜，问你。按实际情况在 FEM 里补（比如加重力），或判断不需要，勾选“追问都已处理”，确认。
3. **计算并核查** → **出报告**。

结果：整体可信度 **不通过**，原因与例子 2 相同（固定孔壁边缘的应力奇异点，8.6 → 10.3 → 13.6 MPa）；另有一项网格质量“未知”：
曲面上二阶单元太扭曲，改用了直边单元，软件提示把网格调细。最大位移 0.106 mm 已经收敛。

**English**

1. Open `ARM-UPPER.step`, select the part, click **Draft from one sentence (AI)** and write:

   > Upper arm ARM-UPPER, 6061-T6. The Ø138 reducer seat at the shoulder is fixed; a j3 peak torque of 46.4 N·m acts on the Ø107 reducer seat at the elbow.

2. The AI asks four questions: torque direction; whether to include self-weight; whether the shoulder is fixed on the Ø138 bore wall (F6) or the mounting shoulder; whether there is an end load. These are things the sentence left open, so the AI asks instead of guessing. Add what applies in FEM (gravity, for example) or decide it is not needed, tick "All questions handled", and confirm.
3. **Compute and check** → **Report**.

Result: overall credibility **fail**, for the same reason as example 2 (a stress singularity at the edge of the fixed bore, 8.6 → 10.3 → 13.6 MPa). Mesh quality is also "unknown": second-order elements on curved faces were too distorted, so straight-sided elements were used and the software suggests a finer mesh. The max displacement, 0.106 mm, has converged.
