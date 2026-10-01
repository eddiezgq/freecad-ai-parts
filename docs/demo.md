# 演示：从一句需求到 BOM

V1 的目标流程：用一句话描述关节需求，得到校验过的方案、FreeCAD 中的布局、BOM 与 URDF（M5，ADR-0037）。下面三种方式由易到难，结果相同；组件都是虚构的测试组件（ADR-0015）。

## 一、离线命令行（不需要密钥，几分钟）

```bash
git clone https://github.com/eddiezgq/freecad-ai-parts.git && cd freecad-ai-parts
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
python -m mcp_server.e2e "六轴机械臂第 2 关节：输出连续扭矩 25 N·m、峰值 50 N·m，输出转速 30 rpm，220 V 单相供电，EtherCAT 总线" --out out/
```

打开 `out/README.md`，可以看到：

1. **需求**：每个数值的原文依据。离线时回放的是示例句子的模拟录制，汇总中会注明
2. **方案**：200 W 电机经轴套与转接板接 r25 减速器，配 d200 驱动器
3. **布局**：各实例的位置
4. **复核**：11 项校验的结论

另外还有 `bom.csv`、`system.json`、`candidate-1.urdf`。

没有 FreeCAD 时不做干涉检查，退出码为 2。

## 二、加上 FreeCAD（Linux）

```bash
scripts/fetch_freecad.sh                       # 下载锁定版本的 FreeCAD 1.0.2（约 800 MB），核对 SHA-256
sudo apt-get install -y xvfb                   # 没有桌面显示时截图用
FAP_FREECAD=headless python -m mcp_server.e2e "六轴机械臂第 2 关节：…（同上）" --out out/
```

这次 `out/README.md` 会多出干涉检查过程：

- 第 1 轮：驱动器与电机等干涉
- 移开驱动器后，第 2 轮通过
- 转接板列为“需有通孔”，请核对

`out/layout-iso.png` 是布局截图。同一句话重跑，除截图外的文件逐字节相同；样例见 [`examples/joint2/`](../examples/joint2/)。

## 三、在 FreeCAD 里用自然语言（需要密钥）

1. 安装工作台：`python -m freecad_addon.install`
2. 在 FreeCAD 的 Python 中安装依赖：`<FreeCAD 的 python> -m pip install -e ".[llm]"`
3. 设置 `ANTHROPIC_API_KEY`（环境变量，或写在本仓库的 `.env` 中），启动 FreeCAD
4. 切换到 “AI Parts” 工作台，打开 “AI 对话面板”，输入上面那句话，并加一句“在 FreeCAD 里布局并消除干涉”

助手会依次调用选型、校验、布局、干涉检查与截图工具，布局实时显示在 `FapLayout` 文档中。详见 [`freecad_addon/README.md`](../freecad_addon/README.md)。

也可以用 Claude Desktop 驱动打开着的 FreeCAD：在工作台中“启用桥接”，MCP 服务端设 `FAP_FREECAD=gui`，用提示模板 `joint_layout`。见 [mcp-client.md](mcp-client.md)。

## 真实需求解析

离线演示回放的是示例句子的模拟录制。有密钥时：

```bash
pip install -e ".[llm]"
export ANTHROPIC_API_KEY=...        # 或写在本仓库的 .env 中（不入 git）
python -m mcp_server.e2e "你的一句话需求" --record --out out/
```

`--record` 会真实调用 LLM 解析需求，并把响应录制到 `tests/recordings/requirement/`；之后同一句话可以离线复现。解析时，每个数值都要能在原话里找到依据（数字、单位、指标名称），缺少连续扭矩或转速时会列出追问，不会猜。
