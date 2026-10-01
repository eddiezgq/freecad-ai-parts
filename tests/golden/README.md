# golden 测试集

配置引擎与 MCP 工具的标准验收用例。**预期结果由人手算并审定；golden 用例的增删改只能由人决定，不得为了让测试通过而修改预期**（`CLAUDE.md`）。

按 ADR-0015，全部使用虚构测试组件（id 以 `test.` 开头），不含任何真实产品数据。

## 目录

| 路径 | 内容 |
| --- | --- |
| `fixtures/` | 虚构测试组件库，每个组件一个 JSON 文件，文件名即组件 id |
| `valid/` | 可用的方案：整体结论为 `pass` 或 `warn` |
| `invalid/` | 错配方案：每个用例只含一个错误，C1–C11 每项至少一个（C6、C8 只告警，故为 `warn`） |
| `unknown/` | 缺关键数据的方案：整体结论为 `unknown` |

## 用例格式（YAML）

```yaml
id: invalid/c3-flange-pcd-mismatch
description: 一句话说明
system: { ... }          # 完整的系统对象，遵循 schema/system.schema.json
expected:
  overall: fail          # pass / warn / fail / unknown
  checks:
    C3: fail             # 必须是这个结果
    others: not_fail     # 未列出的各项不得为 fail
calc: |
  逐项手算过程
```

`checks` 中的值除四种状态外，还可以是 `not_applicable`（该项不适用，ADR-0016）或 `any`：表示该项结果依赖 M3 尚未定义的规则，本用例不断言（目前只用于 `invalid/c1-swapped-wiring` 中受接线错误影响的 C9、C10）。

## 已明确的规则（ADR-0016、ADR-0020）

- **不适用的校验**：`not_applicable`（ADR-0016）；现有用例未列出不适用项，是否补充断言由人决定
- **缺少应有的连接**：判为 `fail`（ADR-0020）；`invalid/c1-swapped-wiring` 中 C9、C10 目前为 `any`，按此应为 `fail`，是否更新由人决定
- **系统包络外径**：取各段外接圆直径的最大值，长方体按截面对角线（ADR-0020）；`invalid/c11-envelope-diameter` 在任一算法下都判 `fail`，不受影响
- **轴承转速**：取关节输出转速（ADR-0020）；目前还没有轴承转速的用例
