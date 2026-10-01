# V1 实施细则

- 版本：1.0（2026-09-30 定稿）
- 在线版（含关节模组端口连接图）：https://claude.ai/code/artifact/ffce2bff-a1ce-4a2a-a45a-b8e50a67baee

本细则把[整体架构](README.md)和 V1 开发计划落实为可执行的规则和字段级规格，重点是 M1 要定稿的 schema。第二节的 AI 编码助手规则同时写在仓库根目录 `CLAUDE.md` 中。

## 一、总则

1. **适用范围**：适用于 V1（M0–M5）全部开发、数据录入和验收工作，包括人工和 AI 编码助手完成的工作。
2. **文件优先级**：架构文档 > 本细则 > 开发计划 > `docs/` 其他文件与 `CLAUDE.md` > 代码注释。上下冲突时以上位文件为准，并在同一周内修正下位文件。
3. **先文档后代码**：范围、接口、schema、校验规则的任何变更，先改文档并写决策记录（ADR），再改代码。
4. **不确定即未知**：数据缺失或无法确认时标记为“未知”，任何环节不得猜测或用默认值填补；校验遇到未知数据时结果为“未知”，不得判为通过。
5. **可追溯**：每个参数能追到来源文件和页码，每个代码改动能追到任务和评审记录。
6. **进度状态**：M0 已于 2026-09-30 提前完成；M1 提前至 2026-10-05 开工，缓冲期相应增加 1 周，V1 完成日期（2027-02-28）不变。

## 二、开发流程细则

一个任务从建立到合并走固定的 6 步；即使只有一名开发者，也走 PR，因为 PR 是评审 AI 改动的入口。

1. **建任务**：在 GitHub Issues 建一个 issue，归入对应里程碑（M1…M5）。内容必须有三项：目标、涉及的 schema 或接口（链接到文件）、验收标准（写成可执行的测试或检查项）。
2. **开分支**：从 `main` 开分支，命名 `m<阶段>/<简述>`，例如 `m1/port-types`。`main` 为受保护分支，不直接推送。
3. **实现**：人或 AI 编码助手按 issue 实现，每个改动附测试。
4. **提交**：提交信息格式为 `M1: <做了什么>`，正文写原因和关联的 issue（`#12`）。
5. **PR 与 CI**：开 PR，CI 必须全绿；PR 描述列出改了什么、怎么验证的。
6. **评审与合并**：人逐行看 diff，对照 issue 的验收标准确认后 squash 合并，关闭 issue。

**AI 编码助手使用规则**（见 `CLAUDE.md`，对每个会话生效）

- 一次只做一个 issue；超出 issue 范围的改动另开 issue
- 同一个 PR 不得同时改 `schema/` 和实现代码；schema 改动单独成 PR，并附 ADR
- **不得修改 `tests/golden/` 的预期结果来让测试通过**；golden 用例的增删改只能由人决定
- 不得跳过、删除或弱化已有测试和校验
- 不得在代码或数据里编造参数值；缺数据就标记未知并在 PR 里说明
- 密钥只从环境变量读取，不写入仓库
- 每次会话结束前运行 `ruff check .` 和 `python -m pytest`，结果写入 PR 描述

## 三、代码与仓库规范

| 项目 | 规范 |
| --- | --- |
| 语言与版本 | Python 3.11+；全部函数写类型注解 |
| 风格检查 | ruff，行宽 100；CI 不通过不合并 |
| 数据对象 | 跨模块传递的数据用 pydantic 模型，从 `schema/` 的 JSON Schema 生成或与其对照测试，两者不得各自演化 |
| 引擎代码 | `engine/` 的校验函数必须是纯函数：不联网、不调用 LLM、不读数据库，输入相同则输出相同 |
| LLM 调用 | 只出现在 `ingest/`（规格书抽取）和 `engine/` 的需求解析、方案解释模块；输出必须经 schema 校验才能进入下一步 |
| 单位 | 代码内部只用第四节规定的标准单位；单位换算只在 `ingest/` 入口处用 pint 完成 |
| 测试 | pytest；测试不联网、不调用真实 LLM（用录制的响应）；FreeCAD 相关测试标记 `@pytest.mark.freecad`，只在本地运行 |
| 密钥 | 放在本地 `.env`（已在 `.gitignore`），提供 `.env.example` 说明字段 |
| 版本号 | 代码包与 schema 分别用语义化版本；M1 定稿时 schema 为 `0.1.0`，破坏性改动升次版本号并写 ADR |
| 文档语言 | 文档和注释用中文；标识符、字段名、枚举值用英文小写加下划线 |

