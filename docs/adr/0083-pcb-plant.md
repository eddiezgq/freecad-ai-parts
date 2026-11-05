# ADR-0083：工业园第三座厂——电路板厂（电子 E3）

- 状态：已接受（2026-11-05 项目负责人确认问渠第 85 轮细则 Q1–Q4）
- 日期：2026-11-05
- 补充：ADR-0064（工厂清单）、ADR-0068（共用一份代码）、ADR-0081、ADR-0082（电子 E1、E2）

## 决策

1. 新清单 `factory/plants/wenquest-pcb.yaml`：问渠电路板厂（示例）。产品三种：关节伺服驱动板 DRV-JOINT、AGV 控制板 CTRL-AGV、编码器读头板 ENC-RD；
   两层物料清单（SMT 线做贴片板 → 后段做成品板）；外购件写通用名称 +“型号待确认”，单价、工时、名义值、散布都是示例值，不进零件参数库。
2. 一种物料一张检验模板：贴片板在 AOI 工序记锡膏检测、炉温记录、光学检测结果；成品板在功能测试工序记在线测试与功能测试结果；AOI 缺陷数为计数型。
3. `factory/equip.py` 加 12 类 SMT 与电子测试设备的缺省数据（示例值）；回流焊炉、老化房不需要人值守。
4. 仿真车间的隐藏问题按厂分：电路板厂四种（钢网堵孔、回流炉温漂、贴片机吸嘴磨损、采样电阻来料批次），各有对症措施；减速器厂、机器人厂不变。
5. 规则目录支持 `plant`：只属于某座厂的规则只在那座厂登记（电路板厂 QE1–QE5，QE5 待数据）。
6. 机器人厂清单里 DRV-JOINT、CTRL-AGV 的供应商改为工业园的电路板厂（`park: wenquest-pcb`）。

## 影响

- 新增 `plants/wenquest-pcb.yaml`、`digital/ontology/rules/electronics.yaml`、`digital/hub/ont/rules/electronics.py`、`digital/tests/test_pcb_plant.py`、帮助“电路板厂”一册；
  改 `factory/equip.py`、`digital/sim/errors.py`、`digital/hub/supply.py`、`digital/hub/ont/anomaly.py`、`plants/wenquest-robot.yaml`、帮助索引与机器人厂一册。
- 不改 `schema/`、`engine/`、零件数据，不碰 `tests/golden/`。
