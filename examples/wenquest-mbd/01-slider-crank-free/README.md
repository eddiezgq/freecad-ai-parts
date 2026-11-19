# 例子 1 · 曲柄滑块（免费版） / Example 1 · Slider-crank (Free)

曲柄半径 30 mm、连杆中心距 100 mm，钢（FreeCAD 材料库 Steel-Generic）。机架上有轴承座和导轨。
Crank radius 30 mm, connecting rod 100 mm between centers, steel (FreeCAD material Steel-Generic). The frame carries a bearing block and a guide.

## 步骤 / Steps

1. 菜单“问渠多体动力学 → 装配体多体动力学”，点“导入 STEP 并起草运动副…”，选 `slider-crank.step`（不勾“用 AI 起草”）。
   程序找出 4 个运动副：机架–曲柄、曲柄–连杆、连杆–滑块三个转动副（同轴的销和孔），机架–滑块一个移动副（两组贴合平面，只剩沿 x 能滑）；机架选“机架”。点“确认，建成装配体”。
   Menu WenQuest MBD > Assembly multibody dynamics, "Import STEP and draft joints…", pick `slider-crank.step` (no AI). The program finds four joints: three revolute (frame–crank, crank–rod, rod–slider: coaxial pins and holes) and one translational (frame–slider: two pairs of mating planes, only x is free). Ground: the frame. Click "Confirm and build the assembly".
2. 给四个零件设材料（零件属性 ShapeMaterial → Steel-Generic），点“用当前文档的装配体”。或者直接打开 `slider-crank.FCStd`（装配体和材料都已设好），点“用当前文档的装配体”。
   Give the four parts a material (property ShapeMaterial > Steel-Generic) and click "Use the assembly in the current document". Or open `slider-crank.FCStd`, where assembly and materials are ready.
3. 驱动：机架–曲柄的转动副选“匀速”，1200 rpm。分析：运动学，时长 0.05 s（一圈），输出点数 200。点“计算”。
   Drive the frame–crank joint at constant speed 1200 rpm. Analysis: kinematic, 0.05 s (one turn), 200 output points. Compute.

## 结果 / Results（`results.json`）

| 量 Quantity | 峰值 Peak |
| --- | --- |
| 曲柄驱动力矩 / crank drive torque | 1.71 N·m |
| 反力 机架–曲柄 / reaction frame–crank | 133 N |
| 反力 曲柄–连杆 / reaction crank–rod | 121 N |
| 反力 连杆–滑块 / reaction rod–slider | 89 N |
| 反力 机架–滑块（导轨）/ reaction frame–slider (guide) | 16 N |

核查：约束残差、自由度都通过。反力里冗余约束方向的分量不唯一，状态栏和报告里写明是哪些方向。
Checks: constraint residual and degrees of freedom pass. Reaction components along removed redundant constraints are not unique; the status line and the report say which.
