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
- 每次会话结束前运行 `python -m ruff check .` 和 `python -m pytest`，结果写入 PR 描述

## 三、代码与仓库规范

| 项目 | 规范 |
| --- | --- |
| 语言与版本 | Python 3.11+；全部函数写类型注解 |
| 风格检查 | ruff（版本固定在 pyproject.toml，统一用 `python -m ruff` 运行），行宽 100；CI 不通过不合并 |
| 数据对象 | 跨模块传递的数据用 pydantic 模型，从 `schema/` 的 JSON Schema 生成或与其对照测试，两者不得各自演化 |
| 引擎代码 | `engine/` 的校验函数必须是纯函数：不联网、不调用 LLM、不读数据库，输入相同则输出相同 |
| LLM 调用 | 只出现在 `ingest/`（规格书抽取）和 `engine/` 的需求解析、方案解释模块；输出必须经 schema 校验才能进入下一步 |
| 单位 | 代码内部只用第四节规定的标准单位；单位换算只在 `ingest/` 入口处用 pint 完成 |
| 测试 | pytest；测试不联网、不调用真实 LLM（用录制的响应）；FreeCAD 相关测试标记 `@pytest.mark.freecad`，在 CI 的 `freecad` 作业中用锁定版本的 FreeCAD 运行（ADR-0032） |
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

- 数值三选一：`value`（单值）、`min`/`max`（范围）、`nominal` + `tol_upper`/`tol_lower`（公差）；偏差带符号，要求 `tol_lower ≤ tol_upper`，两侧可同号（如 g6 的 −0.006/−0.017，ADR-0022）
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
| `mechanical.cyl_female` | 孔 / 内圆柱配合面（减速器输入孔、轴承内圈、轴承座孔） | `diameter_mm`、`fit`（ISO 286 公差带如 `H7`；轴承内圈为精度等级如 `P0`）、`feature`、`clamping`（`key` / `clamp_ring` / `set_screw` / `press_fit`；轴承内圈可不填，ADR-0024） | `fit_system`（`iso286` 缺省 / `bearing`）、`depth_mm`、`key_width_mm`、`accepted_diameter_range_mm`（可换轴套时） | `cyl_male` |
| `mechanical.flange` | 圆形安装法兰（电机法兰、减速器输入/输出法兰） | `pcd_mm`、`hole_count`、`hole_kind`（`through` / `threaded`）、`hole_diameter_mm` 或 `thread`（如 `M5`） | `pilot_diameter_mm`、`pilot_kind`（`male` / `female`）、`pilot_fit`、`square_size_mm`、`hole_angle_offset_deg` | `flange` |
| `mechanical.mount_face` | 非圆形安装面（驱动器底板、壳体安装面） | `pattern`（`rect`：`pitch_x_mm × pitch_y_mm` 矩形角点，4 孔或对角 2 孔；`linear`：沿 y 单列，相邻孔距 `pitch_y_mm`；ADR-0031）、`pitch_y_mm`、`hole_count`、`hole_diameter_mm` 或 `thread` | `face_size_mm`、`din_rail` | `mount_face` |
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

必填参数就是第七节校验要用到的参数，也就是录入和复核时的“关键字段”；必填项缺失的组件可以入库，但相关校验结果为“未知”。**接口数据只放在端口里，不在参数表重复**（ADR-0014）：尺寸、电流、电压、协议等描述连接的数据写在对应端口的 `spec` 中；参数表只允许列出的必填与选填参数；必填参数在品类 schema 中以 `x-key-fields` 标注，不强制，缺失时进入复核。减速比须大于 0，效率须在 (0, 1] 内，额定扭矩与效率必须注明工况。

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

V1 共 11 项静态校验，全部由 `engine/` 的确定性代码完成；每项输出五种状态之一。

| 状态 | 含义 | 对整体结果的影响 |
| --- | --- | --- |
| `pass` | 满足 | — |
| `warn` | 满足但有风险或需额外措施 | 整体可用，方案说明中必须列出 |
| `fail` | 不满足 | 整体不可用 |
| `unknown` | 数据缺失，无法判定 | 整体最多为“待确认”，不得呈现为通过 |
| `not_applicable` | 该项前提在需求或系统中不存在，不做（ADR-0016），须写明原因 | 不影响整体结论 |

整体结论按优先级取：有 `fail` 即不可用；否则有 `unknown` 即待确认；否则有 `warn` 即有条件可用；适用项全部 `pass` 才是可用（`not_applicable` 不计入）。

### 校验清单

