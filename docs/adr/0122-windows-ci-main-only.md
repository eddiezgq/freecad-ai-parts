# ADR-0122：Windows 安装包只在 main 推送、打标签、每晚和手动时跑，PR 上只跑 CI

- 状态：已接受（2026-11-24，总控指令）
- 日期：2026-11-24
- 补充：ADR-0067（CI 预算）、ADR-0066（Windows 安装包）

## 背景

总控统计：7 天约 995 次 Actions 运行。`ci.yml` 和 `windows.yml` 在 `pull_request` 和推送 main 时各跑一次；
`windows.yml` 即使按 ADR-0067 判定不需要出安装包，也要起一次 `scope` 作业，每个 PR 每推一次都算一次运行。
镜像（`images.yml`）已经只在 main 推送和打标签时跑，不用改。

## 决策

1. `windows.yml` 去掉 `pull_request` 触发，加上打标签（`v*`）触发；保留推送 main、每晚一次（ADR-0067）和手动。
2. `ci.yml` 不变：PR 上照常跑，合并后推送 main 再跑一次。
3. 改了 `installer/`、`freecad_addon/` 界面这类只有 Windows 作业能验的 PR，想合并前验：在该分支上手动跑
   `gh workflow run windows.yml --ref <分支>`（手动 = 全部作业，ADR-0067）。

## 理由

Windows 作业按 2 倍计费、每次十几分钟，又只与少数目录有关；合并后在 main 上跑一次、每晚兜底一次，足以发现问题。
考虑过保留 PR 触发、只靠 `scope` 跳过：重作业是跳过了，但运行次数不减，达不到总控要求。

## 影响

Windows 安装包和 Windows 界面测试的失败改在合并后才看到，按“改了就修”的原则在下一个 PR 修；关系大的改动合并前手动跑一次。
