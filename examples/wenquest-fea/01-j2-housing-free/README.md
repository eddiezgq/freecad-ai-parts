# 例子 1 · 关节壳体 J2-HSG（免费版）/ Example 1 · Joint housing J2-HSG (Free)

**中文**

只用 FreeCAD FEM 工作台自己的工具建分析，免费版就能算。

1. 打开 `J2-HSG.FCStd`（分析已经建好：CalculiX 求解器为静力；底面（z = 0）固定；Ø110 减速器座孔面受 +x 方向 2000 N 的力——示例载荷）。
   想自己从头建：打开 `J2-HSG.step`，按用户手册“用法一”做。
2. 切到 FEM 工作台，点 **计算并核查**，材料选 **6061-T6**（与零件实际材料一致）。
3. 算完弹出结论：整体可信度 **通过**。结果在“分析”节点下，用 FEM 的结果工具看 von Mises 应力和变形。

参考结果（本仓库生成样张时）：最大位移 0.0012 mm，最大 von Mises 应力 0.55 MPa，安全系数约 499（按屈服强度）。
这个壳体是实心块加一个 Ø110 通孔，对 2000 N 的径向力很富余；换成你自己的零件和载荷再算。

**English**

Built only with FreeCAD FEM workbench tools; runs in the free edition.

1. Open `J2-HSG.FCStd` (the analysis is ready: CalculiX solver set to static; the bottom face (z = 0) fixed; a 2000 N force in +x on the Ø110 reducer bore — an example load). To build it yourself, open `J2-HSG.step` and follow "Way 1" in the user guide.
2. Switch to the FEM workbench, click **Compute and check**, and choose **6061-T6** (the part's actual material).
3. When it finishes, the overall credibility verdict is **pass**. Results are under the analysis node; use FEM's result tools for von Mises stress and deformation.

Reference results (when the samples were generated): max displacement 0.0012 mm, max von Mises stress 0.55 MPa, safety factor about 499 (on yield strength). The housing is a solid block with a Ø110 bore, so it has a large margin for 2000 N; try your own part and loads.