## 四、schema 通用约定

所有对象共用三项约定：统一的命名、统一的存储单位、统一的参数值结构。

### 1. 命名

- 组件 id：`<品类>.<厂商>.<型号>`，全小写，厂商和型号中的空格、斜杠换成连字符，例如 `reducer.harmonic-drive.shg-20-100-2uh`；一经发布不再改名
- 品类：`servo_motor`、`reducer`、`drive`、`bearing`，紧固件为 `fastener`，转接件为 `adapter`
- 端口 id：在组件内唯一，用功能命名，如 `shaft`、`mount_flange`、`output_flange`、`power_in`、`encoder`
- 端口类型：`<域>.<名称>`，域为 `mechanical`、`electrical`、`signal`

### 2. 存储单位（入库前一律换算，字段名带单位后缀）

| 物理量 | 单位 | 字段后缀 | 备注 |
| --- | --- | --- | --- |
| 长度 | mm | `_mm` | 机械行业惯例 |
| 扭矩 | N·m | `_nm` | |
| 转速 | rpm | `_rpm` | |
| 质量 | kg | `_kg` | |
| 转动惯量 | kg·m² | `_kgm2` | 规格书常用 kg·cm² 或 10⁻⁴ kg·m²，入库时换算 |
| 功率 | W | `_w` | |
| 电压 | V | `_v` | 注明 AC/DC |
| 电流 | A（有效值） | `_a` | 规格书若给峰值须换算并在来源备注中注明 |
| 力 | N | `_n` | |
| 角度（回差） | arcmin | `_arcmin` | |
| 效率 | 0–1 的小数 | `_ratio` | 不用百分数 |

### 3. 参数值结构

每个参数是一个对象，而不是裸数字：

```json
"rated_torque_nm": {
  "value": 1.27,
  "condition": "at rated speed, 25 °C",
  "source": {"doc": "src-yaskawa-sgm7j-catalog", "page": 42},
  "method": "extracted",
  "confidence": 0.95,
  "reviewed": true
}
```

- 数值三选一：`value`（单值）、`min`/`max`（范围）、`nominal` + `tol_upper`/`tol_lower`（公差）
- `condition`：该值成立的工况，规格书有就必填（如减速器效率随转速、负载、温度变化）
- `source`：来源文档 id（对应 `data/sources.yaml` 登记）和页码；计算得出的值写明公式
- `method`：`extracted`（LLM 抽取）、`manual`（人工录入）、`computed`（由其他参数计算）、`standard`（按标准生成，如 ISO 紧固件）
- `confidence`：0–1；人工录入并复核的记为 1
- `reviewed`：是否经人工复核
- 缺失的参数直接不写，不写 `null`、`0` 或估计值

## 五、端口类型规格

V1 共 8 种端口类型：4 种机械、2 种电气、2 种信号，覆盖关节模组里所有连接。

关节模组的连接关系：电源 →（power_supply）→ 驱动器；上位控制器 ↔（fieldbus）↔ 驱动器；驱动器 →（motor_power）→ 伺服电机；伺服电机 →（encoder）→ 驱动器；伺服电机轴 →（cyl_male → cyl_female）→ 减速器输入孔；伺服电机法兰 ↔（flange）↔ 减速器电机法兰；减速器输出法兰 →（flange）→ 负载连杆；轴承内圈 ↔（cyl）↔ 连杆轴，外圈装入关节壳体。电机与减速器之间的两条机械连接（轴传递扭矩、法兰固定壳体）都要单独校验。

### 所有端口的公共字段

| 字段 | 说明 |
| --- | --- |
| `id` | 组件内唯一 |
| `type` | 下表 8 种之一 |
| `dir` | `in` / `out` / `bidir`；机械端口按功率流向填（电机轴为 `out`，减速器输入孔为 `in`），固定连接填 `bidir` |
| `motion` | 仅机械端口：`rotating`（随转子转动）或 `stationary`（与壳体固定）；转动端口只能接转动端口 |
| `frame` | 仅机械端口：端口坐标系在组件包络坐标系中的位置 `origin_mm [x,y,z]` 和轴向 `axis [x,y,z]`（单位向量，指向配合方向）；FreeCAD 装配靠它对齐 |
| `spec` | 类型专属字段，见下表；每个字段都用第四节的参数值结构 |

### 8 种端口类型

