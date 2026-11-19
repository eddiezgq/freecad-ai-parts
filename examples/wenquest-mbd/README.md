# 问渠多体动力学 · 入门例子 / WenQuest MBD · Getting-started examples

三个例子从零件或模型走到结果和报告。尺寸、材料、运动都是演示用的示例。
Three examples, each going from parts or a model to results and a report. Dimensions, materials and motions are examples for demonstration.

| 例子 Example | 版本 Edition | 怎么建 How it is built | 结果 Result |
| --- | --- | --- | --- |
| [01 曲柄滑块 / slider-crank](01-slider-crank-free/) | 免费版 Free | 导入 STEP，程序按几何起草运动副 / STEP import, joints drafted from geometry | 1200 rpm：曲柄驱动力矩峰值 1.71 N·m / peak crank torque 1.71 N·m |
| [02 两关节机械臂 / two-joint arm](02-arm-ai/) | 专业版 Pro | 导入 STEP，AI 挑运动副 / STEP import, AI joint selection | 肩 1.79 N·m、肘 0.25 N·m（峰值）/ shoulder 1.79 N·m, elbow 0.25 N·m (peak) |
| [03 细长推杆屈曲 / pushrod buckling](03-pushrod-buckling/) | 专业版 Pro | 模型文件（大变形梁）/ model files (large-deformation beam) | 屈曲载荷 16.03 kN，欧拉公式 15.97 kN（差 0.38 %）/ buckling load 16.03 kN vs Euler 15.97 kN (0.38 %) |

每个目录里有结果摘要（`results.json`）和中英报告样张（`sample-report.zh.pdf`、`sample-report.en.pdf`）。例子 1 的报告是专业版才出的，给免费版用户看专业版多了什么。
Each folder has a results summary (`results.json`) and sample reports in Chinese and English. The report of example 1 needs Pro; it shows free-edition users what Pro adds.

重新生成 / Rebuild（FreeCAD 自带的 Python / FreeCAD's Python）：

```
<FreeCAD 的 python / FreeCAD python> examples/wenquest-mbd/build_examples.py --out /tmp/WenQuest-MBD-examples [--samples]
```

例子 2 在仓库里用真实 AI 回复的录制回放（不联网）；你自己做时用自己的 AI 密钥，AI 起的名字和理由可能与样张略有不同，程序核对规则一样。
Example 2 replays a recorded real AI reply in this repository (offline). With your own AI key the AI's names and reasons may differ slightly; the program's checks are the same.
