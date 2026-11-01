# ADR-0076：清单写了产品的厂，AI 巡检规则和 AI 助手接上已打开的领域

- 状态：已接受（2026-11-01 项目负责人确认问渠仓库第 67 轮细则 Q1–Q3）
- 日期：2026-11-01
- 补充：ADR-0073、ADR-0074、ADR-0075（机器人厂打开各领域）、ADR-0068（共用一份代码）

## 背景

E1–E7 的巡检规则标着 `demo_only`、AI 助手的这些领域在非演示工厂一律拒答。机器人厂打开这些领域后，平台不报警、助手不回答。

## 决策

1. 规则目录：`demo_only` 的规则在 `plant.has_domains()` 的厂也跑；读演示工厂“现场的减速器”投诉表的 C1–C4 除外。
2. 写死演示工厂设备 / 物料的规则改为按清单找：`factory/equip.py` 的 `bottleneck()`（工艺路线负荷最大的工作站）、`key_items()`（清单 `key_materials`）。
3. RS1、RS2 的处理方案与新动作类型 `robot_service`（现场机器人服务派工）。
4. AI 助手：打开了的领域工具和问法放开；读“现场的减速器”的三个工具仍只在演示工厂；机器人厂的投诉 / 服务问法答“现场的机器人”。
5. 共有路径，按 ADR-0068 逐字同步。演示工厂行为不变（规则 63 条、评测题照过）。

## 影响

- 改 `hub/ont/anomaly.py`、`hub/ont/agent.py`、`hub/ont/actions.py`、`hub/ont/plan_api.py`、`hub/ont/rules/{energy,maintenance,people,supply,service}.py`、
  `hub/rfield.py`、`factory/factory/equip.py`、帮助机器人厂第 10、11 章、`tests/plant_loop.py`；新增 `tests/test_robot_rules.py`。
- 不改 `schema/`、`engine/`、零件数据，不碰 `tests/golden/`。