| 类型 | 含义 | 必填字段 | 选填字段 | 可连接到 |
| --- | --- | --- | --- | --- |
| `mechanical.cyl_male` | 轴 / 外圆柱配合面（电机轴、轴承外圈） | `diameter_mm`、`fit`（ISO 286 公差带如 `h6`、`k6`；轴承外圈为精度等级如 `P0`）、`feature`（`plain` / `keyed` / `d_cut` / `spline`） | `fit_system`（`iso286` 缺省 / `bearing`）、`usable_length_mm`、`key_width_mm`、`max_radial_load_n`、`max_axial_load_n` | `cyl_female` |
| `mechanical.cyl_female` | 孔 / 内圆柱配合面（减速器输入孔、轴承内圈、轴承座孔） | `diameter_mm`、`fit`（ISO 286 公差带如 `H7`；轴承内圈为精度等级如 `P0`）、`feature`、`clamping`（`key` / `clamp_ring` / `set_screw` / `press_fit`） | `fit_system`（`iso286` 缺省 / `bearing`）、`depth_mm`、`key_width_mm`、`accepted_diameter_range_mm`（可换轴套时） | `cyl_male` |
| `mechanical.flange` | 圆形安装法兰（电机法兰、减速器输入/输出法兰） | `pcd_mm`、`hole_count`、`hole_kind`（`through` / `threaded`）、`hole_diameter_mm` 或 `thread`（如 `M5`） | `pilot_diameter_mm`、`pilot_kind`（`male` / `female`）、`pilot_fit`、`square_size_mm`、`hole_angle_offset_deg` | `flange` |
| `mechanical.mount_face` | 非圆形安装面（驱动器底板、壳体安装面） | `pattern`（`rect`，含 `pitch_x_mm`、`pitch_y_mm`）、`hole_count`、`hole_diameter_mm` 或 `thread` | `face_size_mm`、`din_rail` | `mount_face` |
| `electrical.power_supply` | 供电输入/输出（电网、直流母线 → 驱动器） | `current_type`（`ac` / `dc`）、`voltage_v`（范围）、`phases`（1 / 3，直流填 0） | `rated_current_a`、`frequency_hz`、`connector` | `power_supply` |
| `electrical.motor_power` | 驱动器 → 电机的动力线 | `voltage_class_v`、`rated_current_a`、`peak_current_a` | `connector`、`brake_voltage_v` | `motor_power` |
| `signal.encoder` | 编码器反馈（电机 → 驱动器） | `protocol`（如 `endat_2_2`、`biss_c`、`ssi`、`incremental_abz`、`vendor_proprietary`）、`kind`（`absolute` / `incremental`） | `resolution_bits`、`multi_turn`、`vendor`（私有协议必填）、`connector` | `encoder`（驱动器端填支持的协议列表） |
| `signal.fieldbus` | 总线与命令接口（控制器 ↔ 驱动器） | `protocol`（`ethercat` / `canopen` / `modbus_rtu` / `profinet` / `ethernet_ip` / `pulse_dir`） | `profile`（如 `cia402`）、`connector` | `fieldbus` |

### 公差体系（ADR-0013）

滚动轴承内外圈的尺寸公差由轴承精度等级规定（ISO 492：Normal、6、5、4、2 级，常记作 P0、P6、P5、P4、P2），不属于 ISO 286 公差带。圆柱端口用 `fit_system` 区分：缺省或 `iso286` 时 `fit` 为 ISO 286 公差带，`bearing` 时 `fit` 为轴承精度等级。

### 建模约定（ADR-0007）

- 减速器 V1 只收录带壳体和输出轴承的“整机型”（unit），不收录谐波减速器的零件型（component set），以保持端口简单
- 多系列共用的连接要素（可换轴套、适配法兰）建成独立的 `adapter` 组件，用来表达不同品牌之间的转接，不在端口里写条件分支

## 六、品类参数规格

必填参数就是第七节校验要用到的参数，也就是录入和复核时的“关键字段”；必填项缺失的组件可以入库，但相关校验结果为“未知”。**接口数据只放在端口里，不在参数表重复**（ADR-0014）：尺寸、电流、电压、协议等描述连接的数据写在对应端口的 `spec` 中；参数表只允许列出的必填与选填参数。

