# ADR-0086：共有代码加上仓库根下的 `eda/`（问渠电子的设计描述与检查）

- 状态：已接受（2026-11-06 按项目负责人长期授权执行；问渠第 102 轮同步时发现）
- 日期：2026-11-06
- 补充：ADR-0068（共用一份代码）、ADR-0084（关节驱动板 KiCad 设计）

## 背景

问渠仓库新增了仓库根下的 `eda/`（问渠电子 WenQuest Electronics：四层设计描述的读取与校验、板子模型、检查引擎；见 `eda/README.md`），
`factory/designs/tools/drv_joint.py` 从此改为读设计描述（`factory/designs/drv-joint/design.yaml`、`drv-joint-b/variant.yaml`），要 `import wqeda`。
共有代码原来只比对 `factory/`，同步过来的 `drv_joint.py` 在本仓库找不到 `wqeda`，`factory/digital/tests/test_pcb_design.py` 等导入失败。

## 决策

1. 仓库根下的 `eda/` 整个算共有代码，与问渠逐字一致；`tools/factory_sync.py`（在问渠）同时比对它，报告里路径以 `eda/` 开头。
2. 本仓库不改 `eda/` 的内容；改动在问渠做、再同步过来（与 `factory/` 同一规矩）。
3. 不改 `schema/`、`engine/`，不碰 `tests/golden/`；`eda/` 的检查是纯函数（不联网、不调 LLM），与本仓库 `engine/` 的约束相容；
   不往零件参数库写数据。

## 后果

- 同步 PR 里会出现 `eda/` 的改动；CI 照常跑 `factory/` 的测试即可（`eda/tests` 在问渠跑）。
