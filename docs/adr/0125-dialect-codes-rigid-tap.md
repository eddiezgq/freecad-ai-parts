# ADR-0125：写法差别加“手册代码表”与刚性攻丝前导行

- 状态：已接受（2026-11-24，属于 ADR-0106 E3）
- 日期：2026-11-24
- 补充：ADR-0124

## 背景

按哈斯官网在线《Mill Operator's Manual》（第 18 章 M-Codes，2026-11-24 查）核对：哈斯铣床的 **M29 是“Set Output Relay with M-Fin”（接通输出继电器）**，
不是 FANUC 的刚性攻丝方式；问渠CAM 的 FANUC 写法在 G84 前写 `M29 S转速`，原样给哈斯就会去接一个继电器——这正是“写法看着一样、意思不一样”的危险。
倾斜面 G68.2、五轴 G43.4 哈斯也没有（哈斯是 G268、G234，写法不同）。单靠标准题查不住所有零件，要在出程序时就查。

## 决策

1. `dialect.codes`：这家手册代码表里的 G、M 代码号（按手册原样填）。正式程序里出现表外的 G 或 M 代码，**不出程序**，写明“手册里没有 Gxx / Mxx”。
2. `dialect.rigid_tap`：G84 前面的程序行模板（{s} 转速）；FANUC 写法是 `["M29 S{s}"]`，哈斯铣床填 `[]`（不写这一行）。回读时按模板换回 FANUC 写法。
3. 两项都要在 `dialect.sources` 里写出处。

## 影响

- 已有配置不用改；没写 `codes` 的不查。实现与哈斯铣床配置见后面的 PR（ADR-0106 E3）。

## 实现记录（2026-11-24）

- `postcfg.check_codes`：正式程序写好后查每个 G、M 代码是否在 `dialect.codes` 里（注释里的不算），表外的列出来、`ReleaseError` 不出。
- `rigid_tap`：G84 前 FANUC 的 `M29 S转速` 换成模板行，`[]` 就不写；回读时在 G84 前按前面最近的 S 补回 `M29 S`，再与仿真比。
- 哈斯铣床配置 `analysis/cam/posts/haas-mill.json`：按 Haas 官网在线《Mill Operator's Manual》（第 12 章 Programming、第 17 章 G-Codes、第 18 章 M-Codes、G84 页，
  2026-11-24 浏览器读原文）：O 加 5 位、换刀 T1 M06（同 FANUC）、攻丝不写 M29（哈斯 M29 是接继电器；G84 自己开停主轴）、代码表照手册。
  倾斜面 G68.2、五轴 G43.4 不在哈斯的表里——出不了，等按手册做 G268 / G234。
- 标准题 `tests/test_cam_post_dialect_codes.py`（CAM-87、88）：哈斯铣床开槽、钻孔、攻丝能出、没有 M29、回读一致；rs274 一致（不含攻丝）；代码表去掉 G84 → 带攻丝的程序不出、点名 G84。