| 品类 | 必填参数 | 选填参数 | 标准端口 |
| --- | --- | --- | --- |
| 伺服电机 `servo_motor` | `rated_power_w`、`rated_torque_nm`、`peak_torque_nm`、`rated_speed_rpm`、`max_speed_rpm`、`rotor_inertia_kgm2`、`mass_kg` | `brake`、`ip_rating`、`torque_constant_nm_per_a`（法兰边长写在 `mount_flange` 端口的 `square_size_mm`） | `shaft`（cyl_male, out, rotating）、`mount_flange`（flange, stationary）、`power_in`（motor_power, in；额定/峰值电流在此）、`encoder`（encoder, out） |
| 减速器 `reducer` | `reducer_kind`（`harmonic` / `planetary`）、`ratio`、`rated_torque_nm`（注明工况）、`repeated_peak_torque_nm`、`momentary_max_torque_nm`、`max_input_speed_rpm`、`efficiency_ratio`（注明工况）、`mass_kg` | `avg_input_speed_limit_rpm`、`backlash_arcmin`（行星）、`lost_motion_arcmin`（谐波）、`torsional_stiffness_nm_per_arcmin`、`input_inertia_kgm2`、`output_bearing_dynamic_load_rating_n`、`output_bearing_moment_load_rating_nm` | `input_bore`（cyl_female, in, rotating）、`motor_flange`（flange, stationary）、`output_flange`（flange, out, rotating）、`housing_mount`（flange 或 mount_face, stationary） |
| 驱动器 `drive` | 无（供电、输出电流、支持的编码器与总线协议都在端口里） | `rated_output_power_w`、`safety_functions`（如 STO）、`mass_kg` | `power_in`（power_supply, in；电压、相数）、`motor_out`（motor_power, out；额定/峰值输出电流）、`encoder_in`（encoder, in；支持的协议列表）、`bus`（fieldbus, bidir）、`mount`（mount_face） |
| 轴承 `bearing` | `bearing_kind`（`deep_groove` / `angular_contact` / `cross_roller` / `tapered_roller`）、`width_mm`、`dynamic_load_rating_n`、`static_load_rating_n`、`limiting_speed_rpm` | `moment_load_rating_nm`（交叉滚子）、`seal`、`mass_kg` | `inner`（cyl_female, rotating；内径在此）、`outer`（cyl_male, stationary；外径在此）；两者 `fit_system` 均为 `bearing` |
| 转接件 `adapter` | `adapter_kind`（`sleeve` / `flange_plate`）、`mass_kg` | `length_mm` | 恰为两个端口：轴套为 `inner`（cyl_female）与 `outer`（cyl_male）；适配法兰为两个 flange |

补充规则：

- **带编码器的电机**：同一电机本体配不同编码器、是否带制动器时，按厂商完整型号分别入库，每个型号是一个组件
- **减速器扭矩三个等级分开存**：额定扭矩、启停时允许峰值扭矩、瞬间最大扭矩含义不同，不得合并；厂商叫法不同时在 `condition` 里注明原文名称
- **效率**：谐波减速器效率随转速、负载和温度变化明显，V1 取规格书中额定工况的值，并在校验时使用安全系数（见第七节）
- **包络**：每个组件还要有包络参数（圆柱或长方体的尺寸）和包络坐标系原点约定：原点在安装法兰面中心，z 轴指向输出方向

## 七、连接规则与校验细则

V1 共 11 项静态校验，全部由 `engine/` 的确定性代码完成；每项输出四种状态之一。

| 状态 | 含义 | 对整体结果的影响 |
| --- | --- | --- |
| `pass` | 满足 | — |
| `warn` | 满足但有风险或需额外措施 | 整体可用，方案说明中必须列出 |
| `fail` | 不满足 | 整体不可用 |
| `unknown` | 数据缺失，无法判定 | 整体最多为“待确认”，不得呈现为通过 |

整体结论按优先级取：有 `fail` 即不可用；否则有 `unknown` 即待确认；否则有 `warn` 即有条件可用；全部 `pass` 才是可用。

### 校验清单

