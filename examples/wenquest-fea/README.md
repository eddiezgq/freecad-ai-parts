# 问渠有限元 · 入门例子 / WenQuest FEA · Getting-started examples

三个例子都是机器人关节零件，每个从零件走到结果和报告。载荷是演示用的示例工况，不是零件的规格参数。
All three examples are robot-joint parts, each going from the part to results and a report. The loads are example load cases for demonstration, not part specifications.

| 例子 Example | 版本 Edition | 怎么建 How it is built | 可信度 Credibility |
| --- | --- | --- | --- |
| [01 关节壳体 J2-HSG / joint housing](01-j2-housing-free/) | 免费版 Free | FEM 工具手建 / FEM tools by hand | 通过 pass |
| [02 肩关节空心轴 RJ-201 / shoulder hollow shaft](02-rj201-shaft-sentence/) | 专业版 Pro | 一句话起草 / one sentence | 不通过 fail（奇异点 singularity） |
| [03 大臂 ARM-UPPER / upper arm](03-arm-upper-sentence/) | 专业版 Pro | 一句话起草，AI 追问 4 处 / one sentence, 4 AI questions | 不通过 fail（奇异点 singularity） |

每个目录里有零件 STEP 和中英报告样张（`sample-report.zh.pdf`、`sample-report.en.pdf`）。例子 1 的报告是专业版才出的，给免费版用户看专业版多了什么。
Each folder has the part STEP file and sample reports in Chinese and English. The report of example 1 needs Pro; it shows free-edition users what Pro adds.

重新生成 / Rebuild（FreeCAD 自带的 Python / FreeCAD's Python）：

```
<FreeCAD 的 python / FreeCAD python> examples/wenquest-fea/build_examples.py --out /tmp/WenQuest-FEA-examples [--samples]
```

例子 2、3 在仓库里用真实 AI 回复的录制回放（不联网）；你自己做时用自己的 AI 密钥，AI 的说法可能与样张略有不同，程序核对规则一样。
Examples 2 and 3 replay recorded real AI replies in this repository (offline). When you do them yourself with your own AI key, the AI's wording may differ slightly from the samples; the program's checks are the same.
