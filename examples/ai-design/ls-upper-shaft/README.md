# AI 设计平缝机上轴（ADR-0100 M42）

`requirement.txt` 是需求原话（示意数据）。`python -m assist.design examples/ai-design/ls-upper-shaft/requirement.txt -o result.json`
回放录制（录制在 CI 上用真实模型生成，`.github/workflows/design-eval.yml`）。AI 列条件、提方案；条件核对、轴承位尺寸、
强度、临界转速、轴承寿命全由代码做，不通过的项交回 AI 改，最多 4 轮。验收对照《机械设计》33.11 的 LS-101。

加 `--model-dir out` 时，设计通过后生成三维模型并回读核对（42.3）：

| 文件 | 内容 |
| --- | --- |
| `out/result.json` | 条件、AI 的问题、每一轮的方案与校核结论 |
| `out/shaft.step` | 三维模型（相邻同径段合成一个圆柱，台阶按方案倒圆） |
| `out/readback.json` | 用 41.4 的测量量模型，与设计逐段核对（直径 ±0.01 mm、起点与长度 ±0.05 mm）；质量 = 体积 × 材料密度 |
| `out/drawing.svg` | 轴的外形轮廓图，尺寸全部来自设计数据；回读一致才出 |
| `out/bom.json` | 自制件（质量取回读）+ 库里选的轴承 |

自制件进企业库要人确认，放在问渠 CAD 的面板里做（42.4）。
