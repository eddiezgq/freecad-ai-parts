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

1. 在 FreeCAD 中启用桥接：在 AI Parts 工作台中点“启用 / 停止桥接”
   - 桥接只监听本机，端口与一次性令牌写在 `~/.freecad-ai-parts/bridge.json`（仅本人可读写）
2. MCP 服务端设置 `FAP_FREECAD=gui`
   - `place_component`、`connect_ports` 之后，FreeCAD 中的 `FapLayout` 文档会自动更新
   - `check_interference` 和 `snapshot` 在这个 FreeCAD 中执行

## 安装工作台与内置对话面板（ADR-0036）

```bash
python -m freecad_addon.install                          # 写入 FreeCAD 用户目录的 Mod/FreeCADAIParts/InitGui.py
<FreeCAD 的 python> -m pip install -e ".[llm]"           # 面板依赖（在本仓库目录下运行）
export ANTHROPIC_API_KEY=...                             # 或写在本仓库的 .env 中（不入 git）
```

重启 FreeCAD 后选择 “AI Parts” 工作台：

- **AI 对话面板**：右侧停靠窗口。用一句话描述需求，助手会：
  - 调用选型、校验与布局工具，布局实时显示在 `FapLayout` 文档中
  - 检查并消除干涉，截图自查，最后按布局复核
- **启用 / 停止桥接**：供外部 MCP 客户端驱动当前 FreeCAD（见上一节）

说明：

- 模型缺省为 `claude-sonnet-5-5`，可用 `FAP_CHAT_MODEL` 更换
- 组件库按 `FAP_LIBRARY` / `DATABASE_URL` 配置；都没设置时用虚构测试组件库，面板顶部会注明
- 卸载：`python -m freecad_addon.install --uninstall`

## 操作录制（ADR-0042）

在 AI Parts 工作台点 **开始 / 停止录制**，录下这次的操作过程，供 AI 学习。录制默认关闭；录制期间，状态栏一直显示“● 录制中”。

- **录什么**：
  - 界面命令
  - 文档改动：增加、删除、属性前后的值，每条都标明来自用户（`user`）还是 AI 助手的工具调用（`ai`）
  - 选择
  - 对话面板的消息与工具调用
  - 重算后的 3D 视图截图，至少间隔 2 秒
- **停止时**：请你评价这次结果（采纳 / 修改后采纳 / 未采纳），可以不评；最后的方案与校验结论一并记下
- **存在哪**：本机 `~/.freecad-ai-parts/sessions/<时间>-<编号>/`，可用 `FAP_SESSIONS_DIR` 另指目录；不自动上传
  - `meta.json`
  - `events.jsonl`
  - `snapshots/`
  - `outcome.json`
- **隐私**：写盘前去掉密钥（`ANTHROPIC_API_KEY` 的值、`sk-ant-…` 等）；属性值只记简短表示，不记形体数据

**视频（可选）**：点 **开始 / 停止录制（含视频）**，会另外用 ffmpeg 录 FreeCAD 主窗口所在区域，存为会话目录中的 `video.mp4`。

- 支持 Linux（X11）与 Windows；需要 ffmpeg，可用 `FAP_FFMPEG` 指定路径
- 录不了时（没有 ffmpeg、macOS、Wayland）在 FreeCAD 报告视图中说明原因，其他内容照常录制

**查看、导出与重放**：

```bash
python -m freecad_addon.sessions list                       # 列出会话
python -m freecad_addon.sessions show <会话>                 # 摘要：事件数、改动来源、命令、工具调用、结果
python -m freecad_addon.sessions export ds.jsonl --rated-only   # 导出数据集，每行一个会话
<FreeCAD 的 python> -m freecad_addon.sessions replay <会话> --save out.FCStd   # 在新文档中重建对象
```

数据集的每行包含：需求原话、对话、操作序列（每步标 `user` / `ai`）、命令、截图、评价、最后的结论，以及 `user_edits_after_ai`，即用户在 AI 改过之后又改的属性。

重放只重建参数化对象（类型、属性、位置）。形体数据不录，AI 布局里的零件可用会话中记下的工具调用重新生成。

**相似会话检索**：对话面板收到一句需求时，在录制会话目录中找出相似的历史会话，作为参考附在提示词后面。面板里会显示一行灰字“参考了相似的历史录制会话”。

- **相似度**：两次需求原话的词项重合度，加上用到的相同组件；结果确定
- **参考内容**：只有历史需求、评价与说明、用户对 AI 的修改、最后的结论；“未采纳”的会话也会列出，作为反例
- 能不能用仍以本次工具的校验结果为准
- 设 `FAP_SESSION_HINTS=0` 可关闭
