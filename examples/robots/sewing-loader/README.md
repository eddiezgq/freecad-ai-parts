# 案例 B：缝纫车间裁片上下料机器人（ADR-0115 44.5）

`requirement.txt` 是需求原话。现在做到 **44.5.1 构型初筛**（回放 CI 上 Claude 的录制，不调用真实 AI）：

```bash
python -m assist.robot_design examples/robots/sewing-loader/requirement.txt --screen-only -o examples/robots/sewing-loader/out/concept-result.json
```

| 文件 | 内容 |
| --- | --- |
| `out/concept-result.json` | AI 摘的条件（带原话引用；节拍与取放条件单独问一次）、AI 的问题、每轮构型与初筛（取放距离、同高、一叠最高处够不够得着、节拍）、采用哪个 |

第 1 轮 AI 提了两个构型：台面上的 X–Z 两轴龙门（真空吸盘）、偏置底座的 SCARA。龙门全部通过初筛（节拍 2.8 s ≤ 3 s），采用；
SCARA 的取料点、放料点在关节行程内够不着。还没判的（选件后判）：节拍要的末端最高速度 2.5 m/s、加速度 12.5 m/s²，
直线模组做不做得到；抓取力至少 4.46 N；重复定位精度 ±1 mm。

后面几步（ADR-0115 44.5.2–44.5.5）：直线模组与抓手的零件类别、整本导入公开目录、选件与末端比较、三维装配、一个节拍的多体动力学、横梁有限元、报告与 BOM。
