# 需求解析的录制（ADR-0037）

文件名为请求哈希（提示词版本、模型、系统提示、原话共同决定）。测试与端到端演示默认回放这里的录制，不联网。

- 示例句子（`examples/joint2-requirement.json` 的原话）的录制是真实响应（2026-10-01，claude-sonnet-5-5）
- `simulated: true` 的录制是手写的模拟响应，结果中会标注“模拟”；目前没有
- 真实录制：在本地设置 `ANTHROPIC_API_KEY` 后运行 `python -m engine.requirement_parse "一句话需求" --record`，同一句话的录制会被真实响应覆盖
