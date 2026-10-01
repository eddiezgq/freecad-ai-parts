# CLAUDE.md

本文件对每个 AI 编码会话生效。完整规则见 [docs/implementation-rules.md](docs/implementation-rules.md)，决策记录见 [docs/adr/](docs/adr/)。

## 项目

AI 原生 FreeCAD 与零件产品库。厂商零件抽象为“端口 + 参数 + 包络”的黑箱；LLM 负责理解需求、提议候选和解释结果，凡影响“能不能用”的判断都由 `engine/` 的确定性代码校验。V1 目标：机器人关节模组（伺服电机、减速器、驱动器、轴承）的选型、校验、FreeCAD 布局和 BOM 输出。

## 工作方式

- 一次只做一个 issue；超出 issue 范围的改动另开 issue
- 从 `main` 开分支，命名 `m<阶段>/<简述>`；不直接推送 `main`，所有改动走 PR
- 提交信息格式 `M<阶段>: <做了什么>`，正文写原因和关联 issue
- 范围、接口、schema、校验规则的变更：先改文档并写 ADR，再改代码

## 必须遵守

- 同一个 PR 不得同时改 `schema/` 和实现代码；schema 改动单独成 PR，并附 ADR
- **不得修改 `tests/golden/` 的预期结果来让测试通过**；golden 用例的增删改只能由人决定
- 不得跳过、删除或弱化已有测试和校验
- 不得在代码或数据里编造参数值；缺数据就不写该字段（不写 `null`、`0` 或估计值），并在 PR 里说明
- 校验遇到缺失数据时结果为 `unknown`，不得判为 `pass`
- `engine/` 的校验函数必须是纯函数：不联网、不调用 LLM、不读数据库
- 代码内部只用标准单位（mm、N·m、rpm、kg、kg·m²、W、V、A 有效值、N、arcmin、效率用 0–1 小数），字段名带单位后缀；单位换算只在 `ingest/` 入口用 pint 完成
- 测试不联网、不调用真实 LLM；FreeCAD 相关测试标记 `@pytest.mark.freecad`
- 密钥只从环境变量读取，不写入仓库；原始规格书放 `data/raw/`，不入 git
- 未在 `data/sources.yaml` 登记并核实条款（`terms_checked: true`）的来源，其数据不得入库

## 命令

```bash
pip install -e ".[dev]"
python -m ruff check .
python -m pytest -v
```

数据库测试需要 PostgreSQL 16 + pgvector，用环境变量 `FAP_TEST_DATABASE_URL` 指定测试库；未配置时本地跳过，CI 中必须运行。

每次会话结束前运行 `python -m ruff check .` 和 `python -m pytest`，并把结果写入 PR 描述。
