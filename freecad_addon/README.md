# freecad_addon

FreeCAD 1.x 工作台（Python + Qt），在 M4b 实现。架构、配合约定和测试方式见 [ADR-0032](../docs/adr/0032-m4b-layout-architecture.md)。

| 子包 | 依赖 | 内容 |
| --- | --- | --- |
| `core/` | 只用标准库 | 位姿、配合规则、布局场景、世界坐标下的包络描述、包络长度 |
| `fc/` | FreeCAD | 包络实体、干涉计算、截图、FreeCAD worker |
| `gui/`、`InitGui.py` | FreeCAD 界面 | 工作台、零件面板、内置 AI 对话面板 |

各子包的分工：

- 布局场景由 MCP 服务端持有，FreeCAD 文档只是它的视图
- `place_component`、`connect_ports` 的位姿计算不需要 FreeCAD
- `check_interference`、`snapshot` 通过 worker 在 FreeCAD 中执行

内置对话面板按“先外后内”（[ADR-0003](../docs/adr/0003-entry-points.md)）在工具稳定后实现。

## 本地运行 FreeCAD 测试（Linux）

```bash
FC=$(scripts/fetch_freecad.sh)            # 下载锁定版本 1.0.2 并核对 SHA-256，解包到 .freecad/
"$FC/usr/bin/python" -m pip install -e ".[dev]"
PYTHONPATH="$FC/usr/lib" xvfb-run -a "$FC/usr/bin/python" -m pytest -m freecad -v
```

普通的 `python -m pytest` 会跳过标记为 `freecad` 的测试；CI 的 `freecad` 作业会运行这些测试，并且不允许跳过。