| 编号 | 校验 | 判定条件 | 不满足时 |
| --- | --- | --- | --- |
| C1 | 端口兼容 | 类型在“可连接到”列表内；方向为 out→in 或含 bidir；`motion` 相同 | fail |
| C2 | 圆柱配合 | 内外圆柱名义直径相等；公差配对在配合表内（一侧为轴承时，按轴承配合推荐表判定）；`feature` 与 `clamping` 兼容，有键时键宽相等 | 直径或键不符 fail；公差配对不在表内 warn |
| C3 | 法兰配合 | 分度圆直径相差 ≤ 0.05 mm；孔数相等；一侧螺纹孔时，另一侧通孔直径 ≥ 按 ISO 273 中等系列的间隙孔；止口一公一母且直径相等 | 分度圆、孔数、孔径、止口不符 fail；一侧没有止口 warn |
| C4 | 连续扭矩 | 公式 (1)(2) | fail |
| C5 | 峰值扭矩 | 公式 (3)(4) | fail |
| C6 | 减速器过载保护 | 电机峰值扭矩经减速后超过减速器瞬间最大扭矩，公式 (5) | warn（需在驱动器设置扭矩限幅） |
| C7 | 转速 | 所需输出转速 × 减速比 ≤ 电机最高转速，且 ≤ 减速器最高输入转速；超过减速器平均输入转速限制时告警 | fail / warn |
| C8 | 惯量比 | 仅当需求给出负载惯量时计算，公式 (6)，阈值默认 10 | warn |
| C9 | 电气匹配 | 供电电压在驱动器范围内且相数一致；驱动器与电机电压等级一致；驱动器额定电流 ≥ 电机额定电流；驱动器峰值电流 ≥ 电机峰值电流 | 前三项 fail；峰值电流不足 warn（峰值扭矩受限） |
| C10 | 信号匹配 | 电机编码器协议在驱动器支持列表内，私有协议要求同一厂商；驱动器总线协议与需求一致 | fail |
| C11 | 轴承与包络 | 轴承处转速 ≤ 极限转速；系统包络外径和长度 ≤ 需求限值 | fail |

### 扭矩与惯量公式

T 为扭矩，i 为减速比，η 为减速器效率，SF 为安全系数（默认 1.2，用户可在需求中修改，ADR-0008），J 为转动惯量，下标 req 为需求值：

```text
(1)  SF · T_req,cont / (i · η)   ≤ T_motor,rated
(2)  SF · T_req,cont              ≤ T_reducer,rated
(3)  T_req,peak / (i · η)         ≤ T_motor,peak
(4)  T_req,peak                   ≤ T_reducer,repeated_peak
(5)  T_motor,peak · i · η  >  T_reducer,momentary_max   ⇒  warn
(6)  (J_load / i² + J_reducer,in) / J_motor  ≤ 10       （超过则 warn）
```

### 每项校验的输出格式

```json
{"check": "C4", "status": "pass", "measured": 0.92, "limit": 1.27, "unit": "N*m",
 "margin_ratio": 0.28, "ports": ["motor.shaft", "reducer.input_bore"],
 "message": "连续扭矩折算到电机侧 0.92 N·m，低于额定 1.27 N·m"}
```

C2 的公差配合表、C2 的 `feature`/`clamping` 兼容矩阵、C3 的 ISO 273 间隙孔表，在 M1 第 1 周作为数据文件放入 `schema/rules/` 并定稿。

## 八、数据录入与复核细则

所有数据入库前过三道关：来源已登记、schema 校验通过、关键字段已复核。

### 1. 来源登记

- 每个厂商先在 `data/sources.yaml` 登记，核实网站使用条款后把 `terms_checked` 设为 `true` 并写明结论和日期；未核实的来源不得入库
- 每份规格书登记为一个来源文档：id（如 `src-yaskawa-sgm7j-catalog`）、标题、版本或发布日期、下载网址、文件 SHA-256；原始 PDF 放 `data/raw/`，不入 git

### 2. 录入方式

| 阶段 | 方式 | 文件位置 |
| --- | --- | --- |
| M1 种子数据（每类约 5 个型号） | 人工录入，`method: manual` | `data/seed/<品类>/<组件 id>.json`，每个组件一个文件 |
| M2 批量数据（每类 30–50 个型号） | LLM 抽取，`method: extracted`，进复核队列 | 复核通过后写入数据库，并导出为 JSON 快照纳入版本管理 |
| 紧固件 | 按 ISO/DIN 标准表程序生成，`method: standard` | 生成脚本入库，数据由脚本产出 |

### 3. 复核规则

- 关键字段（第六节的必填参数和端口 `spec` 必填字段）一律人工对照原文复核
- 非关键字段：`confidence` < 0.9 的进入复核队列；其余每批按 10% 抽样复核
- 准确率门槛：每品类抽样的关键字段准确率 ≥ 95% 方可批量入库；低于门槛时先改抽取方法，再重新抽取整批
- 复核时发现的错误分类记录（单位错、列错位、工况混淆、型号错配等），作为改进抽取的依据
- 人工录入的种子数据由 AI 对照原文交叉检查一遍，差异由人裁定

