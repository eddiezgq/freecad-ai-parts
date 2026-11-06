# 问渠电子 WenQuest Electronics（`eda/`）

AI 原生电子设计与制造平台的本体（方案：`docs/方案/AI原生电子设计与制造平台.md`）。KiCad 是母体，源码不动；设计的源头是一份四层的**设计描述**（YAML），KiCad 文件由它生成。

| 目录 | 内容 |
|---|---|
| `wqeda/schema/design.py` | 设计描述格式（L1 规格、L2 功能块、L3 电路、L4 板子）：读、校验、展开（变体、按规则生成的测试点） |
| `wqeda/schema/capability.py` | 工厂工艺能力表格式：读、校验；没填的项是“未知” |
| `wqeda/model.py` | 板子模型：检查引擎的中间数据（KiCad 板子文件和光绘文件都变成它） |
| `wqeda/readers/` | 两条入口：`kicad.py`（pcbnew）、`gerber.py`（gerbonara + 物料清单 + 坐标） |
| `wqeda/checks/` | 判定：纯函数，不联网、不调 AI |
| `examples/factories/` | 演示工厂的工艺能力表（虚构，数值为示例值） |
| `tests/` | `python3 -m pytest -q eda/tests`（读 KiCad 文件的测试要 KiCad 7 的 pcbnew，没有就跳过） |

第一个例子：关节伺服驱动板 `factory/designs/drv-joint/design.yaml`（A 版）与 `factory/designs/drv-joint-b/variant.yaml`（B 版改动清单）；`factory/designs/tools/drv_joint.py` 读它们，`build.py` 照旧生成 KiCad 工程和产物。
