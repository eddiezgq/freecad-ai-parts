# ADR-0089：问渠电子设计描述格式在 P111 / P112 新加的字段（补记）

- 状态：已接受（2026-11-07 补记；对应问渠仓库已合并、已上线的 PR #61、#62、#63）
- 日期：2026-11-07
- 补充：ADR-0086（共用 `eda/`）、ADR-0088（变体 `add_pours`）

## 背景

问渠的另一会话在 P111（电子 P4：板子生成、工艺与布局检查、热分析、回读、报告）和 P112（电子 P5：工厂侧新产品导入）
给 `eda/` 的设计描述格式加了字段，问渠仓库里已合并、上线；本仓库按 ADR-0086 同步 `eda/`，格式变更在这里补一份 ADR。

## 决策（照问渠已上线的实现记录）

1. 设计描述（wqeda.design/1）板子层 `board` 可选字段（`eda/wqeda/schema/board.py` 校验，只查格式不判对错，每个数要有出处，没有写“示例值”）：
   `net_classes`（布线线宽 / 间距类别）、`stackup`（板厚、铜厚）、`rules`（走线温升、ICT 覆盖率要求）、
   `thermal`（环境温度、对流换热系数、开关频率、发热器件）、`constraints`（布局约束五种：loop、kelvin、near、apart、edge）。
2. `circuit.nets.high_current` 的电流可写数，也可写 `spec.<规格字段>`（跟着规格变）。
3. 变体（wqeda.variant/1）加可选字段 `item_changes`：`{位号: 物料编号 或 null}`（改物料编号 / 去掉），记入改动清单。
4. 工厂能力（capability）加三项：`pitch_min_mm`、`fine_pitch_mm`、`pad_min_mm`。
5. 都是可选字段，旧描述照旧有效；不改 `schema/`（零件库 JSON Schema）、`engine/`，不碰 `tests/golden/`。

## 后果

- 驱动板 A、B 版设计描述用上这些字段；`eda/tests/test_board_p4.py`、`test_factory_p5.py` 覆盖。
- 问渠 PR #63：板子模型存档改为按内容比对（形状 0.002 mm 容差），CalculiX 改用迭代解法——CI 上原来逐字节比对、差异文本跑满 50 分钟超时。
