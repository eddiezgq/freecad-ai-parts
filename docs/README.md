# 文档

## 主文档

| 文档 | 内容 |
| --- | --- |
| [整体架构](architecture.md) | 五层架构、核心数据模型、AI 分工、MCP 工具清单、技术选型、V1 范围与已定决策 |
| [V1 开发方案与计划](plan.md) | 仓库结构、开发方法、进度计划、各阶段验收、风险、当前进度 |
| [V1 实施细则](implementation-rules.md) | 开发流程、代码规范、schema 字段级规格、校验规则、数据复核、golden 用例、各阶段分项任务 |
| [演示](demo.md) | 从一句需求到 BOM 的三种演示方式 |
| [MCP 客户端接入](mcp-client.md) | Claude Desktop 等客户端的配置、工具清单、HTTP 与 REST |
| [真实数据](real-data.md) | 规格书登记、下载、页码索引与抽取（M6，ADR-0040） |

文件优先级：架构 > 实施细则 > 开发计划 > 其他（实施细则第一节）。

- 前两份原为私有在线文档，2026-10-01 转存到本目录，此后以仓库版本为准
- 实施细则的在线版含端口连接图：https://claude.ai/code/artifact/ffce2bff-a1ce-4a2a-a45a-b8e50a67baee

## 决策记录（ADR）

| 编号 | 决策 | 日期 |
| --- | --- | --- |
| [0001](adr/0001-open-core-and-license.md) | 开放核心模式，开源部分采用 Apache-2.0 | 2026-09-30 |
| [0002](adr/0002-port-schema.md) | 端口类型库用自定义轻量 JSON Schema，概念上对应 SysML v2 | 2026-09-30 |
| [0003](adr/0003-entry-points.md) | 用户入口两者都要，先外部 MCP 客户端，后 FreeCAD 内置面板 | 2026-09-30 |
| [0004](adr/0004-v1-scope.md) | V1 只做 4 类核心链路，每类 30–50 个型号，只做静态匹配 | 2026-09-30 |
| [0005](adr/0005-data-sources.md) | 数据来源：参数入库、包络自生成、原厂模型只留链接 | 2026-09-30 |
| [0006](adr/0006-robotics-academy.md) | 与机器人学院共用组件库，学院作为独立使用方接入 | 2026-09-30 |
| [0007](adr/0007-reducer-units-and-adapters.md) | 减速器只收录整机型；新增 adapter 组件类型 | 2026-09-30 |
| [0008](adr/0008-validation-defaults.md) | 校验默认值：安全系数 1.2，惯量比告警阈值 10 | 2026-09-30 |
| [0009](adr/0009-workflow-and-rules.md) | main 受保护、全部改动走 PR；实施细则入库；M1 提前开工 | 2026-09-30 |
| [0010](adr/0010-schema-representation.md) | 参数值与端口类型的 schema 表示约定 | 2026-09-30 |
| [0011](adr/0011-rule-tables.md) | 校验规则数据表的格式与核对状态 | 2026-09-30 |
| [0012](adr/0012-component-system-requirement.md) | 组件、系统、需求 schema 的结构 | 2026-09-30 |
| [0013](adr/0013-bearing-fit-system.md) | 圆柱端口增加公差体系，轴承用 ISO 492 精度等级 | 2026-09-30 |
| [0014](adr/0014-interface-data-in-ports.md) | 品类 schema：接口数据只放在端口里，参数名封闭 | 2026-09-30 |
| [0015](adr/0015-data-authorization.md) | 数据获取路线：先用虚构组件开发，真实厂商数据须取得书面授权（第 2 条被 ADR-0040 取代） | 2026-09-30 |
| [0016](adr/0016-not-applicable-status.md) | 校验结果增加“不适用”状态 | 2026-09-30 |
| [0017](adr/0017-bearing-fit-judgement.md) | C2 对轴承端口的判定方式 | 2026-09-30 |
| [0018](adr/0018-kb-storage.md) | 组件知识库的存储设计 | 2026-10-01 |
| [0019](adr/0019-vendor-source-consistency.md) | 组件引用的来源文档必须属于组件厂商 | 2026-10-01 |
| [0020](adr/0020-m3-rule-decisions.md) | 缺少连接、包络尺寸、轴承转速三条校验规则 | 2026-10-01 |
| [0021](adr/0021-llm-extraction.md) | LLM 结构化抽取的流程与输出格式 | 2026-10-01 |
| [0022](adr/0022-tolerance-sign.md) | 公差偏差的符号约定：只要求下偏差 ≤ 上偏差 | 2026-10-01 |
| [0023](adr/0023-review-queue.md) | 人工复核队列与组件组装 | 2026-10-01 |
| [0024](adr/0024-bearing-ring-clamping.md) | 轴承内圈端口不强制紧固方式 | 2026-10-01 |
| [0025](adr/0025-engine-conventions.md) | 校验引擎的实现约定 | 2026-10-01 |
| [0026](adr/0026-performance-chain.md) | 性能链校验（C4–C8）的实现约定 | 2026-10-01 |
| [0027](adr/0027-electrical-envelope.md) | 电气、信号与包络校验（C9–C11）的实现约定 | 2026-10-01 |
| [0028](adr/0028-engine-review-fixes.md) | 校验引擎独立评审后的规则修订 | 2026-10-01 |
| [0029](adr/0029-compose-ranking.md) | 链路模板与候选方案排序 | 2026-10-01 |
| [0030](adr/0030-explanations.md) | 方案解释的生成方式 | 2026-10-01 |
| [0031](adr/0031-mount-face-pattern.md) | 安装面孔位阵列增加 linear，明确 rect 的孔位 | 2026-10-01 |
| [0032](adr/0032-m4b-layout-architecture.md) | M4b FreeCAD 布局的架构、配合约定与测试方式 | 2026-10-01 |
| [0033](adr/0033-interference-pass-through.md) | 干涉检查中的轴穿过通道，以及 worker 的启动方式 | 2026-10-01 |
| [0034](adr/0034-system-layout.md) | 系统布局字段与 C11 包络长度 | 2026-10-01 |
| [0035](adr/0035-urdf-export.md) | URDF 导出的约定 | 2026-10-01 |
| [0036](adr/0036-gui-bridge-and-chat-panel.md) | FreeCAD 界面桥接与内置对话面板 | 2026-10-01 |
| [0037](adr/0037-requirement-parsing.md) | 一句话需求的解析与端到端演示的可复现性 | 2026-10-01 |
| [0038](adr/0038-eval-equivalence.md) | 抽取评测的等价规则与可推出字段 | 2026-10-01 |
| [0039](adr/0039-phases-imply-ac.md) | 需求解析中单相、三相供电推出交流 | 2026-10-01 |
| [0040](adr/0040-public-catalog-data.md) | 用厂商公开的产品目录参数跑通真实数据（取代 ADR-0015 第 2 条） | 2026-10-01 |
| [0041](adr/0041-generated-adapters.md) | 按两侧端口尺寸生成转接件（轴套与转接板） | 2026-10-02 |

新决策按 [模板](adr/template.md) 编写，编号顺延；已接受的决策不改写，被取代时新建一条并标注。
