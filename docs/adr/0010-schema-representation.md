# ADR-0010：参数值与端口类型的 schema 表示约定

- 状态：提议（随 M1 issue #2 的 PR 评审）
- 日期：2026-09-30

## 背景

实施细则第四、五节规定了参数值结构和 8 种端口类型的字段，但没有规定如何写成 JSON Schema。本记录说明落地时做的表示选择，供评审。

## 决策

1. **规范与标识**：全部使用 JSON Schema Draft 2020-12；`$id` 统一为 `https://github.com/eddiezgq/freecad-ai-parts/schema/<相对路径>`，与文件路径一一对应，文件之间用相对路径 `$ref`。
2. **参数值**：`schema/common/param-value.schema.json`。
   - 数值三选一用 `oneOf` 强制：单值 `value`、范围 `min`/`max`（至少一个）、公差 `nominal`（可带 `tol_upper`/`tol_lower`）
   - `source`、`method`、`confidence`、`reviewed` 一律必填；`method` 为 `computed` 时 `source.formula` 必填，否则 `source.doc` 必填
   - 不设 `unit` 字段，单位只由字段名后缀表达
   - 提供类型化变体 `$defs`：`number`、`integer`、`string`、`boolean`、`string_or_list`、`number_pair`；后四种只允许单值表示
   - 跨字段数值关系（min ≤ max、偏差符号）JSON Schema 无法表达，由代码校验
3. **端口**：`schema/common/port-base.schema.json` 定义公共字段；`schema/port-types/<类型>.schema.json` 各约束 `type` 与 `spec`；`schema/port.schema.json` 按 `type` 分派到对应类型。
   - 机械端口必须有 `motion` 与 `frame`；电气与信号端口不得有
   - 每个端口类型用注解关键字 `x-connects-to` 记录“可连接到”的类型，作为 C1 校验的唯一数据来源；测试保证其对称
4. **对细则的三处细化**
   - 法兰：`hole_kind` 为 `through` 时必须给 `hole_diameter_mm`，为 `threaded` 时必须给 `thread`（细则原文为“二者之一”）
   - 编码器与总线：`protocol`、`kind` 可为单值或列表；电机端填单值，驱动器端可填支持的列表；`protocol` 含 `vendor_proprietary` 时必须给 `vendor`
   - 安装面 `face_size_mm` 用两个数的数组 `[宽, 高]`
5. **公差带格式**：轴用小写（如 `h6`、`js6`），孔用大写（如 `H7`、`JS7`），由正则检查格式；配对是否合理留给 C2 的配合表（issue #3）。

## 理由

把约束尽量写进 schema，数据录入和 LLM 抽取在入库前就能被拒绝；无法用 schema 表达的部分明确交给代码，避免两处各自演化。

## 影响

- 后续的组件、品类 schema（issue #4、#5）复用 `param-value` 的类型化变体和 `port.schema.json`
- 端口枚举值（编码器协议、总线协议等）的增加需要改 schema 并写 ADR