| 编号 | 校验 | 判定条件 | 不满足时 |
| --- | --- | --- | --- |
| C1 | 端口兼容 | 类型在“可连接到”列表内；方向为 out→in 或含 bidir；`motion` 相同 | fail |
| C2 | 圆柱配合 | 内外圆柱名义直径相等；公差配对在配合表内（一侧为轴承时，按轴承配合推荐表判定）；`feature` 与 `clamping` 兼容（轴承一侧未写 `clamping` 时此项不适用，ADR-0024），有键时键宽相等 | 直径或键不符 fail；公差配对不在表内 warn |
| C3 | 法兰配合 | 分度圆直径相差 ≤ 0.05 mm；孔数相等；一侧螺纹孔时，另一侧通孔直径 ≥ 按 ISO 273 中等系列的间隙孔；止口一公一母且直径相等 | 分度圆、孔数、孔径、止口不符 fail；一侧没有止口 warn |
| C4 | 连续扭矩 | 公式 (1)(2) | fail |
| C5 | 峰值扭矩 | 公式 (3)(4) | fail |
| C6 | 减速器过载保护 | 电机峰值扭矩经减速后超过减速器瞬间最大扭矩，公式 (5) | warn（需在驱动器设置扭矩限幅） |
| C7 | 转速 | 所需输出转速 × 减速比 ≤ 电机最高转速，且 ≤ 减速器最高输入转速；超过减速器平均输入转速限制时告警 | fail / warn |
| C8 | 惯量比 | 仅当需求给出负载惯量时计算，公式 (6)，阈值默认 10 | warn |
| C9 | 电气匹配 | 系统有驱动器和电机而缺动力连接时 fail（ADR-0020）；数据取自驱动器 `power_in`、`motor_out` 与电机 `power_in` 端口（ADR-0014）；供电电压在驱动器范围内且相数一致；驱动器与电机电压等级一致；驱动器额定电流 ≥ 电机额定电流；驱动器峰值电流 ≥ 电机峰值电流 | 前三项 fail；峰值电流不足 warn（峰值扭矩受限） |
| C10 | 信号匹配 | 缺编码器连接时 fail（ADR-0020）；数据取自编码器与总线端口（ADR-0014）；电机编码器协议在驱动器支持列表内，私有协议要求同一厂商；驱动器总线协议与需求一致 | fail |
| C11 | 轴承与包络 | 轴承转速取输出转速，须 ≤ 极限转速；系统外径取各段外接圆直径的最大值（圆柱取直径，长方体取截面对角线），须 ≤ 需求限值；长度须布局后计算：系统带 `layout` 时取除驱动器外各实例包络在减速器输出轴方向上的投影范围，须 ≤ 需求限值，缺位姿或缺尺寸为 unknown；没有 `layout` 时为 not_applicable（ADR-0020、ADR-0034） | fail |

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
- 厂商公开发布的产品目录参数与接口尺寸按 ADR-0040 收录（`license: params-only`）：逐份登记官方下载网址，每份只下载一次，不批量爬取；不转存文档、图片、图纸与 CAD；厂商提出异议时删除其数据，来源改为 `withdrawn`
- 每份规格书登记为一个来源文档：id（如 `src-yaskawa-sgm7j-catalog`）、标题、版本或发布日期、下载网址、文件 SHA-256；原始 PDF 放 `data/raw/`，不入 git

### 2. 录入方式

| 阶段 | 方式 | 文件位置 |
| --- | --- | --- |
| 种子数据（每类约 5 个型号，issue #7） | 公开目录参数（ADR-0040）或开源硬件设计，人工录入，`method: manual` | `data/sources.yaml` 中 `license: partner` 或 `terms_checked: true` 的来源；`data/seed/<品类>/<组件 id>.json`，每个组件一个文件 |
| M2 批量数据（每类 30–50 个型号） | LLM 抽取，`method: extracted`，进复核队列 | 复核通过后写入数据库，并导出为 JSON 快照纳入版本管理 |
| 紧固件 | 按 ISO/DIN 标准表程序生成，`method: standard` | 生成脚本入库，数据由脚本产出 |

### 3. 复核规则

- 关键字段（第六节的必填参数和端口 `spec` 必填字段）一律人工对照原文复核；ADR-0040 起可由 AI 独立读取原文逐项比对完成，复核人记为 `claude（AI 复核）`，不一致项不入库，留待人工核对
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

用例引用的组件放在 `tests/golden/fixtures/`，M1–M3 一律为虚构测试组件（ADR-0015），id 以 `test.` 开头，永远不进入正式库。缺关键数据、整体结论为 `unknown` 的用例放在 `unknown/` 目录。`checks` 的值除四种状态外还可为 `any`，表示该项依赖 M3 尚未定义的规则、本用例不断言。

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
| 第 2 周（10/12–10/18） | 组件（含 `adapter`）、系统、需求 schema；5 个品类的参数 schema；初查首批来源条款；向候选厂商发出授权请求（ADR-0015） | `schema/component.schema.json` 等、`schema/categories/`、`data/sources.yaml` |
| 第 3 周（10/19–10/25） | 编写虚构测试组件库与 golden 用例（≥ 3 正确、≥ 11 错配、若干未知）；用虚构组件表达一套完整关节并手算校验结果；schema 评审与定稿 `0.1.0`；M1 验收 | `tests/golden/`、`docs/milestones/M1.md`、标签 `v0.1.0` |

M1 阶段还没有引擎代码，golden 用例的预期结果由人手算确定，到 M3 由引擎自动验证。

真实厂商数据须先取得书面授权（ADR-0015）：M1–M3 的开发与 golden 用例一律使用虚构测试组件，真实种子数据（issue #7）移至 M2，取得首批授权后录入。

### M2 分项任务（2026-10-01 开工，计划完成 11-22）

M1 提前约 3 周完成，M2 随即开工，完成日期不变，多出的时间作为等待厂商授权的缓冲。按依赖顺序：

| 顺序 | issue | 内容 | 验收 |
| --- | --- | --- | --- |
| 1 | 组件知识库 | PostgreSQL + pgvector；组件、参数、端口表；参数修改历史；按来源许可把关的导入；JSON 快照导出 | 导入前做 schema 校验；未核实来源的数据和 `test.` 组件被拒；修改留历史；导入—导出往返一致 |
| 2 | 单位归一化 | pint；常见来源单位换算到标准单位 | kg·cm²、kgf·cm、10⁻⁴ kg·m²、峰值电流→有效值等各有测试 |
| 3 | 模拟规格书生成器 | 由虚构组件生成 PDF 规格书，混用单位与叫法；同时输出正确答案 | 每类至少 5 份，答案与组件数据一致 |
| 4 | PDF 文本与表格提取 | 从 PDF 提取文本和表格，保留页码 | 模拟规格书的表格全部提取，页码正确 |
| 5 | LLM 结构化抽取 | 按品类 schema 输出参数与端口，带置信度和来源页码 | 输出通过 schema 校验；测试用录制的响应 |
| 6 | 人工复核队列 | 命令行工具；关键字段与低置信度字段进队列；记录错误分类 | 复核结果写回知识库并留历史 |
| 7 | 抽取准确率评测 | 对照正确答案逐字段评分 | 模拟规格书上关键字段准确率 ≥ 95% |
| 8 | M2 验收 | 取得授权后在真实规格书上复测；并入真实种子数据（issue #7） | 见开发计划 |

真实 LLM 调用需要项目负责人的 Anthropic API 密钥，只放在本地 `.env`；CI 与测试一律使用录制的响应。

