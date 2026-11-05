# ADR-0081：电路分析（电子 E1）

- 状态：已接受（2026-11-04 项目负责人确认问渠《电路板厂与电子仿真方案》Q1–Q8 与第 79 轮细则 Q1–Q4）
- 日期：2026-11-05
- 补充：ADR-0068（共用一份代码）、ADR-0056（分析模块）

## 决策

1. 数字工厂加“电路分析”：`cae/circuit.py`（关节伺服驱动板 DRV-JOINT 的 6 道例题、网表检查、服务器 ngspice、蒙特卡洛）、`cae/circuit_report.py`（Word 计算书）、
   CAE 服务 `/circuit/*`、枢纽转发 `/api/circuit/*`、网页 `/circuit`。
2. 求解器 ngspice：服务器用系统 ngspice 子进程（CAE 镜像 apt 安装）；浏览器用 ngspice 的 WebAssembly 版（npm `eecircuit-engine`，MIT，固定版本，随网页打包）。
   不联网、不调用 LLM；读数一律用 ngspice 的 `.meas`，每道例题与手算公式对照（ADR-0056 的“标准题”要求）。
3. 网表模式只许分析语句与器件，拒绝 `.control`、`.include`、读写文件、shell 等；单次仿真限时。
4. 例题参数是示例值，写在 `cae/circuit.py` 并注明，不进零件参数库；器件用通用模型，不收厂商模型。

## 影响

- 新增上述文件与 `tests/test_circuit.py`、网页 `Circuit.vue`、`SchematicView.vue`、`SpiceChart.vue`、`lib/spice.js`、`lib/schematics.js`、`web/tools/spice_check.mjs`；
  改 `cae/service.py`、`hub/cae_api.py`、`Dockerfile`、`web/package.json`、导航与帮助。
- 不改 `schema/`、`engine/`、零件数据，不碰 `tests/golden/`。
