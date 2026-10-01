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
PYTHONPATH="$FC/usr/lib" xvfb-run -a -s "-screen 0 1280x1024x24" "$FC/usr/bin/python" -m pytest -m freecad -v
```

普通的 `python -m pytest` 会跳过标记为 `freecad` 的测试；CI 的 `freecad` 作业会运行这些测试，并且不允许跳过。

## FreeCAD worker

MCP 服务端通过 `freecad_addon.fc.client.HeadlessWorker` 用 FreeCAD 内带的 Python 启动 `python -m freecad_addon.fc.worker`，按 JSON 行协议请求干涉检查与截图（ADR-0033）。

- 路径：`FAP_FREECAD_PYTHON`、`FAP_FREECAD_LIB`；缺省用 `scripts/fetch_freecad.sh` 的解包位置
- Linux 下没有显示环境时，自动在 `xvfb-run` 下启动

干涉结果包括：

- `interferences`：干涉对、重叠体积、包围盒、两者是否有配合关系
- `pass_through`：轴从根部到孔口之间穿过的同组零件，需人工确认这些零件有通孔

## 界面桥接（gui 后端，ADR-0036）

让外部 MCP 客户端（如 Claude Desktop）驱动你打开的 FreeCAD：布局实时显示在窗口里，截图截的就是这个窗口。

1. 在 FreeCAD 中启用桥接
   - 工作台完成前（#89），可以在 FreeCAD 的 Python 控制台中运行：
     ```python
     import sys; sys.path.insert(0, "/path/to/freecad-ai-parts")
     from freecad_addon.fc.bridge import Bridge; bridge = Bridge(); bridge.start()
     ```
   - 桥接只监听本机，端口与一次性令牌写在 `~/.freecad-ai-parts/bridge.json`（仅本人可读写）
2. MCP 服务端设置 `FAP_FREECAD=gui`
   - `place_component`、`connect_ports` 之后，FreeCAD 中的 `FapLayout` 文档会自动更新
   - `check_interference` 和 `snapshot` 在这个 FreeCAD 中执行
