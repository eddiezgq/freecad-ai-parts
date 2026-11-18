# AI 设计平缝机上轴（ADR-0100 M42）

`requirement.txt` 是需求原话（示意数据）。`python -m assist.design examples/ai-design/ls-upper-shaft/requirement.txt -o result.json`
回放录制（录制在 CI 上用真实模型生成，`.github/workflows/design-eval.yml`）。AI 列条件、提方案；条件核对、轴承位尺寸、
强度、临界转速、轴承寿命全由代码做，不通过的项交回 AI 改，最多 4 轮。验收对照《机械设计》33.11 的 LS-101。
