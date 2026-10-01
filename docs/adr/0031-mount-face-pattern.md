# ADR-0031：安装面孔位阵列增加 linear，明确 rect 的孔位

- 状态：已接受（2026-10-01，项目负责人授权先按最优方案决定，可推翻）
- 日期：2026-10-01

## 背景

issue #39：`mechanical.mount_face` 的 `pattern` 原来只有 `rect`，由 `pitch_x_mm`、`pitch_y_mm`、`hole_count` 描述。驱动器常见的 2 孔安装（上下各一孔）只能写成 `rect` 加 `hole_count: 2`，此时无法确定两孔是同列还是对角。M4b 要在 FreeCAD 中按端口布局，进入布局前要先把孔位的含义定下来。

现有数据（golden fixtures 中的 5 个驱动器，以及模拟规格书目录中的驱动器）都写成 `rect`：2 孔的 `pitch_x_mm` 不为 0，说明两孔左右错开，即位于对角。golden 数据的修改只能由人决定，因此这次变更不能让现有数据变为不合法。

## 决策

1. **坐标约定**：孔位在端口坐标系的安装面内，x 为水平方向，y 为垂直方向，以端口原点为中心
2. **`rect`**：孔位于 `pitch_x_mm × pitch_y_mm` 矩形的角点
   - `hole_count` 只能是 4（占四个角）或 2（占一对对角）
   - 必须给出 `pitch_x_mm` 和 `pitch_y_mm`
3. **新增 `linear`**：孔沿 y 方向排成一列
   - 相邻孔的中心距为 `pitch_y_mm`
   - 不得填写 `pitch_x_mm`
   - `hole_count` 至少为 2
4. **schema 变化**：`pitch_x_mm` 不再是无条件必填，改为在 `rect` 下必填；上述限制由条件约束表达
5. **已知限制**：`rect` 2 孔时，schema 不区分是哪一对对角（左下右上，还是左上右下）
   - V1 不校验安装面之间的孔位是否对得上（引擎没有 mount_face 对 mount_face 的校验），布局也不建模孔，所以暂不区分
   - 以后加孔位匹配校验时，再另写 ADR 补充字段

## 理由

- 只增加枚举值、并收紧 `rect` 的合法孔数：现有数据全部仍然合法，golden 不用改
- 考虑过改用显式孔位列表：表达力最强，但规格书通常只印孔距；人工复核和 LLM 抽取都要换成坐标，出错面更大
- 考虑过用 `pitch_x_mm: 0` 表示同列：语义含糊，0 也可能是抽取错误

## 影响

- `ingest/assemble.py` 补全 `pattern` 的规则：
  - 有 `pitch_x_mm`，且孔数为 2 或 4 时，推为 `rect`
  - 没有 `pitch_x_mm` 时不推断，因为规格书可能只是漏印了水平孔距。由复核员用 `kb.review add` 补 `pattern`；补齐前组件不能入库
  - 这部分实现另开 PR（不与 schema 同一 PR）
- 实施细则第五节端口类型表同步更新
- issue #39 关闭
