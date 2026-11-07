# ADR-0088：问渠电子设计描述的变体（wqeda.variant/1）加 `add_pours`（新增铺铜）

- 状态：已接受（2026-11-07 按项目负责人长期授权执行问渠第 110 轮细则）
- 日期：2026-11-07
- 补充：ADR-0086（仓库根下共用 `eda/`）

## 背景

问渠第 110 轮驱动板 B 版加抱闸驱动：抱闸线圈从 48 V 母线供电。母线在板上是顶层铺铜（底稿 `board.pours`），
布线器把铺铜当禁布区，母线又按 2.5 mm 宽线走，新加的抱闸接口 J6、续流二极管 D5 的母线脚连不上（DRC“未连接”）。
变体原来只能改引脚、改说明、加器件、加摆放，加不了铺铜；改底稿又会动 A 版（A 版要一字不动）。

## 决策

1. 变体加可选字段 `add_pours`：列表，每块 `{net, layer, points}`（与底稿 `board.pours` 同样写法），`points` 至少 3 个 `[x, y]`（mm）。
2. 校验（`eda/wqeda/schema/design.py` 的 `validate_variant`）：缺 `net` / `layer`、`points` 不对、有不认识的字段都报错。
3. 打补丁（`apply_variant`）：追加到 `board.pours`，改动清单记一行“铺铜：新增 <网络> 铺铜（<层>）”。
4. 没写这个字段的变体行为不变；底稿格式（wqeda.design/1）不变；不改 `schema/`（零件库 JSON Schema）、`engine/`，不碰 `tests/golden/`。

## 后果

- 驱动板 B 版 `factory/designs/drv-joint-b/variant.yaml` 用它把母线铺铜往右接出一条到 J6 / D5。
- 测试 `eda/tests/test_schema.py`（报错三种、正确的不报、B 版展开后多一块铺铜）。
