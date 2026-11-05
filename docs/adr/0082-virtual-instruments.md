# ADR-0082：传感器虚拟仪器（电子 E2）

- 状态：已接受（2026-11-05 项目负责人确认问渠第 82 轮细则 Q1–Q4）
- 日期：2026-11-05
- 补充：ADR-0081（电路分析）、ADR-0068（共用一份代码）

## 决策

1. 数字工厂加“虚拟仪器”页（`/instruments`）：示波器、万用表、逻辑分析仪、数据记录仪等仪器模型 + 6 种传感器模型 + 6 个测量任务；电路分析的瞬态曲线可送到示波器。
2. 仪器与传感器在浏览器里算（`web/src/lib/instruments.js`）；参数只有一份 `web/src/lib/sensors.json`，全部示例值，不进零件参数库。
3. 服务器 `cae/instruments.py` 只做：按登录的人给随机种子、按公式算正确结果并核对（不返回正确值）、生成 Word 实验记录。学生参数在 JS 与 Python 两边逐位一致（同一套 mulberry32），由测试核对。
4. 不联网、不调用 LLM；测试用 Node 跑网页模块，不需要浏览器。

## 影响

- 新增 `cae/instruments.py`、`tests/test_instruments.py`、`web/src/lib/instruments.js`、`web/src/lib/sensors.json`、`web/src/pages/Instruments.vue`、`web/src/components/ScopeScreen.vue`、`web/tools/instr_check.mjs`；
  改 `cae/service.py`、`hub/cae_api.py`、`web/src/pages/Circuit.vue`、导航与帮助。
- 不改 `schema/`、`engine/`、零件数据，不碰 `tests/golden/`。
