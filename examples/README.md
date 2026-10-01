# 示例

| 文件 | 内容 |
| --- | --- |
| `joint2-requirement.json` | 六轴机械臂第 2 关节的结构化需求（含原话） |
| `joint2/` | 由上面的需求经端到端演示生成的全部输出（ADR-0037） |

`joint2/` 中的文件：

- `README.md`：汇总，包括方案、干涉检查过程、最终布局和按布局复核的结论
- `bom.csv`、`bom.json`：BOM，含来源文档
- `system.json`：系统、布局、校验报告和所用组件数据，一个文件即可复现校验
- `candidate-1.urdf`：URDF（米、弧度，ADR-0035）
- `layout-iso.png`：FreeCAD 布局截图

组件都是虚构的测试组件（ADR-0015），不代表任何真实产品。

重新生成（需要 FreeCAD，见 `freecad_addon/README.md`）：

```bash
FAP_FREECAD=headless python -m mcp_server.e2e --requirement examples/joint2-requirement.json --out examples/joint2
```

CI 的 `freecad` 作业会重新生成这些文件，并逐字节比对（截图除外）；样例与代码不一致时测试失败。主作业也会检查：

- `system.json` 中的报告与引擎重新校验的结果相同
- BOM 与按系统重新导出的结果相同
