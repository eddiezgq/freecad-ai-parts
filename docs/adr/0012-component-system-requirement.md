# ADR-0012：组件、系统、需求 schema 的结构

- 状态：已接受
- 日期：2026-09-30

## 背景

issue #4 要定义三个顶层对象。实施细则给出了字段清单，但没有规定组件包络、系统里的组件实例和连接如何表示。

## 决策

1. **组件** `component.schema.json`
   - 必填：`id`、`category`、`vendor`、`model`、`status`、`license`、`params`、`ports`、`envelope`
   - `id` 格式 `<品类>.<厂商>.<型号>`，虚构测试组件加 `test.` 前缀；`id` 中的品类必须与 `category` 一致（schema 检查）
   - `params` 的每个值都必须是参数值对象，参数名小写加下划线；品类专属的必填参数留给 `schema/categories/`（issue #5）
   - `license` 在 ADR-0005 的三种（`params-only`、`open`、`partner`）之外增加 `standard`，用于按标准生成的紧固件
   - 只有 `status: discontinued` 的组件可以有 `superseded_by`
   - **包络**由一个或多个部分组成，每部分为圆柱（直径）或长方体（宽、高），沿 z 轴从 `z_start_mm` 起延伸 `length_mm`；原点在安装法兰面中心，z 轴指向输出方向。尺寸用参数值对象，因为它们来自规格书
2. **需求** `requirement.schema.json`：字段与 C4–C11 一一对应；必填只有连续扭矩和输出转速。`safety_factor` 默认 1.2、`inertia_ratio_limit` 默认 10（ADR-0008）。需求值是用户给定的，用裸数字，不用参数值对象
3. **系统** `system.schema.json`：`components` 为实例列表 `{instance, component}`，同一组件可出现多次；`connections` 为 `{a, b}` 对象，端口写作 `<实例名>.<端口 id>`，方向由 C1 判定而不由书写顺序决定。系统内嵌需求
4. **golden 用例格式随之调整**：用例中的 `system` 为完整的系统对象（含需求），替代实施细则原示例中 `[motor.a.shaft, ...]` 的列表写法

## 理由

实例名让同一型号多次出现（两个轴承）不产生歧义；包络用分段的圆柱和长方体，足以表达“方法兰 + 机身 + 轴”这类外形，又不需要真实几何。

## 影响

- 实例名唯一、连接引用的端口存在、组件 id 品类等跨对象关系，JSON Schema 无法完全表达，由代码校验（M3）
- 实施细则第九节的 golden 示例已按新格式更新
