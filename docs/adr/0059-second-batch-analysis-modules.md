# ADR-0059：第二批分析模块——拓扑优化、数控编程、流体（M11）

- 状态：已接受（2026-10-06，项目负责人授权按计划继续；第一批见 ADR-0056）
- 日期：2026-10-06
- 补充：ADR-0056（本地运行的分析模块）、ADR-0058（本地工厂）

## 背景

ADR-0056 把数字工厂已验证的计算按“每个功能一个模块、在本机 FreeCAD 里算”搬进 `analysis/`，第一批（多体动力学、
有限元 + 疲劳、热分析 + 设计优化、数字孪生）已在 M10 完成。数字工厂里还有三项已验证、带标准题的计算没有搬：
拓扑优化（`cae/topo.py`）、数控编程（`cae/cam*.py`）、流体（`cae/cfd*.py`、`cae/foam.py`）。工厂整套已在 `factory/`
（ADR-0058），但那里是网页用法；企业在 FreeCAD 里设计零件时要能直接用。

## 决策

1. **第二批三个模块，顺序**：拓扑优化 → 数控编程 → 流体。前两个是纯 Python（numpy / scipy），装好 FreeCAD 即可用；
   流体需要 OpenFOAM。约定沿用 ADR-0056：`analysis/<模块>` 定义 `MODULE`、`available()`、`run(setup)`，结果是
   analysis-result/1；不联网、不调用 LLM；结果不写入零件参数；每个模块带与解析解或教材公式对照的标准题，CI 中跑。
2. **拓扑优化 `analysis/topo`**：平面件 SIMP（Andreassen 等 2011 的 88 行算法）。预设（MBB 梁、悬臂、简支、支架）
   与自定的尺寸、支承、载荷；结果为密度分布、柔度历程，按密度 0.5 取轮廓拉伸成板件放进 FreeCAD 文档，
   可接着做有限元校核。标准题：MBB 60×20、体积比 0.5、p = 3、r_min = 1.5 的柔度与原文结果（203）差 < 2%，体积比守住。
3. **数控编程 `analysis/cam`**：两种用法——
   - 生成：阶梯轴车削（端面、粗车、精车、切槽）与 2.5 轴铣削（键槽、型腔、外轮廓、钻孔）→ FANUC 风格 G 代码；
   - 检查：读任何 FANUC 风格 G 代码（包括 FreeCAD 自带 CAM 工作台输出的），算加工时间、仿真切削、检查快移撞料、
     过切 / 残留、超程、转速超限、切削功率（Kienzle）。
   机床参数由企业自己填（`~/.freecad-ai-parts/machines.yaml`）；仓库只带示例机床，明确标“示例（虚构）”。
   Kienzle 单位切削力表带出处原样搬入（`analysis/common/kienzle.yaml`），缺的材料不估。
   标准题：车削基本时间 T = L·i/(f·n)、n = 1000·v_c/(π·d) 与手算一致（< 0.1%）；Kienzle 切削功率与手算一致（< 0.1%）；
   生成的阶梯轴程序仿真后与设计轮廓一致（无过切、残留 < 0.05 mm）。
4. **流体 `analysis/cfd`**：OpenFOAM（simpleFoam / buoyantSimpleFoam + snappyHexMesh）虚拟风洞、风道与强制对流换热，
   几何取 FreeCAD 场景零件的 STEP。OpenFOAM 不随 FreeCAD 安装：查找顺序 `FAP_OPENFOAM_BIN` → PATH；找不到时模块报
   “不可用”及安装方法（Linux：发行版 openfoam 包；Windows：WSL 中安装或 blueCFD-Core），其余模块照常。
   标准题：平行平板层流压降（Poiseuille，< 3%）、平板层流换热（Pohlhausen，< 5%）、平行平板湍流摩擦与换热
   （Blasius、Dittus–Boelter，< 10%）、绕圆柱 Re = 40 阻力系数在 1.52–1.57 附近（< 5%）。
5. **FreeCAD 入口**：“分析”菜单各加一项；MCP `run_analysis` 自动列出新模块（`MODULE_PATHS` 加三项）。
6. **不在本批**：工厂计算服务与 `analysis/` 合并为一份（ADR-0058 第 4 条）仍以后另写 ADR；本批搬入时两份各自保留标准题。

## 后果

- 企业在 FreeCAD 里就能做轻量化构形、出 G 代码并检查、看风冷流场与散热，不用打开工厂网页
- 流体在 Windows 上需另装 OpenFOAM，验收时如本机未装，以“报不可用及安装方法、其余照常”为准
- 示例机床是虚构参数，只用于演示；真实机床参数由企业填，缺的为待确认
