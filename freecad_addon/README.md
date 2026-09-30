# freecad_addon

FreeCAD 1.x 工作台（Python + Qt），M4b 实现：

- 4 类核心零件的包络模板与端口坐标系
- 按端口对齐装配（基于 FreeCAD 1.0 起内置的 Assembly 工作台）
- 干涉检查与截图，供 agent 自查
- 内置 AI 对话面板（先用外部 MCP 客户端验证工具，再做此面板，见 [ADR-0003](../docs/adr/0003-entry-points.md)）