### 4. 修改与作废

- 已入库参数的修改保留历史（原值、新值、原因、日期），不覆盖
- 厂商停产或规格书改版时，组件标记 `status: discontinued` 或指向新版来源，不删除

## 九、测试与 golden 用例细则

golden 用例是配置引擎的验收标准：每个错配用例只含一个错误，预期结果精确到哪一项校验、什么状态。

### 1. 用例格式（YAML，每个用例一个文件）

```yaml
id: invalid/flange-pcd-mismatch
description: 电机法兰分度圆 70 mm，减速器输入法兰 63 mm
system:                 # 完整的系统对象，遵循 schema/system.schema.json（ADR-0012）
  id: flange-pcd-mismatch
  requirement:
    output_torque_cont_nm: 20
    output_speed_rpm: 30
    safety_factor: 1.2
  components:
    - {instance: motor, component: test.servo_motor.test-vendor.m100}
    - {instance: reducer, component: test.reducer.test-vendor.r20-100}
    - {instance: drive, component: test.drive.test-vendor.d400}
  connections:
    - {a: motor.shaft, b: reducer.input_bore}
    - {a: motor.mount_flange, b: reducer.motor_flange}
expected:
  overall: fail
  checks:
    C3: fail          # 必须是这一项失败
    others: not_fail  # 其余各项不得为 fail
```

用例引用的组件可以是种子数据，也可以是放在 `tests/golden/fixtures/` 里的虚构测试组件；虚构组件的 id 以 `test.` 开头，永远不进入正式库。

### 2. 覆盖要求

| 阶段 | 正确用例 `valid/` | 错配用例 `invalid/` | 其他 |
| --- | --- | --- | --- |
| M1 结束 | ≥ 3 套完整关节模组 | C1–C11 每项至少 1 个，共 ≥ 11 个 | 每种 `unknown` 情形至少 1 个（故意缺少关键字段） |
| M3 结束 | ≥ 10 套 | ≥ 30 个，含边界值（刚好等于限值、稍微超出） | 每个 `warn` 情形至少 1 个 |
| M4a 结束 | 通过 MCP 工具重跑全部 golden 用例，结果与直接调用引擎一致 | | |

### 3. 其他测试

- schema：每个 `*.schema.json` 合法；每份种子数据都能通过对应 schema 校验；每种端口类型至少 1 个合法样例和 1 个应被拒绝的样例
- 单位换算：常见来源单位（kg·cm²、kgf·cm、峰值电流等）各有测试
- 规格书抽取：用已人工复核的样例比对抽取结果，输出逐字段准确率

## 十、阶段验收流程与 M1 分周任务

### 阶段验收流程（每个里程碑结束时执行）

1. 对照开发计划中该阶段的验收标准，逐条列出证据（测试结果、抽样记录、演示录屏）
2. CI 全绿，golden 用例全部通过
3. 人工演示一遍，记录问题
4. 验收结论写入 `docs/milestones/M<n>.md`：通过 / 有条件通过（附遗留问题和期限）/ 不通过
5. 打标签 `v0.<n>.0`（如 M1 对应 `v0.1.0`）
6. 更新开发计划的剩余工期；需要调整范围时先改架构文档

不通过时不进入下一阶段，先在缓冲期内补足。

### M1 分周任务（2026-10-05 至 10-25）

| 周 | 任务 | 交付物 |
| --- | --- | --- |
| 第 1 周（10/5–10/11） | 建 GitHub 里程碑和 M1 issues；定稿参数值结构与 8 种端口类型 schema；定稿公差配合表、兼容矩阵、间隙孔表 | `schema/common/`、`schema/port-types/`、`schema/rules/` |
| 第 2 周（10/12–10/18） | 组件（含 `adapter`）、系统、需求 schema；4 个品类的参数 schema；登记首批来源并核实条款；录入种子数据约 20 个型号（每类约 5 个） | `schema/component.schema.json` 等、`data/sources.yaml`、`data/seed/` |
| 第 3 周（10/19–10/25） | 编写 golden 用例（≥ 3 正确、≥ 11 错配、若干未知）；用手工数据表达一套完整关节并手算校验结果；schema 评审与定稿 `0.1.0`；M1 验收 | `tests/golden/`、`docs/milestones/M1.md`、标签 `v0.1.0` |

M1 阶段还没有引擎代码，golden 用例的预期结果由人手算确定，到 M3 由引擎自动验证。
