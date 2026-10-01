# schema

全项目的共同契约：组件（Component）、端口（Port）、连接规则（Rule）、系统（System）的 JSON Schema（Draft 2020-12），以及端口类型库。表示约定见 [ADR-0010](../docs/adr/0010-schema-representation.md)，字段规格见实施细则第四至六节。

## 目录

| 路径 | 内容 | 状态 |
| --- | --- | --- |
| `common/param-value.schema.json` | 参数值结构（单值 / 范围 / 公差，来源、方式、置信度、复核）及类型化变体 | M1 issue #2 |
| `common/port-base.schema.json` | 端口公共字段（id、type、dir、motion、frame、spec） | M1 issue #2 |
| `port-types/*.schema.json` | 8 种端口类型，各含 `x-connects-to` | M1 issue #2 |
| `port.schema.json` | 任意端口：按 `type` 分派到对应端口类型 | M1 issue #2 |
| `rules/` | 公差配合表、feature/clamping 兼容矩阵、ISO 273 间隙孔表 | M1 issue #3 |
| `component.schema.json` | 组件：基本信息、参数表、端口列表、分段包络；结构见 [ADR-0012](../docs/adr/0012-component-system-requirement.md) | M1 issue #4 |
| `requirement.schema.json` | 需求：与 C4–C11 对应的需求值 | M1 issue #4 |
| `system.schema.json` | 系统：需求、组件实例、端口连接 | M1 issue #4 |
| `categories/` | 各品类参数 | M1 issue #5 |

## 约定

- 文件命名 `<对象>.schema.json`；`$id` 为 `https://github.com/eddiezgq/freecad-ai-parts/schema/<相对路径>`，与路径一致（测试检查）
- 文件之间用相对路径 `$ref`
- 任何修改先写决策记录，再改 schema；schema 改动单独成 PR
- CI 校验每个 schema 本身，并用 `tests/fixtures/` 的合法 / 非法样例检验约束

状态：M1（2026-10-05 至 10-25）定稿为 `0.1.0`。