模拟规格书：虚构组件目录在 `ingest/synthetic_catalog.py`（4 个品类各 5 个，部分型号故意缺项，用来检验“缺数据不写”），由 `python -m ingest.synthetic --out data/synthetic --variants N` 生成 PDF 与答案（`*.answer.json`），输出目录不入 git。同一组件与变体号生成的结果完全相同。答案中 `fields` 是规格书上印出的每一行（页码、文字、单位、换算到标准单位后的期望值），`implicit` 是由品类或其他字段推出、规格书上不直接印出的字段（组件中记为 `method: computed`，来源写推导依据），评测时不计分。语言、单位、叫法与版式只由组件 id 和变体号决定，与目录顺序无关。生成 PDF 需要 DejaVu Sans 与文泉驿正黑字体（`fonts-dejavu-core`、`fonts-wqy-zenhei`），字体会嵌入 PDF。

PDF 提取：`ingest/pdf_extract.py` 用 pdfplumber 逐页提取正文与表格，页码从 1 开始；单元格内的排版折行按两侧字符合并（中文与中文直接相连，其余用空格）。表格只认有边框的表；无边框表格的内容仍在该页正文中，交给 LLM 抽取时一并提供（`Document.to_prompt_text()`）。只做忠实提取，不解释单位、不合并跨页表格。

LLM 抽取：`ingest/llm_extract.py`，流程与分工见 ADR-0021。多型号目录用 `--pages` 与 `--target`：只把相关页交给 LLM、只报目标型号；表头列出各型号时，代码核对数值在目标型号那一列，正文中重复的表格行不能用来绕过这项核对；合成的多型号目录由 `ingest/synthetic_multi.py` 生成，`python -m ingest.evaluate --catalogs` 评测（ADR-0040）。LLM 只报印出的内容（数值、单位、页码、原文引用），代码逐项核对后输出抽取结果（`schema/extraction.schema.json`），一律未复核、不直接入库。测试只用录制回放或标明 `simulated` 的模拟响应（`ingest/llm_simulate.py`）；录制方法见 `tests/recordings/llm/README.md`。真实调用需要 `pip install -e ".[llm]"` 和本地 `.env` 中的密钥。

人工复核：`kb/review.py`（ADR-0023）。抽取结果入队后，关键字段、置信度低于 0.9、带注意事项的项，以及全部被拒提议与缺失的关键字段进入复核；复核决定只增不改，可改判，须选错误分类。全部决定后由 `ingest/assemble.py` 组装组件（端口坐标系按品类约定，需确认；包络由整体尺寸生成），复核员核对计划后带指纹确认，经 `kb.store.import_component` 写入并记修改历史；已在库中的组件须 `--update`。命令：`python -m kb.review enqueue / list / show / decide / add / commit / stats`。

准确率评测：`ingest/evaluate.py`。对每个可抽取目标判为对、错、漏、多，数值按相对误差 ≤ 0.1% 判对（规格书印 4 位有效数字），工况单独计；`string_or_list` 字段的单值等于单元素列表，没有枚举的字符串忽略大小写、空白和标点；答案中列为 `implicit` 的字段被报出且与推导值相同时不计分，不同则记为多报（ADR-0038）；关键字段准确率 = 关键字段判对数 / 答案中的关键字段数，门槛 95%。驱动器品类没有关键字段（接口数据都在端口里），只看召回与精确。报告分总体、逐品类、逐字段、逐份规格书。模拟响应只用于检验评测代码，报告会标注且永不判为通过；验收须用真实录制：`python -m ingest.evaluate --variants 2 --record`（本地，需要密钥），之后可用 `--replay` 复现。

### M3 分项任务（2026-10-01 提前开工，计划完成 12-13）

M2 剩余的真实数据验收要等 API 录制与厂商授权，按开发计划“M3 可提前用虚构数据开工、与 M2 后半段并行”，M3 先行。引擎一律用虚构测试组件开发（ADR-0015）。按依赖顺序：

| 顺序 | issue | 内容 | 验收 |
| --- | --- | --- | --- |
| 1 | 校验框架与接口校验 | `engine/`：系统装载（组件来自 golden fixtures 或知识库）、校验结果对象、整体结论；C1–C3 | 纯函数；输出符合第七节格式；相关 golden 用例结果正确 |
| 2 | 性能链校验 | C4–C8，公式 (1)–(6)，给出测量值、限值、余量 | 公式逐项单测，含刚好等于限值、稍微超出的边界 |
| 3 | 电气、信号与包络校验 | C9–C11 | 相关 golden 用例结果正确；C11 长度为 `not_applicable` |
| 4 | golden 运行器 | 引擎跑全部 golden 用例并逐项断言，纳入 CI；`any` 项输出实际结果供人决定 | 现有 golden 用例全部通过 |
| 5 | 链路模板与候选求解 | “电机 → 减速器 → 输出”模板（含驱动器，可选轴承）；按需求从组件库筛选组合、全部过校验、排序后给出前 N 个 | 对虚构组件库结果确定；返回的方案无 `fail`；排序规则写入 ADR |
| 6 | 方案解释 | 由校验结果生成中英文说明：结论、每个 `fail`/`warn`/`unknown` 的原因、涉及端口、余量；确定性模板，LLM 只在 M4a 做措辞润色 | 每个非 `pass` 项都有原因与端口 |
| 7 | golden 扩充 | 起草候选用例：正确 ≥ 10 套，错配 ≥ 30 个（含边界值），每个 `warn` 情形至少 1 个 | **由人逐个确认后合并**（AI 只起草，不自行合并） |
| 8 | M3 验收 | 规则表人工核对完成（#3、#14）；golden 全部通过；演示一句需求得到校验过的候选方案 | 见开发计划 |

驱动器 2 孔安装面的表示（#39）属于 schema 问题，在 M4b 布局之前解决，不阻塞 M3。已由 ADR-0031 解决。

### M4a 分项任务（2026-10-01 提前开工，计划完成 2027-01-17）

M3 开发部分完成后，验收只剩人工事项（规则表核对 #3、#14），按“先外部 MCP 客户端、后 FreeCAD 面板”（ADR-0003）先做 M4a。只实现不依赖 FreeCAD 的工具；`place_component`、`connect_ports`、`check_interference`、`snapshot` 属于 M4b。按依赖顺序：

