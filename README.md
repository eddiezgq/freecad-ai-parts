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

**M0 已完成**（2026-09-30）：目录骨架、CI、示例 MCP 工具 `server_info`、实施细则与 `CLAUDE.md`。下一阶段 M1 于 2026-10-05 开工。

| 阶段 | 计划时间 | 内容 |
| --- | --- | --- |
| M0 | 已完成 | 环境与骨架 |
| M1 | 10/5–10/25 | schema 与端口类型库定稿，手工种子数据，golden 用例 |
| M2 | 10/26–11/22 | 数据流水线，4 类各 30–50 个型号入库 |
| M3 | 11/23–12/13 | 配置引擎 |
| 缓冲 | 12/14–2027/1/3 | 学期假期；补遗留问题 |
| M4a | 2027/1/4–1/17 | MCP 工具 |
| M4b | 1/18–2/14 | FreeCAD 插件 |
| M5 | 2/15–2/28 | 端到端演示 |

## 快速开始

需要 Python 3.11+。

```bash
pip install -e ".[dev]"
python -m ruff check .
python -m pytest -v
```

数据库测试需要 PostgreSQL 16 与 pgvector 扩展。设置测试库地址后运行，未设置时这部分测试会跳过：

```bash
export FAP_TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/fap_test
python -m pytest -v
```

### 接入 MCP 客户端

以 Claude Desktop 为例，在其配置文件的 `mcpServers` 中加入（路径换成本仓库的实际位置）：

```json
{
  "mcpServers": {
    "freecad-ai-parts": {
      "command": "python",
      "args": ["-m", "mcp_server.server"],
      "cwd": "/path/to/freecad-ai-parts"
    }
  }
}
```

重启客户端后，让它调用 `server_info`，返回版本和计划中的 10 个工具即表示连通（M0 验收标准）。

## 开发约定

完整规则见 [docs/implementation-rules.md](docs/implementation-rules.md)；AI 编码助手遵守 [CLAUDE.md](CLAUDE.md)。

- 所有改动从分支走 PR，CI 全绿后合并
- schema 先行、测试先行：先定契约和验收用例，再实现
- 范围、接口或 schema 的任何变更，先改文档和决策记录（`docs/adr/`），再改代码
- 原始规格书不入库，只在 `data/sources.yaml` 登记来源与许可

## 许可证

[Apache License 2.0](LICENSE)。本仓库为开放核心的开源部分；厂商数据的使用遵守各来源的条款，见 [ADR-0001](docs/adr/0001-open-core-and-license.md) 与 [ADR-0005](docs/adr/0005-data-sources.md)。
