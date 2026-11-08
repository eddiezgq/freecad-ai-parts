# 问渠电子 KiCad 插件（第 113 轮）

KiCad 9 起可用。工具栏上多一个按钮“WenQuest: check board”：按下后检查编辑器里打开的板子，在浏览器里开一个只在本机的结果页（127.0.0.1）。

- 每一条结果点“定位”，KiCad 里选中那个器件并放大。
- “把摆放读回设计描述”：板子文件夹（或上一层）里有 `design.yaml` 时，把 KiCad 里挪过的器件写成一份 `design.readback.yaml`，原文件不动。
- “出报告”：在工程文件夹里写 `wqeda-report/report.html`。

工艺能力表：工程文件夹里放 `wqeda-factory.yaml` 就按它查；没有就用插件自带的示例工厂（虚构，示例值）。

判定全由确定性代码做，不调 AI、不联网。KiCad 7、8 用命令行：`python3 -m wqeda.report`、`python3 -m wqeda.readback`。

许可：插件代码属于问渠；用到的库 kicad-python（MIT）、shapely（BSD）、PyYAML（MIT）由 KiCad 按 requirements.txt 装进插件自己的 Python 环境。