| 顺序 | issue | 内容 | 验收 |
| --- | --- | --- | --- |
| 1 | 组件库接口与查询工具 | 组件库抽象：JSON 目录（golden fixtures、知识库快照）或知识库；`search_components`（品类、厂商、参数范围、关键词筛选）、`get_component` | 结构化筛选结果确定；未知参数名、非法范围报错而不是静默忽略 |
| 2 | `find_compatible` | 给定组件与端口，返回能连上的组件及端口，附 C1 与 C2 / C3 的单连接校验结果 | 只返回能连上的；不能直连但可经转接件时注明 |
| 3 | `compose_chain` 与 `verify_system` 工具 | 包装引擎的候选求解与 11 项校验，输入按 schema 校验，输出结构化结果加中英文说明 | 通过 MCP 工具重跑全部 golden 用例，结果与直接调用引擎一致（实施细则第九节） |
| 4 | `export_system` | 导出 BOM（CSV / JSON，含原厂模型链接与数据来源）与系统 JSON（含校验报告）；URDF 需要布局结果，移到 M4b | 导出内容可追溯到组件与来源文档 |
| 5 | REST 接口 | 与 MCP 工具一一对应的 HTTP 接口，供非 MCP 客户端（如机器人学院）使用 | REST 与 MCP 结果一致 |
| 6 | 外部客户端接入 | Claude Desktop 等客户端的配置说明；端到端演示脚本：一句需求 → 结构化需求 → 候选方案 → 校验与说明 | 在外部客户端里用一句需求得到校验过的候选方案（开发计划 M4a 验收） |
| 7 | M4a 验收 | | 见开发计划 |

### M4b 分项任务（2026-10-01 提前开工，计划完成 2027-02-14）

M4a 开发部分完成后，验收只剩外部客户端试用（#70、#71），M4b 先行。架构、配合约定与测试方式见 ADR-0032；驱动器安装面孔位（#39）已由 ADR-0031 解决。按依赖顺序：

| 顺序 | issue | 内容 | 验收 |
| --- | --- | --- | --- |
| 1 | FreeCAD 测试基建 | CI 新增 `freecad` 作业：下载锁定版本的 AppImage（核对 SHA-256、缓存），用其内带 Python 安装本项目，在 Xvfb 下运行 `pytest -m freecad`；注册 `freecad` 标记，作业中导入失败即报错 | 一个最小的 FreeCAD 测试在 CI 中通过；主作业照常跳过 |
| 2 | 位姿与配合（`freecad_addon/core/`） | 刚体变换；按 ADR-0032 的面配合、圆柱配合规则求位姿；刚性组；场景的增删、序列化；世界坐标下的包络描述与输出轴方向的包络长度 | 纯函数，单测覆盖每种端口对、`roll_deg`、`offset_mm`、闭环核对与偏差；对全部 golden 正确用例按连接关系布局后，相配端口对齐 |
| 3 | 包络实体与干涉（`freecad_addon/fc/`） | 由包络描述生成 `Part` 实体，减去 `cyl_female` 孔；包围盒预筛后求重叠体积；`headless` worker 与 JSON 行协议 | 正确用例布局后无干涉；人为错位、轴伸过长穿出孔底等情形能报出干涉对与体积 |
| 4 | FreeCAD 组 MCP 工具 | `place_component`、`connect_ports`、`check_interference`、`snapshot`；会话内场景；REST 对应接口 | 工具结果与直接调用 `core`/`fc` 一致；未连接 FreeCAD 时几何查询类工具给出明确错误 |
| 5 | 系统布局字段（schema） | `system.schema.json` 增加可选 `layout`（各实例位姿）；单独 schema PR，附 ADR | schema 样例合法与非法各至少 1 个 |
| 6 | C11 长度与导出 | 有 `layout` 时 C11 计算包络长度（ADR-0020 的 `not_applicable` 改为实际判定）；`export_system` 的系统 JSON 带布局；新增 URDF 导出 | C11 长度刚好等于、稍微超出限值的单测；URDF 可被解析，连杆与关节可追溯到实例 |
| 7 | agent 布局流程 | 提示模板与演示脚本：选定方案 → 按连接布局 → 干涉检查 → 调整 → 截图自查 | 演示脚本对虚构组件库确定地完成布局且无干涉 |
| 8 | 工作台与对话面板 | FreeCAD 工作台、零件面板、内置对话面板（MCP 客户端，经 `gui` 后端驱动当前 FreeCAD 会话）；密钥只从环境变量读取 | 面板逻辑用录制的 LLM 响应测试；界面部分标记 `freecad` |
| 9 | M4b 验收 | | 见开发计划：agent 能独立完成布局并消除干涉 |

### M5 分项任务（2026-10-01 提前开工，计划完成 2027-02-28）

M4b 开发部分完成后，验收只剩人工演示（#90），M5 先行。需求解析与可复现性见 ADR-0037。按依赖顺序：

| 顺序 | issue | 内容 | 验收 |
| --- | --- | --- | --- |
| 1 | 需求解析 | `engine/requirement_parse.py`：LLM 报字段、数值、单位与原文引用，代码核对引用、数字、单位（pint）与枚举依据；缺必填项时给出追问；录制回放 | 核对规则逐条单测；回放结果确定；不编造未说的指标 |
| 2 | 端到端演示 | `python -m mcp_server.e2e`：一句话（解析）或结构化需求 → 候选方案 → 布局与消除干涉 → 按布局复核 → BOM、系统 JSON、URDF、截图与汇总 | 同一输入两次运行，除截图外输出逐字节相同；FreeCAD 作业中含截图跑通 |
| 3 | 样例输出 | `examples/joint2/`：由示例需求生成的全部输出（截图随附作示意，不逐字节比对），测试重新生成并逐字节比对 | 样例与当前代码一致 |
| 4 | 文档整理 | 根目录 README 更新（状态、各入口的快速开始）；`docs/demo.md` 演示步骤；架构与开发计划转存为仓库文档 | 新用户按 README 能跑通离线演示 |
| 5 | 独立评审与修复 | 由未参与实现的 agent 对全链路做评审，确认的问题逐个修复 | 评审结论与修复记录写入 PR |
| 6 | 演示录制 | 录屏脚本（Xvfb + ffmpeg）；真实 LLM 的演示视频由人录制 | 脚本可生成录屏 |
| 7 | M5 验收 | | 见开发计划：从一句需求到 BOM 的演示可重复跑通 |

