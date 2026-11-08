# 问渠电子 WenQuest Electronics（`eda/`）

AI 原生电子设计与制造平台的本体（方案：`docs/方案/AI原生电子设计与制造平台.md`）。KiCad 是母体，源码不动；设计的源头是一份四层的**设计描述**（YAML），KiCad 文件由它生成。

| 目录 | 内容 |
|---|---|
| `wqeda/schema/design.py` | 设计描述格式（L1 规格、L2 功能块、L3 电路、L4 板子）：读、校验、展开（变体、按规则生成的测试点） |
| `wqeda/schema/capability.py` | 工厂工艺能力表格式：读、校验；没填的项是“未知” |
| `wqeda/model.py` | 板子模型：检查引擎的中间数据（KiCad 板子文件和光绘文件都变成它） |
| `wqeda/readers/` | 两条入口：`kicad.py`（pcbnew）、`gerber.py`（gerbonara + 物料清单 + 坐标） |
| `wqeda/checks/` | 判定：纯函数，不联网、不调 AI。`basic.py` 第一批六项；`process.py` 工艺检查补齐（F2 线距、F4 阻焊桥、F6 器件外框、F7 极性、F8 器件到板边、T1 ICT 覆盖、C1 大电流线宽）；`layout.py` 布局约束（第 111 轮） |
| `wqeda/schema/board.py` | 板子层新字段（第 111 轮）：网络分类、叠层、设计规则、热分析条件、布局约束 |
| `wqeda/gen/board.py` | 通用板子生成（第 111 轮）：L4 → KiCad 板子 → Freerouting 自动布线 |
| `wqeda/geom.py` | 几何：走线、焊盘、铺铜、光绘图元变多边形，量间距、看连通 |
| `wqeda/thermal/` | 板子热分析：`board.py` 损耗与结温判定，`plate.py` 平板模型（CalculiX 输入），`ccx.py` 调 CalculiX |
| `wqeda/readback.py` | KiCad 手工改动读回：`python3 -m wqeda.readback <板子.kicad_pcb> <design.yaml> [--write 新文件]` |
| `wqeda/report.py` | 一份报告（电气、工艺、热）：`python3 -m wqeda.report <设计或变体> --factory <工艺能力表> --out <目录>` |
| `wqeda/model_io.py` | 板子模型存成文件（起草台服务器上没有 KiCad 时用） |
| `wqeda/factory.py` | 工厂端检查（第 112 轮）：资料包 → 编号的检查结果、数量统计；`checks/assembly.py` 板子尺寸、最小引脚间距、最小焊盘 |
| `wqeda/quantity.py` | 数量统计（报价依据，只算量） |
| `wqeda/issues.py` | 问题单格式；`python3 -m wqeda.issues <问题单.yaml> <design.yaml> [--gerber … --bom … --cpl … --factory …]` 对到设计描述、判已解决 |
| `wqeda/package.py` | 由设计描述导出物料清单和贴片坐标：`python3 -m wqeda.package <设计或变体> --out <目录>` |
| `examples/pcba-demo/` | 工厂端演示资料包（故意漏了 C47 的物料编号，标明） |
| `wqeda/readers/kicad_ipc.py` | 从 KiCad 9 的进程间接口（kicad-python）读编辑器里打开着的板子，出同样的板子模型（第 113 轮插件用） |
| `kicad-plugin/` | KiCad 9 插件（第 113 轮）：`plugin.json`、`check.py`、本机结果页 `wq_kicad/`；`python3 eda/kicad-plugin/pack.py <zip>` 打包（服务里 `/eda/api/kicad-plugin.zip` 现场打包）；CI `.github/workflows/eda-plugin.yml` 装 KiCad 9 跑真插件 |
| `examples/factories/` | 演示工厂的工艺能力表（虚构，数值为示例值） |
| `tests/` | `python3 -m pytest -q eda/tests`（读 KiCad 文件的测试要 KiCad 7 的 pcbnew，没有就跳过） |

第一个例子：关节伺服驱动板 `factory/designs/drv-joint/design.yaml`（A 版）与 `factory/designs/drv-joint-b/variant.yaml`（B 版改动清单）；`factory/designs/tools/drv_joint.py` 读它们，`build.py` 照旧生成 KiCad 工程和产物。

## 布局约束怎么写（第 111 轮）

写在设计描述 `board.constraints`，每条有 `key`、`kind`、`name`、`source`（出处；没有出处写“示例值”）：

| kind | 字段 | 量什么 |
|---|---|---|
| `loop` | `refs`、`nets`、`max_area_mm2` | 这些器件在这些网络上的焊盘中心围成的面积（凸包） |
| `kelvin` | `ref`、`ties` | 每个网络连接点（net tie）都落在采样电阻 `ref` 的焊盘上 |
| `near` | `ref`、`to`、`pin`、`max_mm` | `ref` 接在同一网络上的焊盘到 `to` 第 `pin` 脚（焊盘边到边） |
| `apart` | `hot`、`cold`、`min_mm` | 两组器件外框之间最近的距离 |
| `edge` | `refs`、`max_mm` | 器件外框到板边的距离 |

驱动板的报告：`factory/designs/drv-joint/report/report.html`；24 V 示例：`eda/examples/drv-joint-24v/report/report.html`。
板子改了以后重新写板子模型文件：`python3 -m wqeda.model_io factory/designs/drv-joint/kicad/drv-joint.kicad_pcb factory/designs/drv-joint/report/board-model.json.gz`（测试会核对）。
