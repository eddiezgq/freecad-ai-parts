# ADR-0075：机器人厂的客户与服务——现场的机器人

- 状态：已接受（2026-11-01 项目负责人确认问渠仓库第 64 轮细则 Q1–Q3）
- 日期：2026-11-01
- 补充：ADR-0068（共用一份代码）、ADR-0073、ADR-0074（机器人厂打开其余领域）

## 背景

减速器厂的客户与服务围着“现场的减速器”（油温、振动、轴承寿命），机器人厂用不上。问渠第 64 轮给机器人厂单独做“现场的机器人”。

## 决策

1. 新模块 `hub/rfield.py`（接口 `rfield_api.py`、页面 `RobotService.vue`）：整机标定做完建档，6 个关节按规格先进先出配上关节测试台测过的关节
   （序列号、谐波减速器批次、出厂背隙）；销售订单开票即发到客户现场；现场模拟器每个现场日一条摘要（背隙、温度、电流、碰撞），
   问题批次磨得快；投诉进 ERPNext Issue，服务工单（远程重新标定、上门换关节模组、上门补润滑脂），回访。全部是示例值。
2. AI 巡检规则 RS1（现场机器人报警）、RS2（同批减速器多台报警）；没有关节模组产品的厂（演示工厂）返回空。
3. 减速器厂的客户与服务、数字孪生不动。共有路径，按 ADR-0068 逐字同步。

## 影响

- 新增 `hub/rfield.py`、`hub/rfield_api.py`、`web/src/pages/RobotService.vue`、`tests/test_rfield.py`、帮助机器人厂第 11 章；
  改 `hub/app.py`、`hub/ont/rules/service.py`、`ontology/rules/service.yaml`、`App.vue`、`main.js`、`tours.json`、`plant_loop.py`；
  规则总数 61 → 63（`test_anomaly`、`test_chain`、`closed_loop` 的计数）。
- 本次同步顺带补上问渠第 62、63 轮已上线的共有代码（电控箱自然对流 CFD、机器人厂配置器），此前未同步。
- 现场数据是工厂仿真的教学示例，不是零件参数，不进零件库。不改 `schema/`、`engine/`、零件数据，不碰 `tests/golden/`。
