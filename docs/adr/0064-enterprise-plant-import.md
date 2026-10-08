# ADR-0064：企业车间布局与公司资料导入（M16）

- 状态：已接受（2026-10-08，项目负责人：“好，继续”）
- 日期：2026-10-08
- 补充：ADR-0061（工厂接收新产品）、ADR-0063（企业安装版）

## 背景

M15 后企业可以装上自己的数字工厂，产品方案也能经“转为生产物料”进来，但工厂本身仍是演示的“问渠减速器厂”：
摸底（2026-10-08）发现工厂模型写死在约 12 处代码里，同一台设备有三种叫法（ERP 工作站名“数控车床 CNC-L01”、
单元编号 `cnc-l01-a`、工序名“粗车 Rough turning”），只有 `wqbus/topics.UNITS` 的第 4 项把它们连起来：

| 关注点 | 写死的地方 |
| --- | --- |
| 公司 | `hub/mrp.COMPANY`、本体的工厂对象、AI 提示词里的厂名；ERPNext 设置向导（美国、美元） |
| 工作站、工序 | `factory/data.py` 的 `WORKSTATIONS`、`OPERATIONS`、`INSPECTION_OPS`、`ROUTINGS`（标准工时） |
| 设备（单元） | `wqbus/topics.py` 的 `UNITS`、`MACHINES`；`sim/engine.py` 的 `OP_UNITS` 与产能、准备时间、刀具磨损等 |
| 车间平面 | `wqbus/layout.py` 的 `LAYOUT`、`FLOOR`、`AGV_HOME`、`AISLES`；网页 `workshop3d.js` 的设备高度 |
| 班次、指标 | `sim/calendar.py`、`data.SHIFT`、`hub/kpi.py` 的 `SHIFT_MIN`、`TARGET` |
| 客户、供应商、物料 | `factory/data.py`（新产品经 `hub/products.py` 并入） |

## 决策

1. **一份工厂清单**（`plant.yaml`）描述一座工厂：公司（名称、缩写、国家、币种、时区）、工作站（台数、费率）、
   设备单元（编号、区域、中文 / 英文名、所属工作站、仿真参数、平面位置与尺寸、高度）、工序（所用工作站、可用设备、
   阶段、是否检验）、车间平面（长宽、通道、物流小车停靠点）、班次与加班上限、指标目标、客户与供应商（可选）。
   - 演示工厂导出成 `factory/plants/wenquest-gearbox.yaml`，作为缺省；用它加载时，工厂的全部行为与现在完全一样
     （测试逐项比对导出前后的常量）。
   - 环境变量 `WQ_PLANT_FILE` 指定企业的清单；`data.py`、`topics.py`、`engine.py`、`layout.py`、`calendar.py`、`kpi.py`
     在导入时从清单取值（同一份数据，不再各写一份）。
   - 总线主题根 `wq/gearbox` 是内部标识，不随工厂改（改它要动约 30 处，对企业无可见差别）。
   - 仓库按固定的五类（原材料、外购件、半成品、在制品、成品）加公司缩写命名，不在清单里配。
2. **校验**：加载清单时逐项核对（工序用到的工作站存在、每台设备有位置、编号不重复、工作站至少一台设备……），
   出错说清是哪一行哪一项，不带病启动。
3. **Excel 模板与导入命令**：`python -m factory.plant template 输出.xlsx` 生成模板（演示工厂填好作样例），
   企业按表填好后 `python -m factory.plant import 填好的.xlsx 输出.yaml` 转成清单并校验；
   `python -m factory.plant check plant.yaml` 只校验。
4. **企业安装**：`install.sh --plant plant.yaml` 把清单放到安装目录、挂进容器（`WQ_PLANT_FILE`）；
   ERPNext 设置向导按清单的公司、国家、币种、时区建公司；主数据导入（`seed.py`）按清单建工作站、工序。
   `upgrade.sh --plant` 换清单后重启。
5. **随工厂变的文字**：AI 提示词、本体的工厂对象、网页标题用清单里的公司名；`hub/mrp.COMPANY` 改为清单的公司。
   只服务教学的页面（输出轴设计台、实验 15、虚拟 PLC 示例等）仍以演示工厂为准，企业工厂里不显示。
6. **验收**：
   - 演示工厂：所有现有测试不改断言通过；CI 照常。
   - 一座示例企业工厂（`factory/plants/example-sewing.yaml`：示例缝纫机厂，人民币、上海时区、8 个工作站、
     不同的设备与平面）：CI 的企业安装作业用它装，跑平缝机的工厂一侧全流程（工序名与演示工厂相同的那些，
     设备与平面不同）。

## 后果

- 企业交一份 Excel 就能把自己的车间搬进数字工厂；演示工厂也只是一份清单
- 工厂常量集中一处，以后加设备、改平面不用改代码
- 教学专用页面暂不适配企业工厂