### M6 分项任务（2026-10-01 开工）：公开数据跑通

项目负责人决定先用公开数据跑通真实数据流程，厂商授权不急（ADR-0040）：只取厂商公开发布的产品目录参数与接口尺寸，逐项注明出处，不转存文档、图片与 CAD，不批量爬取。按依赖顺序：

| 顺序 | issue | 内容 | 验收 |
| --- | --- | --- | --- |
| 1 | 数据路线与来源登记 | ADR-0040；`data/sources.yaml` 中厂商来源改为 `params-only` 并写明核实结论 | 文档与登记一致 |
| 2 | 规格书下载与真实抽取流水线 | `ingest/fetch.py` 按登记网址下载到 `data/raw/` 并核对 SHA-256；`data/extract_jobs.yaml` 列出抽取任务；GitHub Actions 手动工作流在云端下载、抽取、录制，开 PR 提交录制与抽取结果 | PDF 不入 git、不留构建产物；SHA-256 不符即停；本地与 Codespaces 可用同一命令 |
| 3 | 多型号目录抽取 | 真实目录一份含多个型号、几百页：抽取任务指定页码范围与目标型号 | 合成的多型号目录上关键字段准确率 ≥ 95%；回放确定 |
| 4 | 开源硬件数据 | moteus（Apache-2.0）、ODrive v3.6（MIT）等许可明确的开源设计，按仓库提交登记，人工录入参数 | 入库；每个参数可追溯到仓库文件与提交 |
| 5 | AI 复核 | 另一个模型独立再抽一次（`ingest.jobs run --check`），`ingest/crosscheck.py` 逐项比对；一致的项标为已复核（复核人 `claude（AI 复核）`），组装成组件写到 `data/library/`；不一致项不入库，列在 `data/review/` | 比对规则单测；同一模型不算独立复核；清单可导出 |
| 6 | 首批厂商数据 | Harmonic Drive 整机型减速器、安川 Σ-7 伺服电机与 EtherCAT 驱动器，各取公开目录中适合关节的型号 | 每类至少 5 个型号入库，来源可追溯 |
| 7 | 转接件参数化生成 | 真实电机与减速器之间需要轴套和转接板：`engine/adapters.py` 按两侧端口尺寸生成（ADR-0041；用 `computed` 与 `license: open` 表达，不改 schema）；`compose_chain(generate_adapters=True)` 在库中没有合适转接件时使用 | 生成的转接件通过 schema 与 C2、C3；同一输入结果确定 |
| 8 | 真实数据端到端样例 | `examples/joint-real/`：用真实组件从一句需求到 BOM、布局与 URDF | 样例可重复生成 |
| 9 | M6 验收 | | 至少一套由真实组件组成的关节方案通过全部校验，所有数据可追溯来源；厂商目录按设计不规定的端口（ADR-0045 的 configurable）所对应的 unknown 不计为未通过（ADR-0046 第 7 条） |

规格书的下载与真实抽取在 GitHub Actions 或 Codespaces 中运行（本工作环境访问不到厂商网站）；在 Actions 中运行时，密钥 `ANTHROPIC_API_KEY` 取自仓库的 demo 环境。

### M7 分项任务（2026-10-02 开工）：操作录制与学习

项目负责人提出“自动录屏供 AI 学习”，决定录操作过程、视频可选（ADR-0042）。按依赖顺序：

| 顺序 | issue | 内容 | 验收 |
| --- | --- | --- | --- |
| 1 | 方案 | ADR-0042；计划与细则 | 文档一致 |
| 2 | 录制器与 FreeCAD 接入 | `freecad_addon/core/session_log.py`：会话包 `session/1`（meta、events.jsonl、snapshots/、outcome）、去密钥、改动来源、截图限频；`freecad_addon/fc/` 文档观察者与命令记录；工作台“开始 / 停止录制”、状态栏标记、停止时评价；对话面板事件写入录制 | 记录逻辑单测；FreeCAD 作业中文档改动被记下且来源正确 |
| 3 | 可选视频 | ffmpeg 只录 FreeCAD 主窗口区域，默认关闭 | 有 ffmpeg 时生成视频，没有时说明原因、其余照常 |
| 4 | 重放与数据集导出 | `python -m freecad_addon.sessions list / show / export / replay` | 导出 JSONL；重放在新文档中重建对象 |
| 5 | 相似会话检索 | `freecad_addon/core/retrieval.py`：按需求词项（英文单词、数字带单位、中文二字组）的 Jaccard 相似度加相同组件检索正常结束的会话；参考文字（需求、评价、用户修改、结论）附在本轮系统提示之后；`FAP_SESSION_HINTS=0` 关闭 | 检索结果确定；不含密钥；可关闭 |
| 6 | M7 验收 | | 录一次手工建模加一次 AI 布局，导出数据集，重放成功 |

### M8 分项任务（2026-10-05 开工）：AI 原生 FreeCAD

项目负责人决定重点转到 FreeCAD 的 AI 原生重构，先做库浏览器与接口实体（ADR-0048）。按依赖顺序：

| 顺序 | issue | 内容 | 验收 |
| --- | --- | --- | --- |
| 1 | 方案 | ADR-0048；计划与细则 | 文档一致 |
| 2 | 共用工具宿主与自动找库 | 对话面板、浏览器、接口命令共用一个服务端与场景；未设 `FAP_LIBRARY` / `DATABASE_URL` 时用插件所在仓库的 `data/library/` | 不设环境变量时面板显示真实库；单测 |
| 3 | 库浏览器 | `freecad_addon/core/browser.py` 筛选与详情（纯函数）；停靠窗口列表、详情、“放入布局” | 筛选与详情单测；FreeCAD 作业中放入布局后场景有该实例 |
| 4 | 接口实体 | `FapLayout` 中每个实例一组：零件带组件 id、实例名、品类属性；各端口一个标记，按大类着色 | FreeCAD 作业中标记位置与端口坐标系一致 |
| 5 | 对接与装配即校验 | 选两个接口标记“连接接口”；场景改动后组成系统并校验（无需求时只跑 C1、C2、C3、C10）；“校验”停靠窗口；按最差结论着色 | 由场景组成系统、端口结论汇总单测；FreeCAD 作业中手工对接后显示结论 |
| 6 | M8 第一步验收 | | 在 FreeCAD 中不设环境变量，从浏览器取真实电机与减速器，手工对接，看到校验结论；再让 AI 完成同一关节 |

