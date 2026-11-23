# 问渠CAM 入门例子 / WenQuest CAM getting-started examples

前两个例子用免费版就能做（例子 3 五轴联动是专业版的功能范围，计算本身不受授权限制）；示例机床、示例刀具库都是虚构的，只用来演示。
The first two examples work in the free edition (example 3, simultaneous 5-axis, belongs to the Pro scope; the calculation itself is not licence-gated); the example machines and the example tool library are fictional and for demonstration only.

| 例子 Example | 内容 Contents |
| --- | --- |
| `01-shaft-turning` | 带螺纹的阶梯轴：新建车削作业读轮廓、规则起草、逐道确认、卡爪、两次装夹、FANUC 程序 / Threaded stepped shaft: read the profile, rule draft, confirm each operation, chuck jaws, two setups, FANUC programs |
| `02-block-milling` | 带型腔和孔的块：FreeCAD CAM 算刀路、平口钳、FANUC 程序 / Block with a pocket and a hole: FreeCAD CAM tool paths, vise, FANUC program |
| `03-cone-5axis` | 五轴联动侧刃铣圆锥台（NAS 979 简化）：直纹面刀位、摇篮式五轴整机仿真、刀尖跟随程序（西门子 TRAORI、FANUC G43.4）；不用 FreeCAD，`python examples/wenquest-cam/03-cone-5axis/build.py --save` / 5-axis swarf milling of a cone (simplified NAS 979): ruled-surface tool positions, trunnion 5-axis machine simulation, tool-tip control programs (Siemens TRAORI, FANUC G43.4); no FreeCAD needed |

每个文件夹里：零件 STEP、正式程序（.nc）、结果摘要 `results.json`、工艺卡样张（中英 PDF，工艺卡是专业版功能）。
重新生成：`<FreeCAD 的 python> examples/wenquest-cam/build_examples.py --samples`。
Each folder holds the part STEP, the released programs (.nc), a result summary `results.json` and sample process cards (Chinese and English PDF; the process card is a Pro feature).
Regenerate with `<FreeCAD python> examples/wenquest-cam/build_examples.py --samples`.
