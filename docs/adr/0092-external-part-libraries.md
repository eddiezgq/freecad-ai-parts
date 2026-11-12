# ADR-0092：外部零件库只链接、不转存

- 状态：已接受（2026-11-11，项目负责人确认问渠第 158 轮细则第七节，及 22:45 对第二段的改动）
- 日期：2026-11-11
- 补充：ADR-0040（公开产品目录参数）、ADR-0084（KiCad 官方库）、ADR-0086（共用 `eda/`）

## 背景

项目负责人问到 OpenPartsLibrary（GitHub alekssadowski95）、SnapEDA 上 Seeed 的 Open Parts Library 等外部零件库能否并入，并提出“直接连上就行”。
这些库的许可差别很大：

| 外部库 | 许可 / 条款 | 与本仓库（Apache-2.0）的关系 |
|---|---|---|
| OpenPartsLibrary | AGPL-3.0 | 并入会使组合作品受 AGPL 约束，不相容 |
| SnapEDA / SnapMagic | 单个元件 CC BY-SA 4.0 + 设计例外；网站条款不许拿它的网站当来源在网上转发内容 | 不能批量转存 |
| McMaster-Carr、MISUMI、LCSC、DigiKey | 商业网站，条款限制转存 | 不能转存 |
| FreeCAD 紧固件工作台 | GPL-2.0 | 不相容；标准紧固件已由 bd_warehouse（Apache-2.0）生成 |
| BOLTS | 整体 GPL-3.0，数据逐份不同 | 不相容、逐份核查成本高 |
| Seeed OPL KiCad 库（GitHub Seeed-Studio/OPL_Kicad_Library，提交 b0035c51） | CC BY-SA 4.0 | 许可上可以单独收录，但内容不对口（见理由） |

## 决策

1. **只链接**：外部库一律只做“到外部库查”的搜索链接——按零件库条目或物料清单行自己的型号、尺寸码 + 数值或名称，拼对方网站的搜索地址，新窗口打开；
   不抓取、不转存对方的页面、文件、图片、参数。链接类外部库不入库，不在 `data/sources.yaml` 登记。
   地址模板和拼法规则只有一份代码：`factory/digital/web/src/lib/extlinks.js`（问渠第 158 轮）。
2. **只供查找**：链接带来的信息只供人查找，不进零件参数、不参与任何校验，不影响检查的通过与否。
3. **不收**：OpenPartsLibrary、SnapEDA 的内容；Seeed OPL KiCad 库的索引；FreeCAD 紧固件工作台；BOLTS。

## 理由

- 链接不转存内容，许可与条款问题最少；对方更新时不用跟着改，用户点开看到的是对方的最新数据。
- Seeed OPL KiCad 库：只有 341 种元件（300 种带型号），多是 Arduino 一类的常用料；问渠驱动板物料清单上的芯片一个都不在里面；
  Seeed 的全量常备料清单只在它的报价系统里，没有公开下载。收它的索引，物料清单里那一栏会几乎全是“不在库里”，不如直接链到 LCSC
  （嘉立创贴片用的深圳现货库，点开就能看到有没有货和价格）。
- 替代方案：调用 SnapEDA、Octopart 等商业接口实时查库存——要付费和钥匙，等有试点客户再定。

## 影响

- 零件库页、电路板设计页、问渠贴片检查结果加“到外部库查”的链接（问渠第 158 轮 158a、158b，按 `factory/SYNC.md`、ADR-0086 两边同步）。
- 不改 `data/sources.yaml`、`schema/`、`engine/`，不碰 `tests/golden/`。
