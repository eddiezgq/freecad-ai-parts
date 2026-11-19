# 例子 2 · 两关节机械臂（专业版） / Example 2 · Two-joint arm (Pro)

底座（立柱 + 底板）、大臂（肩到肘 300 mm）、小臂，铝合金（FreeCAD 材料库 Aluminum-6061-T6）。两个关节轴线水平，手臂在竖直面里转，受重力。
Base (column and plate), upper arm (300 mm shoulder to elbow), forearm, aluminum (FreeCAD material Aluminum-6061-T6). Both joint axes are horizontal; the arm turns in a vertical plane under gravity.

## 步骤 / Steps

1. 勾“用 AI 起草”，点“导入 STEP 并起草运动副…”，选 `arm.step`。程序找出两个转动副（Ø20、Ø16 的轴孔同轴），AI 起名“肩关节”“肘关节”、选底座作机架，并提醒核对轴向是否限位。点“确认，建成装配体”。
   Tick "Draft with AI", "Import STEP and draft joints…", pick `arm.step`. The program finds two revolute joints (Ø20 and Ø16 coaxial shafts and holes); the AI names them shoulder and elbow, picks the base as ground and asks you to check the axial restraint. Confirm.
2. 三个零件设材料 Aluminum-6061-T6，点“用当前文档的装配体”（或打开 `arm.FCStd`）。
   Set Aluminum-6061-T6 on the three parts and click "Use the assembly in the current document" (or open `arm.FCStd`).
3. 驱动都选“位移函数”：肩关节 `60*(time - sin(2*pi*time)/(2*pi))`，肘关节 `-90*(time - sin(2*pi*time)/(2*pi))`（1 s 内转 60°、−90°，起止速度和加速度为零）。分析：运动学，1 s，100 点。计算，再“写计算报告…”。
   Both drives "displacement function": shoulder `60*(time - sin(2*pi*time)/(2*pi))`, elbow `-90*(time - sin(2*pi*time)/(2*pi))` (60° and −90° in 1 s, zero velocity and acceleration at both ends). Kinematic, 1 s, 100 points. Compute, then "Write report…".

## 结果 / Results（`results.json`）

| 量 Quantity | 峰值 Peak |
| --- | --- |
| 肩关节电机力矩 / shoulder motor torque | 1.79 N·m |
| 肘关节电机力矩 / elbow motor torque | 0.25 N·m |

这两个数就是选电机、减速器的依据（这里只有自重，没有负载）。核查：约束残差、自由度都通过。
These are the numbers for sizing motors and gearboxes (self-weight only, no payload). Checks: constraint residual and degrees of freedom pass.
