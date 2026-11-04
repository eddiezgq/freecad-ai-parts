# ADR-0080：WQ-H1 轮式人形的动力学模型

- 状态：已接受（2026-11-04 项目负责人确认问渠仓库第 75 轮细则 Q1、Q2）
- 日期：2026-11-04
- 补充：ADR-0078（轮式人形 WQ-H1）、ADR-0068（共用一份代码）

## 决策

1. 数字工厂加 `cae/wqh1.py`：WQ-H1 上半身 16 个关节（腰 2、头 2、双臂各 6）的质量惯量与 MJCF，底盘（WQ-AGV300）按一个刚体固定在地上，不做行走。
2. 关节模组数据只有一份：直接引用 `cae/wqcr5.py` 的 `MODULES`；外购件、自制件的质量是示例值，写在原件里并注明，不进零件参数库。
3. “运动与动力分析”（`cae/mbd_models.py` 的 OWN）可选 B-HUM-WQH1；机器人厂清单 WQ-H1 写上 `library: B-HUM-WQH1/default`（问渠零件库编号）。
4. 本仓库没有问渠的零件库（`library/`），比对零件库副本的测试在这边跳过；其余测试照跑。共有路径按 ADR-0068 逐字同步。

## 影响

- 新增 `factory/digital/cae/wqh1.py`、`factory/digital/tests/test_wqh1.py`；改 `cae/mbd_models.py`、`plants/wenquest-robot.yaml`、帮助机器人厂第 12 章。
- 不改 `schema/`、`engine/`、零件数据，不碰 `tests/golden/`。
