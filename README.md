# FreeCAD AI Parts

AI 原生的 FreeCAD 与零件产品库。把厂商零件抽象成"端口 + 参数 + 包络"的黑箱，由 AI 根据需求选型、做确定性校验，再在 FreeCAD 里按端口装配成系统。

第一步围绕机器人：V1 目标是在 FreeCAD 里用一句自然语言需求，完成机器人关节模组（伺服电机 → 减速器 → 输出，配驱动器与轴承）的选型、校验、布局和 BOM 输出。

## 架构

| 层 | 目录 | 作用 |
| --- | --- | --- |
| L5 应用与视图 | `freecad_addon/` | FreeCAD 工作台：AI 对话、零件面板、包络装配、干涉检查 |
| L4 服务接口 | `mcp_server/` | MCP 工具 + REST，供 agent 和其他客户端调用 |
| L3 配置引擎 | `engine/` | 需求解析、候选求解、性能链计算、规则校验、方案解释 |
| L2 组件知识库 | `kb/` | 组件、参数、端口类型、连接规则、向量索引 |
| L1 数据采集 | `ingest/` | 来源登记、规格书解析、归一化、人工复核 |
| 契约 | `schema/` | 各层共用的 JSON Schema 与端口类型库 |

设计原则：LLM 负责理解需求、提议候选和解释结果；凡影响"能不能用"的判断，都由确定性程序校验兜底。完整说明见 [docs/](docs/README.md)。

## 当前状态

V1 各阶段的**开发部分已全部完成**（2026-10-01，比计划大幅提前），剩下的是需要人完成的验收、规则表核对与厂商数据授权，见 [开发计划的进度一节](docs/plan.md#进度截至-2026-10-01)。

| 阶段 | 内容 | 开发 |
| --- | --- | --- |
| M0 | 环境与骨架 | 完成 |
| M1 | schema 与端口类型库，golden 用例 | 完成（有条件通过验收） |
| M2 | 数据流水线：合成规格书、LLM 抽取与核对、人工复核队列、准确率评测 | 完成 |
| M3 | 配置引擎：11 项校验、候选求解与排序、中英文解释 | 完成 |
| M4a | MCP 工具与 REST，外部客户端接入 | 完成 |
| M4b | FreeCAD：按端口布局、干涉检查、截图、URDF、工作台与对话面板 | 完成 |
| M5 | 一句话需求解析、端到端演示、样例输出 | 完成 |

组件数据目前全部是虚构的测试组件（ADR-0015）。真实厂商数据须先取得书面授权。

## 快速开始

需要 Python 3.11+。

```bash
pip install -e ".[dev]"
python -m mcp_server.e2e "六轴机械臂第 2 关节：输出连续扭矩 25 N·m、峰值 50 N·m，输出转速 30 rpm，220 V 单相供电，EtherCAT 总线" --out out/
```

`out/` 中有方案汇总、BOM、系统 JSON 和 URDF；样例见 [`examples/joint2/`](examples/joint2/)。加上 FreeCAD 做干涉检查与截图、在 FreeCAD 里用自然语言对话的步骤，见 [演示](docs/demo.md)。

| 入口 | 说明 |
| --- | --- |
| 命令行端到端演示 | `python -m mcp_server.e2e`，见 [docs/demo.md](docs/demo.md) |
| 外部 MCP 客户端（Claude Desktop 等） | 11 个工具与提示模板，见 [docs/mcp-client.md](docs/mcp-client.md) |
| REST | `freecad-ai-parts-mcp --http`，路由见 `mcp_server/rest.py` |
| FreeCAD 工作台与对话面板 | `python -m freecad_addon.install`，见 [freecad_addon/README.md](freecad_addon/README.md) |

### 测试

```bash
python -m ruff check .
python -m pytest -v
```

- 数据库测试需要 PostgreSQL 16 与 pgvector：设置 `FAP_TEST_DATABASE_URL` 后运行，未设置时跳过
- FreeCAD 测试（标记 `freecad`）的运行方式见 [freecad_addon/README.md](freecad_addon/README.md)
- CI 中这两类测试都必须运行

## 开发约定

完整规则见 [docs/implementation-rules.md](docs/implementation-rules.md)；AI 编码助手遵守 [CLAUDE.md](CLAUDE.md)。

- 所有改动从分支走 PR，CI 全绿后合并
- schema 先行、测试先行：先定契约和验收用例，再实现
- 范围、接口或 schema 的任何变更，先改文档和决策记录（`docs/adr/`），再改代码
- 原始规格书不入库，只在 `data/sources.yaml` 登记来源与许可

## 许可证

[Apache License 2.0](LICENSE)。本仓库为开放核心的开源部分；厂商数据的使用遵守各来源的条款，见 [ADR-0001](docs/adr/0001-open-core-and-license.md) 与 [ADR-0005](docs/adr/0005-data-sources.md)。
