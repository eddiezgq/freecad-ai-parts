# ADR-0085：编码器接口芯片 WQ-ENCIF——从 Verilog 到版图（电子 E5）

- 状态：已接受（2026-11-05 按项目负责人长期授权执行问渠第 92 轮细则 Q1–Q4 的建议）
- 日期：2026-11-05
- 补充：ADR-0068（共用一份代码）、ADR-0081～0084（电子 E1～E4）

## 决策

1. `factory/designs/wq-encif/`：编码器接口芯片的 Verilog（A/B/Z 同步、一致性滤波、4 倍频解码、32 位计数、Z 锁存、SPI 从机，50 MHz 单时钟）、
   Python 逐拍参考模型、Icarus 测试平台。**示例设计，未流片，未经硅验证。**
2. 验证：9 个用例 RTL 与参考模型逐拍一致，并按规格书手算核对；网页 JS 行为模型与参考模型同一组激励逐拍一致。
3. 综合与版图用开源工具链（LibreLane：Yosys、OpenROAD、Magic、KLayout、Netgen）和 SkyWater SKY130 开源工艺库，在问渠仓库的 CI（微电子实验的基础镜像，按摘要锁定）里跑；
   验收线：DRC 0、LVS 一致、天线无违例、50 MHz 下全部工艺角建立和保持不违例。产物（GDS、门级网表、DEF、报告、版图图片）随仓库发布，网页只看产物。
4. GDS 里含 SKY130 标准单元的版图（Apache-2.0，`data/sources.yaml` 登记 skywater-pdk，条款已核实）；不入零件参数库。
5. 不改 `schema/`、`engine/`，不碰 `tests/golden/`；工具链只作工具用，不随产品分发。
