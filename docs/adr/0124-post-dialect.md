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
