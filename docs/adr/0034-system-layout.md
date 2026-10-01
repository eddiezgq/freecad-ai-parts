# ADR-0034：系统布局字段与 C11 包络长度

- 状态：已接受（2026-10-01，项目负责人授权先按最优方案决定，可推翻）
- 日期：2026-10-01

## 背景

ADR-0020 规定：包络长度依赖组件沿轴向的实际布置，M3 中 C11 的长度子项为 `not_applicable`，“须 FreeCAD 布局后计算”。M4b 已经能按端口布局（ADR-0032），需要做三件事：

- 让系统数据携带布局结果
- 让引擎据此判定长度
- 让导出（系统 JSON、URDF）也能用上布局

## 决策

### 1. 系统 schema 增加可选的 `layout`

```json
"layout": {
  "poses": {
    "motor":   {"position_mm": [0, 0, 0],  "rotation": {"axis": [0, 0, 1], "angle_deg": 0}},
    "reducer": {"position_mm": [0, 0, 20], "rotation": {"axis": [0, 0, 1], "angle_deg": 0}}
  },
  "note": "可选说明"
}
```

- 位姿的含义：实例坐标系（组件包络坐标系）到世界坐标的刚体变换。先绕 `rotation.axis` 转 `angle_deg` 度，再平移 `position_mm`
- 格式与布局工具输出的位姿相同（`freecad_addon.core.pose.Pose.to_dict`）
- 选用“轴 + 角度”，而不用四元数或矩阵：人和 LLM 都容易读写
- `poses` 至少一项；键为实例名
- 以下关系由代码校验，不合法时作为入参错误拒绝：
  - 键必须是 `components` 中的实例
  - 旋转轴不能是零向量
- 布局只记位姿，不重复记配合关系。配合已在 `connections` 中，布局工具按它们对齐
- 这是新增的可选字段，现有系统数据全部仍然合法

### 2. C11 的包络长度（有 `layout` 时）

1. **参与计算的实例**：除驱动器外的全部实例。与外径相同，驱动器装在电控柜中，不计入关节包络（ADR-0027）
2. **输出轴方向**：减速器 `output_flange` 端口轴向在世界坐标中的方向
   - 减速器不是恰好一个，或缺少该端口时，长度为 `unknown`
3. **长度**：所有参与实例的包络各段，在输出轴方向上的投影范围（最大值减最小值）
   - 圆柱、长方体的投影有解析式，不需要 FreeCAD
4. **缺数据**
   - 有参与实例没有位姿：`unknown`，原因列出未布局的实例
   - 包络缺尺寸：`unknown`
5. **判定**：长度 ≤ `max_envelope_length_mm` 为 `pass`，否则为 `fail`
   - 没有 `layout` 时维持 ADR-0020 的 `not_applicable`
6. 长度只依赖位姿与包络。干涉是否消除由 `check_interference` 负责，不在 C11 中判定

### 3. 代码位置

- 位姿与投影的数学原在 `freecad_addon/core/`，移到 `engine/geometry.py`，`freecad_addon.core` 改为复用
  - 引擎是核心层，不能依赖视图层（架构文档“核心与视图分离”）
  - 引擎校验仍是纯函数：布局作为系统数据的一部分输入
- 布局工具提供把当前场景写成 `layout` 的方法；`verify_system` 与 `export_system` 在系统带 `layout` 时使用它

## 理由

- 布局放进系统数据，校验、导出、复现都只依赖一份系统 JSON，符合“结果可复现”的原则
- 长度用解析式计算，不调用 FreeCAD，引擎因此保持纯函数，可以在主 CI 作业中测试
- 考虑过在 `verify_system` 中自动布局再算长度：结果会依赖布局约定（如插入深度未知时的处理），不如让布局结果显式出现在系统中，便于人检查

## 影响

- `schema/system.schema.json` 新增 `layout`。这是本 PR 唯一的 schema 改动，按规定单独成 PR
- #87 实现：
  - `engine/geometry.py`
  - C11 长度
  - `layout` 的关系校验
  - 系统 JSON 带布局，以及 URDF 导出
- 现有 golden 用例都没有 `layout`，C11 结果不变
