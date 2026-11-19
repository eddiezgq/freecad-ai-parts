# 问渠CAM 入门例子 / WenQuest CAM getting-started examples

两个例子都用免费版就能做；示例机床、示例刀具库都是虚构的，只用来演示。
Both examples work in the free edition; the example machines and the example tool library are fictional and for demonstration only.

| 例子 Example | 内容 Contents |
| --- | --- |
| `01-shaft-turning` | 带螺纹的阶梯轴：从模型读轮廓、规则起草、卡爪、两次装夹、FANUC 程序 / Threaded stepped shaft: read the profile, rule draft, chuck jaws, two setups, FANUC programs |
| `02-block-milling` | 带型腔和孔的块：FreeCAD CAM 算刀路、平口钳、FANUC 程序 / Block with a pocket and a hole: FreeCAD CAM tool paths, vise, FANUC program |

每个文件夹里：零件 STEP、正式程序（.nc）、结果摘要 `results.json`、工艺卡样张（中英 PDF，工艺卡是专业版功能）。
重新生成：`<FreeCAD 的 python> examples/wenquest-cam/build_examples.py --samples`。
Each folder holds the part STEP, the released programs (.nc), a result summary `results.json` and sample process cards (Chinese and English PDF; the process card is a Pro feature).
Regenerate with `<FreeCAD python> examples/wenquest-cam/build_examples.py --samples`.
