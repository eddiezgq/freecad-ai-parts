# ADR-0018：组件知识库的存储设计

- 状态：已接受（2026-10-01，随 issue #25 实现）
- 日期：2026-10-01

## 背景

M2 需要把通过复核的组件存入知识库（L2），并能导出为 JSON 快照纳入版本管理（实施细则第八节）。技术选型已定为 PostgreSQL + pgvector（架构文档）。

## 决策

1. **表结构**（`kb/migrations/0001_init.sql`）
   - `components`：组件基本信息与包络（`envelope` 为 JSONB）
   - `params`：每个参数一行，存完整参数值对象（JSONB），并抽出 `value_num`、`min_num`、`max_num`、`nominal_num`、`method`、`confidence`、`reviewed`、`source_doc` 供查询
   - `ports`：每个端口一行，`spec`、`frame` 为 JSONB，`pos` 保留端口顺序
   - `change_log`：参数与端口规格的每次变更（原值、新值、原因、变更人、时间），只增不改
   - 启用 `vector` 扩展；向量索引表等到语义检索（M4a）时再建
2. **迁移**：按编号顺序执行 `kb/migrations/*.sql`，已执行的记录在 `schema_migrations`，可重复运行
3. **导入**（`kb.store.import_component`）依次把关，任一不过即拒绝并说明原因：
   1. 通过 `schema/component.schema.json` 校验
   2. `test.` 开头的虚构组件默认拒绝，只有测试显式放行
   3. 参数、端口规格、包络中引用的每个来源文档，都必须在 `data/sources.yaml` 登记，且所属来源已核实条款（`terms_checked: true`）或取得授权（`license: partner`）
   4. 更新已有组件时必须给出原因和变更人，逐项写入 `change_log`
4. **导出**：`kb.store.export_snapshot` 按 `<品类>/<组件 id>.json` 写出；导入后再导出，内容与原组件一致（测试检查）
5. **来源文档登记**：`data/sources.yaml` 的每个来源下增加 `documents` 列表（`id`、`title`、`version`、`url`、`sha256`）；`src-test-fixture` 为测试专用文档
6. **连接**：应用读环境变量 `DATABASE_URL`；数据库测试读 `FAP_TEST_DATABASE_URL`，每次测试会话在独立的 schema 中运行。CI 用 PostgreSQL 服务容器运行全部数据库测试；本地未配置时跳过，CI 中缺少配置则直接失败

## 理由

参数和端口都存完整 JSON，保证导出与导入一致、不丢字段；同时抽出常用数值列，满足后续按参数范围检索。来源把关放在导入入口，是 ADR-0015“未授权数据不得入库”的技术保障。

## 影响

- 依赖增加 `psycopg[binary]`
- CI 增加 PostgreSQL 服务
