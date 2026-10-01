# ADR-0014：品类 schema——接口数据只放在端口里，参数名封闭

- 状态：提议（随 issue #5 的 PR 评审）
- 日期：2026-09-30

## 背景

实施细则第六节的品类参数表中，有几项与端口 `spec` 重复：驱动器的 `supply`（电压、相数）、`rated_output_current_a`、`peak_output_current_a`、`supported_encoder_protocols`、`fieldbus_protocols`，分别与 `power_in`、`motor_out`、`encoder_in`、`bus` 端口的字段重复；轴承的 `bore_mm`、`outer_diameter_mm` 与 `inner`、`outer` 端口的直径重复；电机的 `frame_size_mm` 与 `mount_flange` 端口的 `square_size_mm` 重复。同一数据存两处，录入时容易不一致，校验也不知道该信哪一个。

## 决策

1. **接口数据只放在端口里**：描述连接的尺寸、电流、电压、协议等，只写在对应端口的 `spec` 中；上述重复项从参数表删除
   - 驱动器的必填参数因此为空，其必填数据由五个标准端口保证
   - 轴承的内外径由 `inner`、`outer` 端口给出
2. **参数名封闭**：每个品类只允许列出的必填与选填参数，未列出的参数名被拒绝，以防拼写错误；新增参数需改 schema 并写 ADR
3. **标准端口强制存在**：每个品类必须具备细则列出的标准端口（按 id、类型和给定的方向、运动状态检查）；轴承的两个端口 `fit_system` 必须为 `bearing`
4. **转接件**：恰为两个端口；轴套为 `inner`（孔）与 `outer`（外圆），适配法兰为两个法兰
5. **减速器输出轴承**：细则中的 `output_bearing`（性能参数）展开为 `output_bearing_dynamic_load_rating_n` 与 `output_bearing_moment_load_rating_nm` 两个选填参数
6. `fastener` 在 V1 暂无品类约束，留待紧固件生成脚本时定义

## 理由

单一数据来源让校验只读一处，录入和抽取的复核量也更小；封闭参数名能在入库前拦住拼写错误和多余字段。

## 影响

- 实施细则第六节表格已按此修改
- 校验引擎（M3）读取驱动器电流、协议和轴承内外径时，一律从端口取值
