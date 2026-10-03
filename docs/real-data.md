# 真实数据：下载、索引与抽取（M6）

厂商公开的产品目录按 [ADR-0040](adr/0040-public-catalog-data.md) 收录：只取参数与接口尺寸，逐项注明出处；不转存文档、图片与 CAD，也不批量爬取。

## 流程

1. **登记**：在 `data/sources.yaml` 对应来源的 `documents` 下登记规格书，写明 `id`（`src-` 开头）、`title`、`version`、`url`（厂商官方下载网址）
2. **下载与索引**
   - 下载时核对 SHA-256；第一次下载时把 SHA-256 写入登记（`--pin`）
   - 在 `data/extract_jobs.yaml` 的 `index` 中列出检索词（型号、参数名），生成页码索引：每页的表格数、出现的检索词和页眉标题（每页前两行的短句），不含正文与表格内容
3. **定任务**：按索引在 `jobs` 中写页码范围和目标型号
4. **抽取**：真实 LLM 逐个型号抽取，结果写到 `data/extracted/<文档>/<型号>.json`，录制写到 `data/recordings/llm/`
5. **AI 复核与入库**（issue #127）：
   - 另一个模型（`FAP_CHECK_MODEL`，缺省 `claude-opus-5-5`）对同一页、同一型号独立再抽一次（`python -m ingest.jobs run --check`），结果写到 `<型号>.check.json`
   - `python -m ingest.crosscheck` 逐项比对两次抽取，两次一致的项标为已复核，复核人记为“claude（AI 复核）”
   - 一致的项组装成组件，通过入库把关后写到 `data/library/<品类>/<组件 id>.json`；`FAP_LIBRARY` 可直接指向这个目录
   - 不一致的项和只报出一次的项不收录，列在 `data/review/<文档>/<型号>.json` 中，留待人工核对

## 在哪里运行

本工作环境访问不到厂商网站，第 2 步和第 4 步在下面两处之一运行。

**GitHub Actions（推荐）**：在 Actions 页面选“真实数据（手动运行）”，点 Run workflow。

- 运行结束后，结果推到分支 `m6/data-run-<运行号>`，再开 PR 合并
- 规格书 PDF 只在运行器的临时目录中，不提交，也不保存为构建产物
- 抽取用仓库 Settings → Environments → demo 中的 `ANTHROPIC_API_KEY`；没有时只做下载和索引
- **回放**（`replay`）：不调用模型，用仓库中的录制重跑抽取、复核与比对；改了核对程序后用它重跑，不需要密钥
- **排查**（`diagnose`）：对被拒的引用，在运行日志中列出规格书该页最接近的几行（参数表的行），用来改进核对程序；不提交到仓库。填 `report_issue` 时另外发到该 issue 的评论（本工作环境读不到运行日志）

**Codespaces 或本地**：

```bash
pip install -e ".[dev,llm]"
python -m ingest.fetch --pin            # 下载已核实来源的规格书到 data/raw/（不入 git）
python -m ingest.jobs index             # 页码索引
python -m ingest.jobs run --record      # 抽取（需要 ANTHROPIC_API_KEY）
python -m ingest.jobs run --record --check   # 复核抽取（另一个模型）
python -m ingest.crosscheck             # 比对，一致的项组装成组件
```

之后提交 `data/sources.yaml`、`data/extracted/`、`data/recordings/`、`data/library/` 和 `data/review/`，不要提交 `data/raw/`。