第二步（ADR-0049）：

| 顺序 | issue | 内容 | 验收 |
| --- | --- | --- | --- |
| 7 | 就地更新与方案存档 | 布局文档就地更新；`FapProject` 记录（`fap-project/1`）随 .FCStd 保存；“恢复方案”命令按记录重建；`freecad_addon/core/project.py` 纯函数 | 记录读写与重建序列单测；FreeCAD 作业中另存、关闭、打开、恢复后场景一致 |
| 8 | 拖动回写 | 文档观察者监视零件 `Placement`，用户改动停止 0.4 秒后调用 `place_component`；同步造成的改动不回写 | 位姿换算单测；FreeCAD 作业中改零件位置后场景随之改变、刚性组一起动 |
| 9 | AI 改动先成提案 | 对话面板开关（默认开）；每轮前快照，轮后列出差异与 AI 说明；接受保留、拒绝恢复；录制记下决定 | 场景差异单测；FreeCAD 作业中拒绝后场景恢复原状 |
| 10 | M8 第二步验收 | | 保存方案再打开恢复；拖动零件看到校验变化；拒绝一次 AI 提案、接受一次 |

第三步（ADR-0051）：

| 顺序 | issue | 内容 | 验收 |
| --- | --- | --- | --- |
| 11 | 选型面板 | `core/requirement_form.py` 表单与需求互转（校验窗口共用）；`core/selection.py` 候选行与放入布局的调用序列；停靠窗口“AI Parts 选型” | 表单互转、候选行、调用序列单测；FreeCAD 作业中填需求、查找、放入布局后场景与系统一致，校验为全部 11 项 |
| 12 | BOM 面板 | `core/bom_view.py` 由场景组成 BOM（`bom_rows`）；停靠窗口“AI Parts BOM”，随场景刷新，导出 CSV / JSON | BOM 行与总质量单测（质量缺失时总质量未知）；FreeCAD 作业中放入方案后 BOM 行与 `export_system` 一致 |
| 13 | M8 第三步验收 | | 不用对话：在选型面板填需求、放入方案、看到校验结论与 BOM，导出 CSV |

第四步（ADR-0052）：

| 顺序 | issue | 内容 | 验收 |
| --- | --- | --- | --- |
| 14 | 换件建议 | `core/swap.py` 候选、排序、结论变化、换上的调用序列（纯函数）；MCP 工具 `suggest_replacements`；校验窗口“换件建议”区 | 候选排序与结论变化单测；换上后连接重建、校验与预测一致；FreeCAD 作业中光轴电机配键槽孔减速器，换件建议给出带键电机并换上后 C2 通过 |
| 15 | M8 第四步验收 | | 手工放入光轴电机与减速器并对接，看到 C2 不通过；用“换件建议”换上带键电机，C2 变为通过 |

第五步（ADR-0053）：

| 顺序 | issue | 内容 | 验收 |
| --- | --- | --- | --- |
| 16 | 定制要求 | `engine/custom.py`（纯函数）；bom_json 的 `custom_requirements`；BOM 面板与校验窗口显示 | 真实关节的定制要求照录 SGM7J-02A 法兰的分度圆、孔数、孔形式、孔径及页码，缺失项列为待确认；C3 结论不变；BOM CSV 列不变 |

第六步（ADR-0054）：

| 顺序 | issue | 内容 | 验收 |
| --- | --- | --- | --- |
| 17 | 一句话需求 | 选型面板解析区；`requirement_form.merge_parsed`（纯函数）；解析经 `engine.requirement_parse` | 并入表单与额外指标单测；FreeCAD 作业中用录制回放解析示例原话，表单与示例需求一致，不自动查找；缺必填项时显示追问 |

### M9 分项任务（2026-10-06 开工）：企业自建、自补零件库

| 顺序 | issue | 内容 | 验收 |
| --- | --- | --- | --- |
| 1 | 企业私有库 | ADR-0055；`kb/enterprise.py` 企业库读写（schema 校验、依据必填、历史记录）；`kb/library.py` 的 `LayeredLibrary`；`library_choice` 加入企业库；FreeCAD“企业库”命令选择文件夹 | 叠加取数与覆盖、写入校验与历史单测（临时目录）；FreeCAD 作业中选择企业库后浏览器显示两层的组件数，企业组件可选型、放入、出 BOM |
| 2 | 就地补数据 | 待确认项旁“补数据”：填值、资料、页码、原文，写入企业库 | 补数据后该项校验结论随之变化；依据缺失时拒绝写入 |
| 3 | 导入规格书 | 拖入 PDF / Excel，AI 抽取、代码核对（沿用 ingest 的引用核对），逐项确认后入企业库 | 录制回放下抽取、核对、确认、入库全流程；未确认的值不入库 |
| 4 | 新建零件向导 | 按品类模板从规格书建新零件 | 新零件通过 schema，可选型、放入、出 BOM |
| 5 | M9 验收 | | 在 FreeCAD 中选择企业库，补一项待确认数据、导入一份规格书、新建一个零件，用它们完成一次选型与 BOM |

### M10 分项任务（2026-10-06 开工）：CAD 与数字工厂集成，本地运行版（ADR-0056）

