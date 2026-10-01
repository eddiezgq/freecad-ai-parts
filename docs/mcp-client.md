# 接入外部 MCP 客户端（M4a）

M4a 的工具不依赖 FreeCAD，可以先在外部 MCP 客户端（如 Claude Desktop）里用自然语言完成选型（ADR-0003“先外后内”）。

## 1. 安装

```bash
git clone https://github.com/eddiezgq/freecad-ai-parts.git
cd freecad-ai-parts
python -m venv .venv && source .venv/bin/activate   # Windows：.venv\Scripts\activate
pip install -e .
```

## 2. 选择组件库

| 方式 | 环境变量 | 说明 |
| --- | --- | --- |
| 虚构组件库（开发、演示用） | `FAP_LIBRARY=<仓库>/tests/golden/fixtures` | 全部为 `test.` 开头的虚构组件，数值不代表真实产品 |
| 知识库快照目录 | `FAP_LIBRARY=<快照目录>` | `kb.store.export_snapshot` 导出的 `<品类>/<id>.json` |
| 知识库 | `DATABASE_URL=postgresql://...` | PostgreSQL + pgvector（ADR-0018） |

## 3. 配置 Claude Desktop

在 Claude Desktop 的配置文件（Settings → Developer → Edit Config）的 `mcpServers` 中加入下面这段，路径换成本机实际位置：

```json
{
  "mcpServers": {
    "freecad-ai-parts": {
      "command": "/path/to/freecad-ai-parts/.venv/bin/python",
      "args": ["-m", "mcp_server.server"],
      "env": {"FAP_LIBRARY": "/path/to/freecad-ai-parts/tests/golden/fixtures"}
    }
  }
}
```

Windows 下 `command` 为 `C:\\path\\to\\freecad-ai-parts\\.venv\\Scripts\\python.exe`。重启 Claude Desktop 后，工具列表中应出现 11 个工具：

- 选型与校验：`server_info`、`search_components`、`get_component`、`find_compatible`、`compose_chain`、`verify_system`、`export_system`
- FreeCAD 布局（M4b）：`place_component`、`connect_ports`、`check_interference`、`snapshot`

另有一个提示模板 `joint_selection`。

### FreeCAD 布局工具（可选）

`place_component`、`connect_ports` 不需要 FreeCAD。`check_interference`、`snapshot` 需要在 `env` 中加 `"FAP_FREECAD": "headless"`，服务端会按需启动一个无界面的 FreeCAD（ADR-0032、ADR-0033）。

- Linux：先运行 `scripts/fetch_freecad.sh` 下载锁定版本的 FreeCAD 1.0.2。worker 只用标准库和本仓库代码，FreeCAD 的 Python 里不需要另装依赖
- 其他系统：用 `FAP_FREECAD_PYTHON` 指向 FreeCAD 内带的 Python，必要时用 `FAP_FREECAD_LIB` 指向 FreeCAD 模块目录

没有设置时，这两个工具会返回“未连接 FreeCAD”的说明。

布局完成后，`verify_system` 和 `export_system` 加上 `use_layout: true`，就会用当前布局作为系统的 `layout`（ADR-0034）：

- C11 会计算包络长度
- `export_system` 可以导出 `urdf`（ADR-0035）

## 4. 试一句话需求（M4a 验收）

在 Claude Desktop 中输入：

> 给六轴机械臂第 2 关节选一套驱动：输出连续扭矩 25 N·m、峰值 50 N·m，输出转速 30 rpm，220 V 单相供电，EtherCAT 总线。

预期过程：客户端的 LLM 把需求转成结构化需求，调用 `compose_chain`，然后展示候选方案的组成、整体结论（通过、有条件可用等）和每个告警的原因。每个方案都经过 11 项校验。在虚构组件库上，排第一的是 200 W 电机经轴套与适配法兰板接 r25 减速器（全部通过）；400 W 电机直连 r20 的方案排在后面，带一条“减速器过载保护”告警，提示在驱动器里设置扭矩限幅。

还可以接着问：
- “方案 1 的 BOM 导出成 CSV”（`export_system`）
- “m200 电机的轴能接哪些减速器？”（`find_compatible`，会注明哪些需要经轴套）
- “把输出转速改成 70 rpm 再校验一次”（`verify_system`，C7 会判不通过）

## 5. 不用客户端，离线复现同一流程

```bash
python -m mcp_server.demo examples/joint2-requirement.json          # 中文说明
python -m mcp_server.demo examples/joint2-requirement.json --lang en
```

脚本经 MCP 协议调用同一组工具，依次输出候选方案、方案 1 的复核和 BOM。

## 6. 布局演示（M4b）

```bash
FAP_FREECAD=headless python -m mcp_server.layout_demo examples/joint2-requirement.json --out out/
```

脚本按提示模板 `joint_layout` 的流程，经 MCP 工具依次完成：

1. 选出候选方案
2. 按端口摆放（`place_component`、`connect_ports`）
3. 检查干涉，把不在同一刚性组的干涉件（如驱动器）移开，直到没有干涉
4. 截图
5. 按布局复核（C11 长度）并导出 URDF

截图和 URDF 保存在 `out/`。在 Claude Desktop 中，可以用 `joint_layout` 提示，让客户端的 LLM 自己走这套流程。

## 7. HTTP 方式（MCP + REST）

```bash
freecad-ai-parts-mcp --http --port 8000
# MCP：http://127.0.0.1:8000/mcp
# REST：http://127.0.0.1:8000/api/health、/api/components、/api/compose、/api/layout/… （见 mcp_server/rest.py）
```
