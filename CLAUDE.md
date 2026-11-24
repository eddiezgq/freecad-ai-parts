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
- `analysis/` 的分析模块（ADR-0056）可以启动本机求解器子进程，但不联网、不调用 LLM；分析结果不写入零件参数；每个模块带与解析解或教材公式对照的标准题
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

## 总控协议（2026-11-24 起，所有窗口必须遵守；规则全文在私有仓库 eddiezgq/wenquest-hq 的 RULES.md）

- **开工**：先读本仓库 `STATUS.md`。"总控指令"里有未处理的，先处理或说明为什么不处理。
- **收工**（每次推送前）：更新 `STATUS.md`，30 行以内：本次完成、下一步、卡点、跨仓库需求（写成 `→ 仓库名：要什么`）、本会话模型。
- 跨仓库的事不口头交接，一律写进双方 `STATUS.md` 的"跨仓库需求"。
- 开发阶段：不做客户、市场、招标相关工作；只做 Eddie 交代的任务，新想法写进"待议"，不擅自开工。
- 仓库是公开的：密钥、密码、服务器口令、企业数据、未发表论文的关键结论不进仓库。
- 额度：子代理和例行检查默认用 Sonnet，Opus 留给设计、写作、审稿、疑难排错；不开租用 GPU；全量重建、批量渲染、一次开 3 个以上子代理先问 Eddie；重的 Actions 任务（安装包、镜像、全书构建）不在 PR 和 push 上重复跑。
- 规则妨碍工作时，在 `STATUS.md` 的"规则反馈"写一行，由每周一的巡检汇总给 Eddie。
