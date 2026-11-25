# ADR-0124：后处理配置加“写法差别”（dialect）与核对记录（checks），家族加大隈、发格

- 状态：已接受（2026-11-24，属于 ADR-0106 E3）
- 日期：2026-11-24
- 补充：ADR-0109（可配置后处理）、ADR-0110（车铣 M 代码）

## 背景

项目负责人定：适配所有主流数控系统，按工业级做（ADR-0106 E、E3）。三菱、马扎克、哈斯、兄弟、新代、凯恩帝、NUM 的 ISO 写法与 FANUC 大体相同，
差在少数几处：换刀指令的位数、限速指令（G50 / G92）、车铣插补的开关指令（G12.1 / G112）、动力刀开转（哈斯 M133 P 转速）、程序头尾、复合循环的写法。
这些现在写死在代码里，只能出 FANUC 的样子。大隈 OSP、发格 8065 的基本语法另成一家。核对到了哪一级（独立解释器、厂商系统软件）也没处记。

## 决策

1. `cam-post/1` 加可选的 `dialect`：`tool_call_lathe`、`tool_call_mill`、`spindle_limit`、`polar`（开、关）、`cylindrical`（开、关，带 {r} 或 {d}）、
   `turn_cycles`（two_block / one_block / none）、`head`、`foot`；模板占位符 {n} {nn} {o} {oo} {s} {r} {d} {rpm} {number}。
   **`sources` 必填**：每一项写厂商正式文件的名称、文件号、版本、章节——没出处的写法不收（ADR-0106 E 工业级标准第 1 条）。
2. `millturn.live_on` 的程序行可带 `{rpm}`（例如哈斯 `M133 P{rpm}`）。
3. `family` 加 `okuma`、`fagor`（基本语法与回读规则另写）。
4. 加可选的 `checks`：L2（独立解释器）、L3（厂商系统软件）的核对记录——工具与版本、日期、谁、证据；L4 实机仍写在 `verified`。
5. 没写 `dialect` 的配置，输出与现在一字不差。回读：后处理按 `dialect` 写，回读按同一份模板换回 FANUC 写法再与仿真比，不可逆的写法不收。

## 理由

写法差别属于数控系统，按家族 + 配置表达，与 ADR-0109、ADR-0110 同一做法；出处必填，配置本身就是可审核的对照表。

## 影响

- 已有配置不用改。实现与各家内置配置见 ADR-0106 E3（单独的 PR）。
- 本 PR 合并到实现合并之间，写了 `dialect` 或新家族的用户配置还不起作用（现在没有用户配置）。

## 实现记录（2026-11-24，ADR-0106 E3 第一步：机制）

- `postcfg.apply_dialect`（写好的 FANUC 写法逐行换成这家的写法：车床换刀 `T0101`、铣床换刀 `T1 M06`、限速 `G50 S`、`G12.1` / `G13.1`、
  `G07.1 C半径` / `G07.1 C0`；顺序号、回读行号标记照样认）与 `postcfg.undo_dialect`（回读前换回，逐项是逆运算）；`postproc.to_fanuc` 回读时调用。
- `post.live_on_lines`：`millturn.live_on` 里写了 `{rpm}` 就把转速填进去、不再另写 `S`。
- `postcfg.check`：dialect 只用于 ISO 家族；每一项都要有出处；不认识的占位符、`turn_cycles: one_block`（还没按官方手册做）拒收；
  `okuma`、`fagor` 家族在官方编程手册到之前拒收、写明原因。`turn_cycles: none` 不用车削复合循环。
- 程序头：`checks` 里每条核对记录写一行 `(CHECKED L2 … 日期)`；“未经实机验证”照旧，只有 `verified` 才去掉。
- 标准题 `tests/test_cam_post_dialect.py`（CAM-81 ~ 83）：车（固定循环开、关）、铣、车铣（极坐标、圆柱插补开关，动力刀 `{rpm}`）按测试用写法写出、回读一致、
  车削时间与 FANUC 相同；六位刀具指令加顺序号；`turn_cycles: none`；没出处、单段、不认识的占位符、非 ISO 家族、大隈家族都拒收；核对记录进程序头；
  没写 dialect 的内置配置一字不差。
- 各家的真实配置等官方手册（ADR-0106 E3 的表）。

## 第一份厂商配置：哈斯车床（2026-11-24）

- `analysis/cam/posts/haas-lathe.json`：按 Haas 官网在线《Lathe Operator's Manual》（第 11 章 Programming、第 16 章 G-Codes、第 17 章 M-Codes，2026-11-24 查，
  用浏览器直接读的官方页面原文）：程序号 O 加 5 位、换刀 `T101`（刀号不补零、刀补两位）、限速 G50 S 与 FANUC 相同；
  G71 手册只写了单段写法（D 切深），FANUC 两段写法没写，按工业级标准不用复合循环（`turn_cycles: none`）；
  车铣：G112 是直角坐标 XY 编程、G107 另一套参数，与 FANUC 的 G12.1 / G7.1 不只是开关指令不同，`dialect` 表达不了——没配 `millturn`，带铣削段的程序不出。
- 核对：L1 回读；L2 独立解释器 rs274（`checks` 记录，程序头写 `CHECKED L2`）；标准题核对程序里每个 G、M 代码都在手册的代码表里（CAM-86）。
- 还没做：哈斯铣床（按 Mill Operator's Manual）、车铣（要先给 dialect 加“极坐标插补用直角坐标”的写法，另写 ADR）。
- 2026-11-24 三菱 M800V / M80V：三菱电机 FA 官网手册页公开下载《Programming Manual》车床篇（IB-1501619）、加工中心篇（IB-1501621），按手册做 `mitsubishi-m800-lathe`、`mitsubishi-m800-mill` 两份配置（FANUC 家族 + dialect）：车床 G 代码表 2（前提 #1037 cmdtyp = 3、#1097 刀补 2 位），复合循环不用（G71 凹槽加工随参数 #8110），G12.1 是铣削插补、车铣不出；加工中心 G84 不收（同步攻丝 F 的单位随 #1292、#1268）；冷却 coolant off。标准题 `tests/test_cam_post_mitsubishi.py`（CAM-92、93），含 rs274 一致。
