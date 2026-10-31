# ADR-0074：清单写了产品的厂打开安全环保、人员排班（危险源、示例人员按设备生成）

- 状态：已接受（2026-10-31 项目负责人确认问渠仓库第 61 轮细则 Q1–Q3）
- 日期：2026-10-31
- 补充：ADR-0073（设备的维护、能耗数据进工厂清单）、ADR-0068（共用一份代码）

## 背景

安全环保（E2）的危险源、化学品、员工，人员排班（E4）的员工、技能矩阵、早晚两班岗位都写死在代码里，只对演示工厂有效。
问渠第 61 轮把这两个领域推到清单写了产品的厂（机器人厂）；客户与服务（E1）要按“现场的机器人”重新设计，另做。

## 决策

1. `factory/factory/equip.py` 的设备类别加 `hazards`（示例危险源）；`hub/ehs.py` 按设备生成危险源、化学品、废物。
2. 新模块 `factory/factory/staff.py`：按车间设备确定性地生成一套**示例人员**（虚构人名）、技能矩阵、白班固定岗位、部门；
   自动测试台、跑合台不用人；标定工位只有主操一人会（教学点）。纯查表：不联网、不调 LLM、不读数据库。
3. `hub/people.py`、`sim/staffing.py` 按它换表；只排白班的厂夜间不下发人员等级。
4. 枢纽放行 `/api/ehs`、`/api/people`；页面的设备清单改为从接口取。演示工厂的原表不动（测试核对）。
5. 共有路径，按 ADR-0068 逐字同步。

## 影响

- 新增 `factory/factory/staff.py`；改 `factory/factory/equip.py`、`hub/ehs.py`、`hub/ehs_api.py`、`hub/people.py`、`hub/people_api.py`、
  `sim/staffing.py`、`hub/app.py`、`Ehs.vue`、`People.vue`、帮助机器人厂第 10 章、`tests/plant_loop.py`、`tests/test_domains_robot.py`。
- 人员、危险源是工厂仿真的教学示例，不是零件参数，不进零件库。不改 `schema/`、`engine/`、零件数据。
