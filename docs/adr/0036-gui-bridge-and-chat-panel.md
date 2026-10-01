# ADR-0036：FreeCAD 界面桥接与内置对话面板

- 状态：已接受（2026-10-01，项目负责人授权先按最优方案决定，可推翻）
- 日期：2026-10-01
- 补充：ADR-0003、ADR-0032

## 背景

M4b 最后一项（#89）是 FreeCAD 工作台与内置对话面板。ADR-0032 预留了 `gui` 后端：用户打开 FreeCAD 时，几何查询在这个会话中完成，布局直接显示在用户眼前。落地前要定以下几点：

- 外部 MCP 客户端（如 Claude Desktop）怎样找到并安全地连上正在运行的 FreeCAD
- FreeCAD 的文档和界面只能在主线程操作，而请求来自其他线程
- 面板作为 MCP 客户端，怎样调用 LLM、怎样测试
- 插件怎样安装到用户的 FreeCAD

## 决策

### 1. 主线程执行器

- `freecad_addon/fc/mainthread.py`：其他线程提交的 FreeCAD 操作，经 Qt 排队信号交给主线程执行，提交方阻塞等待结果
- 等待超时报错，主线程上的异常原样传回
- 在主线程中调用时直接执行

### 2. 界面桥接（`gui` 后端）

1. **监听**
   - FreeCAD 中启用插件的“桥接”后，在 `127.0.0.1` 的随机端口上监听，协议同 worker（JSON 行，ADR-0033）
   - 不对外网开放
2. **连接信息**
   - 写入桥接文件，内容为端口、令牌、进程号
   - 文件位置缺省为 `~/.freecad-ai-parts/bridge.json`，可由 `FAP_BRIDGE_FILE` 指定；权限为仅本人可读写
   - 令牌每次启动随机生成（32 个十六进制字符）；每个请求必须带上令牌，否则拒绝
   - 停止桥接或退出 FreeCAD 时删除该文件
3. **服务端设置**
   - MCP 服务端设 `FAP_FREECAD=gui` 时，读取桥接文件来连接
   - 文件不存在或连不上时，报告“请在 FreeCAD 中启用 AI Parts 桥接”
4. **新增 `sync` 方法**
   - 在 FreeCAD 中重建布局文档 `FapLayout` 并适配视图
   - `gui` 后端下，`place_component`、`connect_ports` 成功后会调用一次，让用户实时看到布局
   - 同步失败不影响工具结果，只在结果的 `view` 字段中注明
   - `headless` 后端不同步
5. **截图**：`gui` 后端下截的就是用户正在看的 FreeCAD 窗口。已有界面时不再检查 `DISPLAY`（Windows、macOS 没有这个变量）

### 3. 内置对话面板

1. **工具调用**
   - 面板运行在 FreeCAD 的 Python 中，在进程内创建 MCP 服务端（`create_server`），用 FastMCP 的内存客户端调用工具
   - 几何后端为进程内的主线程执行器，不经套接字
   - 面板与外部客户端用的是同一套工具（ADR-0003“面板只是另一个 MCP 客户端”）
2. **LLM**
   - Anthropic Messages API 的工具调用循环
   - 工具清单取自 MCP 服务端；系统提示由 `joint_selection` 与 `joint_layout` 两个提示模板的流程组成
   - 每轮用户消息最多调用 20 次工具，超过时停止并说明
   - 截图以图像内容交给 LLM，让它自查
3. **密钥与模型**
   - 密钥只从环境变量 `ANTHROPIC_API_KEY`（或本地 `.env`）读取，不写入任何文件
   - 模型由 `FAP_CHAT_MODEL` 指定，缺省与抽取相同（`claude-sonnet-5-5`）
4. **线程**
   - 对话循环在后台线程中运行，不阻塞界面
   - 面板显示用户消息、每次工具调用（名称与要点）、LLM 的回答和截图
5. **测试**
   - 对话循环与 LLM 客户端分离
   - 测试用按脚本回放的 LLM 响应，不联网（CLAUDE.md）
   - 界面部分标记 `freecad`

### 4. 安装

- `python -m freecad_addon.install`：在 FreeCAD 用户目录的 `Mod/FreeCADAIParts/` 下写入 `InitGui.py`，其中记录本仓库路径，由它导入 `freecad_addon.gui`
  - 能识别 Linux、Windows、macOS 的缺省目录，也可用 `--mod-dir` 指定
- 面板还需要在 FreeCAD 的 Python 中安装本项目依赖：`<FreeCAD 的 python> -m pip install -e ".[llm]"`

## 理由

- **随机端口加令牌**：可以防止本机其他程序误连或冒用；只监听本机，避免把 FreeCAD 暴露到网络
- **面板在进程内调用工具**，免去启动子进程和端口配置；工具、校验与外部客户端完全相同，结果一致
- **主线程执行器同时服务桥接与面板**：FreeCAD 的线程约束只在这一处处理

## 影响

- `FAP_FREECAD` 增加 `gui`
- `freecad_addon` 新增 `fc/mainthread.py`、`fc/bridge.py`、`gui/`、`install.py`
- #89 分两个 PR：先做桥接（gui 后端），再做工作台与面板
