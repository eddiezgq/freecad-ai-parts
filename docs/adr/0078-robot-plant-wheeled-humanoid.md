# ADR-0078：机器人厂的第三种整机——轮式人形 WQ-H1

- 状态：已接受（2026-11-02 项目负责人确认问渠仓库第 71 轮细则 Q1–Q3，Q1 选方案 A）
- 日期：2026-11-02
- 补充：ADR-0069（清单第 2 版与机器人厂）、ADR-0073（设备类别）、ADR-0068（共用一份代码）

## 决策

1. 机器人厂清单加第三种整机 WQ-H1（示例产品）：双臂、腰、头共 16 个关节模组（全用本厂 WQJ-L / M / S），下半身是一台 WQ-AGV300（物料清单里“整机套整机”）；
   新工作站“人形总装工位 HA”、三道新工序（人形总装、双臂与手眼标定、人形联调）、三项检验特性。只加内容，清单字段不变。
2. 外购件型号待确认、价格与工时是示例值，不进零件库；不改 WQ-CR5、WQ-AGV300 的现有数据。
3. `factory/equip.py` 加 `ha` 前缀（装配类）；现场售后（`hub/rfield.py`）只认 6 个关节的整机。
4. 共有路径，按 ADR-0068 逐字同步；顺带同步问渠第 66 轮对 `cae/struct_parts.py` 的后续修改。

## 影响

- 改 `factory/plants/wenquest-robot.yaml`、`factory/factory/equip.py`、`hub/rfield.py`、`tests/test_domains_robot.py`；新增 `tests/test_h1.py`、帮助机器人厂第 12 章。
- 不改 `schema/`、`engine/`、零件数据，不碰 `tests/golden/`。