| 顺序 | issue | 内容 | 验收 |
| --- | --- | --- | --- |
| 1 | 模块框架 | `analysis/` 包与模块约定（`MODULE`、`available()`、`run(setup)`、结果 schema）；求解器查找（FreeCAD 自带 ccx / gmsh、`FAP_CCX` / `FAP_GMSH`）；子进程与时限；材料库（每条注明出处）；FreeCAD“分析”菜单列出模块与可用状态；MCP 工具 `list_analyses`；CI 安装求解器 | 缺依赖时模块报“不可用”及安装方法、其余照常；CI 中求解器可用；材料库每条有出处 |
| 2 | 运动学 · 多体动力学 | 搬入 MuJoCo 动力学（机构与机械臂、点到点运动、关节力矩 / 转速 / 功率）；结果 → 峰值、均方根、最高转速 → 选型需求 → 现有候选求解；FreeCAD 窗口：设置、计算、曲线、送去选型 | 标准题：单摆周期、曲柄滑块驱动力矩与虚功原理（< 1%）、四杆位置与解析解、机械臂静止重力矩与 Σm·g·r（< 2%）；一次搬运计算生成的需求能选出真实组件 |
| 3 | 有限元 + 疲劳 | 搬入 gmsh 网格、CalculiX 静力与模态、疲劳（雨流、Goodman、S-N、Miner）；几何取 FreeCAD 场景零件的 STEP；约束、载荷按面选；结果云图着色在三维视图；载荷谱可来自动力学结果 | 标准题：悬臂梁挠度（< 3%）、光滑轴扭转应力与手算（< 3%）、简支梁一阶固有频率；疲劳恒幅与手算（< 0.1%）、雨流计数标准例子 |
| 4 | 热分析 + 设计优化 | 搬入稳态 / 瞬态温度场、热—结构耦合；设计优化（optuna，约束：安全系数、寿命） | 标准题：平壁导热（< 1%）、肋片（< 3%）、集总参数冷却（< 3%）、两端固定杆热应力（< 2%）；悬臂梁定强度最轻截面与解析解（< 3%） |
| 5 | 数字孪生 | 搬入孪生核心（轴承 ISO 281 L10、输出轴疲劳 Miner、热平衡油温、换油、残差报警、“假如”）；按 BOM 中零件的样本参数建孪生（缺参数显示待确认）；运行记录从 CSV 读入 | 恒载 L10 与手算（< 1%）；变工况与当量载荷一致；降载 20% 轴承寿命 1/0.8³ 倍；三种故障情景能报警 |
| 6a | 搬入数字工厂（ADR-0058） | wenquest `factory/` 原样搬到 `factory/`，注明来源；根目录 ruff、pytest 不覆盖；CI 作业 `factory` 跑其单元测试与网页打包 | `factory` 作业通过；不含 `.env` 与密钥 |
| 6b | 本地运行版 | 一条命令启动（Linux / Windows Docker Desktop）、缺省模拟 ERPNext、生产模式、“本地版”标识、说明文档 | 本机 `docker compose` 启动后工作台可打开、看板有数据 |
| 6c | 发布到工厂 | FreeCAD“发布到工厂”：BOM 与零件 STEP 经数据总线发到本地工厂，成为物料与设计版本 | 发布后工厂工作台能看到该方案的物料与设计版本 |
| 6d | 工厂用本仓库零件库、孪生数据互通 | 工厂选型改用公共库 + 企业库；工厂的设备运行摘要导出为孪生运行记录 | 工厂选型列出零件库的组件；导出的记录能被数字孪生读入 |
| 7 | M10 验收 | | 在 Windows 的 FreeCAD 中：一次机械臂搬运动力学 → 选出真实电机减速器 → 放入布局 → 对一个零件做有限元与疲劳 → 建孪生看寿命 |

### M11 分项任务（2026-10-06 开工）：第二批分析模块（ADR-0059）

| 顺序 | issue | 内容 | 验收 |
| --- | --- | --- | --- |
| 1 | 拓扑优化 | 搬入平面 SIMP（预设与自定）；密度图、柔度历程；按 0.5 取轮廓拉伸成板件放进 FreeCAD 文档；FreeCAD 窗口 | 标准题：MBB 60×20、体积比 0.5 柔度与 203 差 < 2%，体积比守住；板件 STEP 可送有限元 |
| 2 | 数控编程 | 搬入车削与 2.5 轴铣削刀路、FANUC 后处理、G 代码读取与仿真检查、Kienzle 切削功率（表带出处）；机床参数企业填写（示例机床标虚构）；FreeCAD 窗口：生成或打开 G 代码 → 时间、检查、功率 | 标准题：车削基本时间与手算（< 0.1%）、切削功率与手算（< 0.1%）；生成的阶梯轴程序仿真无过切、残留 < 0.05 mm；读入 FreeCAD CAM 工作台风格程序能算时间 |
| 3 | 流体 | 搬入 OpenFOAM 建模、求解与后处理；`FAP_OPENFOAM_BIN` / PATH 查找，缺时报不可用；几何取场景零件 STEP；结果：阻力 / 压降、各面散热量与平均换热系数 | 标准题：Poiseuille（< 3%）、平板层流换热（< 5%）、湍流平板通道摩擦与换热（< 10%）、圆柱 Re 40 阻力系数（< 5%）；CI 装 OpenFOAM 跑标准题 |
| 4 | M11 验收 | | 在 Windows 的 FreeCAD 中：对一个支架做拓扑优化 → 拉伸件做有限元；为一根阶梯轴生成 G 代码并检查；流体如本机未装 OpenFOAM，报不可用及安装方法 |

### M12 分项任务（2026-10-07 开工）：工厂计算与 analysis/ 合并为一份（ADR-0060）

| 顺序 | issue | 内容 | 验收 |
| --- | --- | --- | --- |
| 1 | 镜像与测试接通 + 流体内核 | 构建上下文改为仓库根目录（白名单 `.dockerignore`）；镜像与 CI `factory` 作业能导入 `analysis`；`cae/foam`、`cfd_heat`、`cfd` 改为转接层，表面云图、截面、流线补进 `analysis.cfd` | 工厂流体测试不改断言通过；`analysis` 流体标准题通过；`factory-local` 起得来 |
| 2 | 有限元与热分析内核 | `cae/geometry`、`solve`、`modal`、`thermal` 改为转接层 | 工厂有限元、模态、热测试不改断言通过；`analysis` 标准题通过 |
| 3 | 多体动力学内核 | `cae/mbd` 改为转接层 | 工厂动力学测试不改断言通过 |
| 4 | 数控编程内核 | `cae/cam_sim`、`cam_post`、`cam_power` 改为转接层（机床编号 → 参数字典） | 工厂数控测试不改断言通过 |
| 5 | 上层的计算核心 | 拓扑优化 SIMP、疲劳雨流与 S-N、优化评估改调 `analysis` | 工厂对应测试不改断言通过 |
| 6 | M12 验收 | | 本地工厂（Windows Docker Desktop）各计算页面照常；同一题 FreeCAD 与工厂结果一致 |

