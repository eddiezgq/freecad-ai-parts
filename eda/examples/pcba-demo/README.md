# 工厂端演示资料包（演示用，故意带错）

问渠贴片（第 112 轮 P5）的闭环演示。设计、工厂都是示例，工厂是虚构的。

| 文件 | 是什么 |
|---|---|
| `variant.yaml` | 驱动板 A 版上故意去掉 C47 的物料编号（模拟“设计时忘了填”） |
| `bom.csv`、`pos.csv` | 由 `variant.yaml` 导出：`python3 -m wqeda.package eda/examples/pcba-demo/variant.yaml --out eda/examples/pcba-demo` |
| 光绘 | 用驱动板 A 版的 `factory/designs/drv-joint/out/gerber.zip`（板子没变） |

走一圈：

1. 工厂端上传光绘 + 这里的 `bom.csv`、`pos.csv`，按示例贴片厂查：D1 不通过，C47 只在坐标里。
2. 起草问题单，确认后下载 `issues.yaml`。
3. 设计端：`python3 -m wqeda.issues issues.yaml eda/examples/pcba-demo/variant.yaml` → 指出 C47 没有物料编号。
4. 改设计描述（这里就是去掉 `item_changes`，回到 A 版），重新导出物料清单和坐标，再查：
   `python3 -m wqeda.issues issues.yaml factory/designs/drv-joint/design.yaml --gerber factory/designs/drv-joint/out/gerber.zip --bom <新 bom.csv> --cpl <新 pos.csv> --factory eda/examples/factories/example-smt.yaml` → “已解决”。