### M13 分项任务（2026-10-07 开工）：典型应用全流程演练与工厂接收新产品（ADR-0061）

| 顺序 | issue | 内容 | 验收 |
| --- | --- | --- | --- |
| 1 | 工厂接收新产品 | 发布内容加自制件；`/api/cad/designs/{code}/production` 预览与提议；桥接执行建供应商、物料、BOM；产品登记表并入主数据；MRP 对登记产品开全部工单；模拟 ERPNext 新物料库存 | 单元测试：登记后 MRP 给出全部工单与采购；本地工厂里一个新产品从发布到工单 |
| 2 | 三个典型应用（FreeCAD 一侧） | `examples/apps/` 协作机器人关节、SCARA、直驱平缝机：需求（注明出处）→ 动力学 → 选型 → 布局校验 → BOM → 有限元、疲劳、热、拓扑、数控、流体、孪生 → 发布 | 三个脚本都跑通；选出的组件都来自零件库；各分析有结果或说明为何不适用 |
| 3 | 工厂一侧全流程 | 转为生产物料 → 工艺规程审批 → MRP → 确认提议 → MES 下达与执行 → 厂情中枢（注入故障、异常追因、推演、动作审批、简报、日报） | 本机原生起整座工厂跑通；CI `factory-local` 跑一遍 |
| 4 | 报告与 M13 验收 | 演练报告：每个应用每一步的结果、发现的问题与处理 | 项目负责人看报告；需要时在 Windows 上照报告走一个应用 |

### M14 分项任务（2026-10-07 开工）：典型应用演练暴露问题的收尾（ADR-0062）

| 顺序 | issue | 内容 | 验收 |
| --- | --- | --- | --- |
| 1 | 方案改版进 ERP | 桥接按“产品 + 方案版本”识别 BOM：同版本不重建，新版本设默认、旧的取消默认；模拟 ERPNext 支持改 BOM 默认 | 工厂测试：同一方案执行两次只有一张 BOM；第 2 版后默认 BOM 是第 2 版 |
| 2 | 自制件带粗基准与装夹 | 发布内容自制件加可选 `datum`、`clamping`；工厂起草工艺规程使用；三个应用的方案带上；演练脚本不再代写 | 单元测试：带与不带两种都能发布；工厂一侧演练 AI 评审没有“粗基准”错误 |
| 3 | 平缝机动力学改正 | 恒速惯性力矩 → 最大盈亏功与转速不均匀系数；选型给上限（刚性速度环）与下限（惯量吸收，连续扭矩待确认），峰值含起停加速；与教材公式对照 | 快速模式测试；δ 与手算一致；报告改正原说法 |
| 4 | 协作机器人补腕关节 | j4 动力学与选型 | 快速模式测试 |
| 5 | 报告与 M14 验收 | 更新 M13 演练报告；本机从空库重跑全流程 | 项目负责人看报告 |

### M15 分项任务（2026-10-07 开工）：企业安装版、云服务器远程部署与 AI 模型切换（ADR-0063）

| 顺序 | issue | 内容 | 验收 |
| --- | --- | --- | --- |
| 1 | AI 模型网关 | 工厂 `llm.py`：`WQ_AI_PROVIDER`/`WQ_AI_REGION`、回退、记录实际所用；系统设置页切换；新包 `llm_gateway/` 供 FreeCAD 对话与需求解析用 | 单元测试：auto 按地区选、手动覆盖、出错回退、都不可用走规则（录制回答，不联网） |
| 2 | 企业账号 | `WQ_AUTH=enterprise`：密码哈希、管理员管账号与角色、登录限速；安装时建管理员 | 工厂测试：登录、权限、停用、限速 |
| 3 | 预构建镜像 | main 合并后构建工厂、桥接镜像推 GHCR | 工作流跑通，镜像可拉取 |
| 4 | 企业安装包与远程部署 | `factory/enterprise/`：compose（含 ERPNext、Caddy）、install/upgrade/backup/restore/status、`deploy.sh` 经 SSH | CI：干净机器一条命令装好，HTTPS 可登录 |
| 5 | 现场网关 | `factory/gateway/`：Mosquitto TLS 桥接、断网缓存 | CI：网关发的消息到达云端总线 |
| 6 | 企业上线清单 | `docs/enterprise-onboarding.md` | 项目负责人看过 |
| 7 | CI 验收与 M15 验收 | 企业安装后跑平缝机工厂一侧；AI 两家录制回答 | CI 通过；有云服务器时远程部署一次 |

### M16 分项任务（2026-10-08 开工）：企业车间布局与公司资料导入（ADR-0064）

| 顺序 | issue | 内容 | 验收 |
| --- | --- | --- | --- |
| 1 | 工厂清单与加载 | `factory/plant.py`；演示工厂导出 `factory/plants/wenquest-gearbox.yaml`；data / topics / engine / layout / calendar / kpi 从清单取值 | 导出前后常量逐项相等；所有现有测试不改断言通过 |
| 2 | 校验、Excel 模板与导入 | `python -m factory.plant template / import / check`；出错指明行与项 | 单元测试：模板往返得到同一份清单；各类错误都能报出 |
| 3 | 企业安装用清单 | `install.sh --plant`；ERPNext 按清单建公司；seed 按清单建工作站、工序 | CI：用示例企业工厂装好 |
| 4 | 随工厂变的文字 | AI 提示词、本体工厂对象、网页标题、`mrp.COMPANY`；教学页面在企业工厂里不显示 | 工厂测试 |
| 5 | 示例企业工厂与验收 | `factory/plants/example-sewing.yaml`；CI 企业作业跑平缝机工厂一侧 | CI 通过；项目负责人看示例工厂 |
