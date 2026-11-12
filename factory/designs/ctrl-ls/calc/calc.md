# 计算书：CTRL-LS（A 版）

平缝机控制器（单相 110–250 V，功率因数校正 + 智能功率模块）

> 示例设计，未经硬件验证，不能直接投产。器件为示例选型。
> 由问渠电子功能块计算器生成（第 104 轮）。判定：通过 / 不通过 / 未知（缺数据）/ 待核对（用到的器件数据还没人对照规格书核对，不算通过）。

## 规格

| 项 | 值 |
|---|---|
| 母线电压 | 390 V |
| 输入电压 | 90–250 V 交流（波动 ±10 %） |
| 电机 | 550 W · 5000 r/min · 峰值 3 N·m / 均方根 0.58 N·m |
| 力矩出处 | 第 138 轮 G2（峰值 ≥ 3 N·m）与 gc_sim（速度环 40 Hz 时力矩均方根 0.58 N·m） |
| 假设（无器件数据可依） | η_电机 0.9，η_逆变 0.97，η_校正 0.95，功率因数 0.99，电控箱内 50 ℃ |
| 降额与余量规则（示例值） | capacitor 1.25，diode 1.25，mosfet 1.25，sense_headroom 1.05，fuse 1.25 |
| 目标工厂 / 验收等级 | 未定 / 未定 |

## 结论

通过 9 项，不通过 0 项，待核对 49 项，未知 5 项。

## 交流输入、电磁兼容与浪涌（AC input, EMI and inrush）

原理图页：mains

| 量 | 结果 | 公式 | 说明 |
|---|---|---|---|
| 母线功率 | 670 W | P_母线 = P_电机 / η_电机 / η_逆变 + P_辅助 | η_电机 0.9、η_逆变 0.97 是假设值 |
| 交流输入功率 | 705.3 W | P_输入 = P_母线 / η_校正 | η_校正 0.95 是假设值 |
| 输入电流有效值（最低电压） | 7.916 A | I = P_输入 / (V_最低 · PF) | V_最低 90 V，PF 0.99（假设） |
| 输入峰值（最高电压加波动） | 388.9 V | √2 · V_最高 · (1 + 波动) |  |
| 上电浪涌电流峰值（热敏电阻冷态） | 155.6 A | I = V_峰 / R_25 | 待核对；NTC thermistors for inrush current limiting, Series/Type S364/**/M**, B57364S0***M0** Date: 2021-04-22, Version a，p.4 Table 1 |

| 判定 | 要求 | 实有 | 规则 | 结论 | 说明 |
|---|---|---|---|---|---|
| 保险丝额定电压 | 250 V | 250 V | 额定电压 ≥ 最高输入电压 | **待核对** | 待核对；Axial Lead & Cartridge Fuses 5×20 mm > Time-Lag > 215 Series Revised: 01/12/17，p.2 table |
| 保险丝额定电流 | 9.894 A | 10 A | I_额定 ≥ 1.25 × I_输入 | **待核对** | 待核对；Axial Lead & Cartridge Fuses 5×20 mm > Time-Lag > 215 Series Revised: 01/12/17，p.2 table |
| 压敏电阻最高工作电压 | 275 V | 275 V | V_RMS ≥ 最高输入电压 ×（1 + 波动） | **待核对** | 待核对；SIOV metal oxide varistors, Leaded varistors, StandarD series, Series/Type: B722* Date: March 2018，ratings table, V_RMS = 275 V group |
| X 电容额定电压 | 275 V | 310 V | 额定 ≥ 最高输入电压 ×（1 + 波动） | **待核对** | 待核对；MKP339 X2 Interference Suppression Film Capacitors Document Number: 28138, Revision: 24-Jul-2019，p.1 Quick Reference Data |
| 热敏电阻最大电流 | 7.916 A | 11 A | I_max ≥ I_输入（继电器旁路前） | **待核对** | 待核对；NTC thermistors for inrush current limiting, Series/Type S364/**/M**, B57364S0***M0** Date: 2021-04-22, Version a，p.4 Table 1 |
| 热敏电阻允许的负载电容（230 V） | 990 µF | 1 mF | C_T ≥ 母线电容 | **待核对** | 待核对；NTC thermistors for inrush current limiting, Series/Type S364/**/M**, B57364S0***M0** Date: 2021-04-22, Version a，p.4 Table 1 |
| 旁路继电器触点电流 | 9.894 A | 16 A | 触点额定 ≥ 1.25 × I_输入 | **待核对** | 待核对；Power Relay G5LE-G / G5LE-E (no revision printed)，p.1 |
| 共模电感额定电流 | 7.916 A | — | 额定 ≥ I_输入 | **未知** | FC-HLF2018-15mH-10A-LF 的规格书是图片，读不出数；施工时换一份能读的规格书或换型号 |

## 整流桥（Bridge rectifier）

原理图页：mains

| 量 | 结果 | 公式 | 说明 |
|---|---|---|---|
| 整流后平均电流 | 7.126 A | I_平均 = 2√2/π · I_输入 |  |
| 整流桥损耗 | 15.68 W | P = 2 · V_F · I_平均（任一时刻两只导通） | V_F 取 10 A 时的最大值，偏保守；GBU1001 - GBU1007 Single Phase 10.0 AMP. Glass Passivated Bridge Rectifiers Version: A06，p.1 Maximum Ratings |

| 判定 | 要求 | 实有 | 规则 | 结论 | 说明 |
|---|---|---|---|---|---|
| 反向耐压 | 486.1 V | 800 V | V_RRM ≥ 1.25 × 输入峰值 | **待核对** | 待核对；GBU1001 - GBU1007 Single Phase 10.0 AMP. Glass Passivated Bridge Rectifiers Version: A06，p.1 Maximum Ratings |
| 平均整流电流（壳温 100 ℃ 额定） | 7.126 A | 10 A | I_F(AV) ≥ I_平均 | **待核对** | 待核对；GBU1001 - GBU1007 Single Phase 10.0 AMP. Glass Passivated Bridge Rectifiers Version: A06，p.1 Maximum Ratings |
| 浪涌电流 | 155.6 A | 220 A | I_FSM ≥ 上电浪涌（热敏电阻冷态） | **待核对** | GBU1001 - GBU1007 Single Phase 10.0 AMP. Glass Passivated Bridge Rectifiers Version: A06，p.1 Maximum Ratings；NTC thermistors for inrush current limiting, Series/Type S364/**/M**, B57364S0***M0** Date: 2021-04-22, Version a，p.4 Table 1 |

## 功率因数校正（连续导通升压）（PFC boost (CCM)）

原理图页：pfc

| 量 | 结果 | 公式 | 说明 |
|---|---|---|---|
| 输入电流有效值（最低电压） | 7.836 A | I = P_输入 / V_最低（校正后按纯正弦） |  |
| 输入电流峰值 | 11.08 A | √2 · I |  |
| 电感电流纹波（峰峰） | 3.325 A | ΔI = 纹波系数 × I_峰 | 纹波系数 0.3 |
| 升压电感（最少） | 451.2 µH | L = V_x(1 − V_x/V_o) / (f · ΔI)，V_x 取纹波最大处 V_o/2 | V_x = 195 V，f = 65 kHz（规格书 R_FREQ = 67 kΩ 时的典型值） |
| 电感峰值电流 | 12.74 A | I_峰 + ΔI/2 |  |
| 电流采样电阻上限 | 11.77 mΩ | R ≤ \|V_PCL,min\| / (余量 × I_L峰) | 余量 1.2；选 10m；ICE3PCS01G Standalone Power Factor Correction (PFC) Controller in Continuous Conduction Mode (CCM), Datasheet Version 3.0, 03 April 2017，p.18 4.3.6 |
| 开关管电流有效值 | 6.663 A | I_Q = I · √(1 − 8√2·V_in/(3π·V_o)) |  |
| 开关管高温导通电阻 | 140.8 mΩ | R_150℃,典型 × R_25℃,最大 / R_25℃,典型 | IPW60R060P7 600V CoolMOS P7 Power Transistor, Final Data Sheet Rev. 2.1, 2018-05-15，p.5 Table 4 |
| 开关管导通损耗 | 6.252 W | I_Q² · R_高温 |  |
| 开关管开关损耗 | 2.273 W | (½·V_o·I_平均·(t_r + t_f) + E_oss + Q_c·V_o) · f | t_r、t_f 是规格书 5.6 A 时的典型值，按工频平均电流估；IPW60R060P7 600V CoolMOS P7 Power Transistor, Final Data Sheet Rev. 2.1, 2018-05-15，p.5 Table 5；IPW60R060P7 600V CoolMOS P7 Power Transistor, Final Data Sheet Rev. 2.1, 2018-05-15，p.1 Table 1；C3D06060A Silicon Carbide Schottky Diode Z-Rec Rectifier Rev. F, 10-2015，p.2 Electrical Characteristics |
| 升压二极管导通损耗 | 4.123 W | V_F(175 ℃ 最大) · I_o | C3D06060A Silicon Carbide Schottky Diode Z-Rec Rectifier Rev. F, 10-2015，p.2 Electrical Characteristics |
| 采样电阻损耗 | 444 mW | I_Q² · R |  |
| 母线电容纹波电流（校正级产生） | 3.75 A | √(I_D,rms² − I_o²)，I_D,rms² = 8√2·I²·V_in/(3π·V_o) |  |
| 母线二倍工频纹波（峰峰） | 5.524 V | ΔV = P_o / (2π · f_工频 · C · V_o)（峰峰） | f_工频取 50 Hz |
| 掉电保持时间（降到 300 V） | 45.88 ms | t = C·(V_o² − V_min²) / (2·P_o) |  |
| 母线分压上臂 | 3.1 MΩ | R_上 = R_下 · (V_o / V_VSREF − 1) | R_下 = 20k；ICE3PCS01G Standalone Power Factor Correction (PFC) Controller in Continuous Conduction Mode (CCM), Datasheet Version 3.0, 03 April 2017，p.20 4.3.11 |
| 过压保护动作的母线电压 | 421.2 V | 1.08 × V_o（OVP1 = 108 % 额定，规格书 4.3.6） |  |

| 判定 | 要求 | 实有 | 规则 | 结论 | 说明 |
|---|---|---|---|---|---|
| 开关频率在控制器范围内 | 65 kHz | 21000–100000 Hz | 范围包含 65000 Hz | **待核对** | 待核对；ICE3PCS01G Standalone Power Factor Correction (PFC) Controller in Continuous Conduction Mode (CCM), Datasheet Version 3.0, 03 April 2017，p.16 4.2 |
| 采样电阻不大于上限 | 10 mΩ | 11.77 mΩ | R ≤ 上限 | **待核对** | ICE3PCS01G Standalone Power Factor Correction (PFC) Controller in Continuous Conduction Mode (CCM), Datasheet Version 3.0, 03 April 2017，p.18 4.3.6 |
| 开关管耐压 | 526.5 V | 600 V | V_DS ≥ 1.25 × 过压点 | **待核对** | 待核对；IPW60R060P7 600V CoolMOS P7 Power Transistor, Final Data Sheet Rev. 2.1, 2018-05-15，p.1 Table 1; p.5 Table 4 |
| 开关管电流（壳温 100 ℃） | 12.74 A | 30 A | I_D(100℃) ≥ 电感峰值电流 | **待核对** | 待核对；IPW60R060P7 600V CoolMOS P7 Power Transistor, Final Data Sheet Rev. 2.1, 2018-05-15，p.3 Table 2 |
| 升压二极管耐压 | 526.5 V | 600 V | V_RRM ≥ 1.25 × 过压点 | **待核对** | 待核对；C3D06060A Silicon Carbide Schottky Diode Z-Rec Rectifier Rev. F, 10-2015，p.1 Maximum Ratings |
| 升压二极管电流（壳温 135 ℃） | 1.718 A | 9 A | I_F ≥ I_o | **待核对** | 待核对；C3D06060A Silicon Carbide Schottky Diode Z-Rec Rectifier Rev. F, 10-2015，p.1 Maximum Ratings |
| 母线电容耐压 | 487.5 V | 500 V | V_额定 ≥ 1.25 × V_o | **待核对** | 待核对；Rubycon MXH series SNAP-IN aluminum electrolytic capacitors catalog page 115-116 (no revision printed)，p.2 table 500 Vdc |
| 母线电容耐压（过压点） | 421.2 V | 500 V | V_额定 ≥ 过压保护点 | **待核对** | 待核对；Rubycon MXH series SNAP-IN aluminum electrolytic capacitors catalog page 115-116 (no revision printed)，p.2 table 500 Vdc |
| 母线电容纹波电流 | 3.75 A | 5.43 A | 3 只 × 额定（120 Hz，偏保守）≥ I_C | **待核对** | Rubycon MXH series SNAP-IN aluminum electrolytic capacitors catalog page 115-116 (no revision printed)，p.2 table 500 Vdc, 330 µF |
| 母线纹波不超过要求 | 5.524 V | 20 V | ΔV ≤ 20 V | **待核对** | Rubycon MXH series SNAP-IN aluminum electrolytic capacitors catalog page 115-116 (no revision printed)，p.1 Specifications; p.2 table |
| 掉电保持时间 | 20 ms | 45.88 ms | t ≥ 0.02 s | **待核对** | Rubycon MXH series SNAP-IN aluminum electrolytic capacitors catalog page 115-116 (no revision printed)，p.1 Specifications; p.2 table |
| 控制器供电绝对最大值 | 15 V | 26 V | V_CC,max ≥ 辅助 15 V | **待核对** | 待核对；ICE3PCS01G Standalone Power Factor Correction (PFC) Controller in Continuous Conduction Mode (CCM), Datasheet Version 3.0, 03 April 2017，p.15 4.1 |
| 仿真：电感电流纹波（峰峰，V_x = V_o/2 处） | 3.325 A | 3.328 A | 要求列是公式值、实有列是仿真值，相差 ≤ 3% | **通过** | 相差 0.09% |
| 仿真：母线二倍工频纹波（峰峰） | 5.524 V | 5.524 V | 要求列是公式值、实有列是仿真值，相差 ≤ 5% | **通过** | 相差 0.00% |
| 仿真：掉电保持时间 | 45.88 ms | 45.68 ms | 要求列是公式值、实有列是仿真值，相差 ≤ 3% | **通过** | 相差 0.42% |

仿真核对：数字工厂电路分析例题“CTRL-LS 校正级”，参数 L_uH=451.2，f_kHz=65，C_uF=990。

## 反激辅助电源（Flyback auxiliary supply）

原理图页：aux

| 量 | 结果 | 公式 | 说明 |
|---|---|---|---|
| 输出功率（各路平均负载之和） | 22.95 W | Σ V·I | 负载是设计给定的示例值：24 V（电磁铁、步进、照明，平均） 0.8 A、15 V（功率模块、校正控制器、继电器） 0.15 A、5 V（主控、编码器、面板口） 0.3 A |
| 输入功率 | 28.69 W | P_o / η | η 0.8 是假设值 |
| 最低输入直流 | 114.6 V | √2 · V_最低 · (1 − 波动)（校正级未工作时） |  |
| 最低输入时占空比 | 0.4661 | D = V_OR / (V_OR + V_min) | 反射电压 V_OR = 100 V |
| 初级峰值电流 | 1.075 A | I_p = 2·P_in / (V_min · D)（断续） |  |
| 初级电感（最多） | 752.8 µH | L_p = V_min · D / (I_p · f) | f = 66 kHz |
| 匝比 N_p : N_24V | 4.008 | n = V_OR / (V_o + V_F) |  |
| 开关管最高漏极电压 | 571.2 V | 过压点 + 钳位电压 | 钳位 150 V |
| 24 V 整流管反向电压 | 129.1 V | V_o + V_max / n |  |

| 判定 | 要求 | 实有 | 规则 | 结论 | 说明 |
|---|---|---|---|---|---|
| 芯片功率（85–265 V 开放式） | 22.95 W | 39 W | P_表 ≥ P_o（校正级未起时按宽电压栏） | **待核对** | 待核对；TOP264-271 TOPSwitch-JX Family, Integrated Off-Line Switcher with EcoSmart Technology Rev. E 08/12，p.2 Table 1 |
| 初级峰值电流低于限流 | 1.29 A | 2.371 A | 1.2 × I_p ≤ I_LIMIT,min | **待核对** | TOP264-271 TOPSwitch-JX Family, Integrated Off-Line Switcher with EcoSmart Technology Rev. E 08/12，p.27 |
| 占空比低于最大占空比 | 0.4661 | 0.75 | D ≤ DC_MAX,min | **待核对** | TOP264-271 TOPSwitch-JX Family, Integrated Off-Line Switcher with EcoSmart Technology Rev. E 08/12，p.24 |
| 开关管耐压 | 714 V | 725 V | BV_DSS ≥ 1.25 × (过压点 + 钳位) | **待核对** | 待核对；TOP264-271 TOPSwitch-JX Family, Integrated Off-Line Switcher with EcoSmart Technology Rev. E 08/12，p.28 |
| 钳位电压高于反射电压 | 140 V | 150 V | V_钳位 ≥ 1.4 × V_OR | **通过** |  |
| 24 V 整流管耐压 | 161.4 V | 200 V | V_RRM ≥ 1.25 × 反向电压 | **待核对** | 待核对；ES3A - ES3J Fast Rectifiers Rev. 2.11, June 2016，p.2 Absolute Maximum Ratings |
| 24 V 整流管电流 | 800 mA | 3 A | I_F(AV) ≥ 24 V 平均电流 | **待核对** | 待核对；ES3A - ES3J Fast Rectifiers Rev. 2.11, June 2016，p.2 Absolute Maximum Ratings |

## 智能功率模块逆变（IPM inverter）

原理图页：servo

| 量 | 结果 | 公式 | 说明 |
|---|---|---|---|
| 电机线反电势常数（要求的上限） | 0.573 V·s/rad | K_e = V_线峰,max / ω_max | 5000 r/min 时线反电势峰值 ≤ 300 V（设计要求） |
| 力矩常数 | 0.4962 N·m/A | K_t = 1.5 · K_e / √3（相电流峰值） |  |
| 峰值力矩时的相电流峰值 | 6.046 A | T_峰 / K_t | T_峰 3 N·m（第 138 轮 G2） |
| 连续工况相电流峰值 | 2.117 A | max(额定功率 / ω_max, 仿真力矩均方根) / K_t | 额定 550 W；力矩均方根 0.58 N·m（第 138 轮 gc_sim） |
| 每只 IGBT 损耗（连续） | 1.899 W | 导通 + 开关（见函数说明） | V_CE 取 7 A 时最大值当常数，偏保守；m = 0.9，cosφ = 0.9；STGIPS14K60T SLLIMM small low-loss intelligent molded module IPM, 3-phase inverter, 14 A, 600 V, Datasheet - production data DocID018534 Rev 5, April 2015，p.7 Table 7 |
| 每只二极管损耗（连续） | 257.4 mW | V_F · I_pk · (1/(2π) − m·cosφ/8) |  |
| 模块总损耗（连续） | 12.94 W | 6 × (IGBT + 二极管) |  |
| 每只 IGBT 损耗（峰值力矩时） | 5.423 W | 同上，I = 峰值 |  |
| 峰值力矩时 IGBT 结温（壳温取上限） | 116.3 ℃ | T_c,max + P_峰 · R_jc | 壳温上限 100 ℃（散热器块保证） |

| 判定 | 要求 | 实有 | 规则 | 结论 | 说明 |
|---|---|---|---|---|---|
| 母线不超过推荐工作电压 | 390 V | 400 V | V_母线 ≤ V_PN,推荐上限 | **待核对** | STGIPS14K60T SLLIMM small low-loss intelligent molded module IPM, 3-phase inverter, 14 A, 600 V, Datasheet - production data DocID018534 Rev 5, April 2015，p.14 Table 14 |
| 过压点不超过绝对最大值 | 421.2 V | 450 V | 1.08 × V_母线 ≤ V_PN,max | **待核对** | STGIPS14K60T SLLIMM small low-loss intelligent molded module IPM, 3-phase inverter, 14 A, 600 V, Datasheet - production data DocID018534 Rev 5, April 2015，p.5 Table 3 |
| IGBT 电流（壳温 25 ℃） | 7.557 A | 14 A | I_C ≥ 1.25 × 峰值相电流 | **待核对** | 待核对；STGIPS14K60T SLLIMM small low-loss intelligent molded module IPM, 3-phase inverter, 14 A, 600 V, Datasheet - production data DocID018534 Rev 5, April 2015，p.5 Table 3 |
| 开关频率不超过推荐上限 | 16 kHz | 20 kHz | f ≤ f_PWM,推荐 | **待核对** | STGIPS14K60T SLLIMM small low-loss intelligent molded module IPM, 3-phase inverter, 14 A, 600 V, Datasheet - production data DocID018534 Rev 5, April 2015，p.14 Table 14 |
| 15 V 供电在推荐范围内 | 15 V | 13.5–18 V | 范围包含 15 V | **待核对** | 待核对；STGIPS14K60T SLLIMM small low-loss intelligent molded module IPM, 3-phase inverter, 14 A, 600 V, Datasheet - production data DocID018534 Rev 5, April 2015，p.14 Table 14 |
| 峰值力矩时结温 | 116.3 ℃ | 125 ℃ | T_j ≤ T_j,max − 25 | **待核对** | STGIPS14K60T SLLIMM small low-loss intelligent molded module IPM, 3-phase inverter, 14 A, 600 V, Datasheet - production data DocID018534 Rev 5, April 2015，p.6 Table 6；STGIPS14K60T SLLIMM small low-loss intelligent molded module IPM, 3-phase inverter, 14 A, 600 V, Datasheet - production data DocID018534 Rev 5, April 2015，p.5 Table 5 |
| 死区不小于推荐 | 1 µs | 1 µs | t_死区 ≥ 推荐值 | **待核对** | STGIPS14K60T SLLIMM small low-loss intelligent molded module IPM, 3-phase inverter, 14 A, 600 V, Datasheet - production data DocID018534 Rev 5, April 2015，p.14 Table 14 |

## 下桥电流采样与片内运放（Low-side current sensing）

原理图页：servo

| 量 | 结果 | 公式 | 说明 |
|---|---|---|---|
| 量程（±） | 8.8 A | I_满 = min(V_零, V_ref − V_零) / (G · k · R) | G = 8，V_ref = 3.3 V，k = 0.9375；WSLT2512 Power Metal Strip Resistors, High Temperature (275 °C), Low Value, Surface-Mount Document Number: 30121, Revision: 04-Apr-2022，p.1 Global Part Number Information |
| 零电流时运放输出（零点） | 1.65 V | V_零 = G · V_ref · R_in/(R_in + R_b) | R_in = 1k，R_b = 15k |
| 采样电阻功耗（峰值力矩持续时） | 456.9 mW | (I_峰/√2)² · R |  |
| 过流比较器门限（采样电阻上的电压） | 187.5 mV | I_跳 · R | I_跳 = 7.5 A |

| 判定 | 要求 | 实有 | 规则 | 结论 | 说明 |
|---|---|---|---|---|---|
| 量程覆盖峰值电流（留余量） | 6.348 A | 8.8 A | I_满 ≥ 1.05 × 峰值 | **待核对** | WSLT2512 Power Metal Strip Resistors, High Temperature (275 °C), Low Value, Surface-Mount Document Number: 30121, Revision: 04-Apr-2022，p.1 Global Part Number Information |
| 过流门限高于峰值、在量程内 | 6.046 A | 7.5 A | 峰值 ≤ I_跳 ≤ I_满 | **待核对** |  |
| 采样电阻额定功率 | 456.9 mW | 1 W | P_额定(70 ℃) ≥ 峰值时功耗 | **待核对** | 待核对；WSLT2512 Power Metal Strip Resistors, High Temperature (275 °C), Low Value, Surface-Mount Document Number: 30121, Revision: 04-Apr-2022，p.1 Standard Electrical Specifications |
| MCU 片内运放能设成这个增益 | 8 | — | 片内 PGA 可选增益含 G | **未知** | STM32G431 的运放增益档位没录进 eda/parts（参考手册），待补 |
| 过流门限不超过模块电流 | 7.5 A | 14 A | I_C ≥ I_跳 | **待核对** | 待核对；STGIPS14K60T SLLIMM small low-loss intelligent molded module IPM, 3-phase inverter, 14 A, 600 V, Datasheet - production data DocID018534 Rev 5, April 2015，p.5 Table 3 |

## 电磁铁驱动（Solenoid drivers）

原理图页：act

| 量 | 结果 | 公式 | 说明 |
|---|---|---|---|
| 线圈电流 | 3 A | V / R | 线圈 8 Ω、20 mH 是示例值（机头上的电磁铁，按实物改） |
| 释放时间（二极管 + 稳压管钳位） | 1.453 ms | τ · ln(1 + I₀R / V_z)，τ = L/R | Surface Mount - 600 W > SMBJ series TVS Diodes Revised: JC.07/04/25 v4，p.2 table |
| 对照：只用续流二极管的释放时间 | 8.17 ms | τ · ln(1 + I₀R / V_F) |  |
| 关断时开关管漏极电压 | 56.85 V | V_24,max + V_BR,max + V_F |  |
| 开关管导通损耗（吸合时） | 36 mW | I₀² · R_DS(on),max |  |
| 每次释放的磁能 | 0.09 J | ½ L I₀² |  |

| 判定 | 要求 | 实有 | 规则 | 结论 | 说明 |
|---|---|---|---|---|---|
| 开关管耐压 | 71.06 V | 80 V | V_DS ≥ 1.25 × 关断尖峰 | **待核对** | 待核对；BSC040N08NS5 OptiMOS 5 Power-Transistor, 80 V, Final Data Sheet Rev. 2.2, 2020-05-15，p.1 Table 1 |
| 开关管电流 | 3.75 A | 121 A | I_D ≥ 1.25 × 线圈电流 | **待核对** | 待核对；BSC040N08NS5 OptiMOS 5 Power-Transistor, 80 V, Final Data Sheet Rev. 2.2, 2020-05-15，p.3 Table 2 |
| 续流二极管浪涌电流 | 3 A | 100 A | I_FSM ≥ 线圈电流（只在释放的几毫秒里导通） | **待核对** | 待核对；ES3A - ES3J Fast Rectifiers Rev. 2.11, June 2016，p.2 Absolute Maximum Ratings |
| 续流二极管耐压 | 33 V | 200 V | V_RRM ≥ 1.25 × V_24 | **待核对** | 待核对；ES3A - ES3J Fast Rectifiers Rev. 2.11, June 2016，p.2 Absolute Maximum Ratings |
| 稳压管峰值功率 | 116.7 W | 600 W | P_PPM(10/1000 µs) ≥ V_C · I₀ | **待核对** | 待核对；Surface Mount - 600 W > SMBJ series TVS Diodes Revised: JC.07/04/25 v4，p.1 Features |
| 释放时间满足要求 | 1.453 ms | 3 ms | t ≤ 3 ms | **待核对** |  |
| 仿真：释放时间（电流降到 1 %） | 1.433 ms | 1.465 ms | 要求列是公式值、实有列是仿真值，相差 ≤ 3% | **通过** | 相差 2.22% |
| 仿真：关断时漏极电压最高 | 54.45 V | 53.56 V | 要求列是公式值、实有列是仿真值，相差 ≤ 3% | **通过** | 相差 1.64% |

仿真核对：数字工厂电路分析例题“CTRL-LS 电磁铁关断”，参数 R_ohm=8，L_mH=20，Vz_V=30.45。仿真里二极管压降用理想模型近似，钳位电压按 V_BR,max + V_F 加在等效电压源上；读数“释放时间”取电流降到 1 %

## 针距步进驱动（Stitch-length stepper driver）

原理图页：act

| 量 | 结果 | 公式 | 说明 |
|---|---|---|---|
| 步进电机线圈电流（有效值） | 1 A |  | 示例值（针距步进电机按实物改） |

| 判定 | 要求 | 实有 | 规则 | 结论 | 说明 |
|---|---|---|---|---|---|
| 24 V（含波动）在驱动器工作范围 | 26.4 V | 5.5–29 V | 范围包含 26.4 V | **待核对** | 待核对；TMC2226 Datasheet, Power driver for stepper motors Rev. 1.06 / 2020-MAY-18，p.72 Operational Range |
| 驱动器连续电流 | 1 A | 1.6 A | I_RMS,连续 ≥ 线圈电流 | **待核对** | 待核对；TMC2226 Datasheet, Power driver for stepper motors Rev. 1.06 / 2020-MAY-18，p.72 Operational Range |

## MCU 最小系统与烧录口（MCU core and programming port）

原理图页：io

| 量 | 结果 | 公式 | 说明 |
|---|---|---|---|
| 已分配的 MCU 引脚 | 48 只 |  |  |

| 判定 | 要求 | 实有 | 规则 | 结论 | 说明 |
|---|---|---|---|---|---|
| 电流、母线、烧录信号都接到 MCU | 15 个 | 15 个 | 全部接上 | **通过** |  |
| MCU 供电 3.3 V 在工作范围内 | 3.3 V | 1.71–3.6 V | 范围包含 3.3 V | **待核对** | 待核对；STM32G431x6/x8/xB (DS12589) Rev 6, 2021-10，p.71 Table 17 |
| 晶振负载电容 | — | — | 要晶振的负载电容 C_L 数据才能算（C = 2·(C_L − C_杂散)） | **未知** | 晶振型号与数据未录，判未知 |

## 编码器、霍尔与脚踏输入（Encoder, Hall and pedal inputs）

原理图页：io

| 量 | 结果 | 公式 | 说明 |
|---|---|---|---|
| 编码器输入 RC 截止频率 | 723.4 kHz | f_c = 1 / (2π·R·C) |  |
| 编码器最高脉冲频率 | 208.3 kHz | 线数 × n_max / 60 | 电机未选型：线数是示例值 |
| 脚踏信号分压后最高电压 | 3 V | V_max × 20 k / 30 k |  |

| 判定 | 要求 | 实有 | 规则 | 结论 | 说明 |
|---|---|---|---|---|---|
| 截止频率 ≥ 余量 × 最高脉冲频率 | 416.7 kHz | 723.4 kHz | f_c ≥ 2 × f_max | **通过** | 线数是示例值（电机未选型） |
| 脚踏信号不超过 ADC 满量程 | 3 V | 3.3 V | V ≤ 3.3 V | **通过** | 脚踏输出 4.5 V 是示例值 |

## 面板口隔离（Isolated panel port）

原理图页：comm

| 量 | 结果 | 公式 | 说明 |
|---|---|---|---|
| 面板串口速率 | 1.152e+05 bit/s |  | 设计给定 |

| 判定 | 要求 | 实有 | 规则 | 结论 | 说明 |
|---|---|---|---|---|---|
| 数字隔离器隔离耐压 | 1.5 kV | — | 耐压 ≥ 要求 | **未知** | ADUM1201ARZ-RL7 规格书未录（隔离耐压要求 1500 V 是示例值，企业按安规表填） |
| 隔离电源隔离耐压 | 1.5 kV | — | 耐压 ≥ 要求 | **未知** | B0505S-1WR2 规格书未录 |

## 散热器（Heatsink）

原理图页：thermal

| 量 | 结果 | 公式 | 说明 |
|---|---|---|---|
| 装在散热器上的总损耗 | 41.26 W | Σ 各器件损耗 | 整流桥 GBU1006 15.68 W、升压开关管 IPW60R060P7 8.52 W、升压二极管 C3D06060A 4.12 W、智能功率模块 STGIPS14K60T 12.94 W |
| 散热器温度上限（整流桥 GBU1006，按结温） | 109.3 ℃ | T_j,max − 余量 − P_芯片·R_jc − P·R_cs | P_芯片 3.92 W |
| 散热器温度上限（升压开关管 IPW60R060P7，按结温） | 114.3 ℃ | T_j,max − 余量 − P_芯片·R_jc − P·R_cs | P_芯片 8.52 W |
| 散热器温度上限（升压二极管 C3D06060A，按结温） | 140.9 ℃ | T_j,max − 余量 − P_芯片·R_jc − P·R_cs | P_芯片 4.12 W |
| 散热器温度上限（智能功率模块 STGIPS14K60T，按结温） | 112.8 ℃ | T_j,max − 余量 − P_芯片·R_jc − P·R_cs | P_芯片 1.90 W |
| 散热器温度上限（智能功率模块 STGIPS14K60T，按壳温） | 93.53 ℃ | T_c,max − P·R_cs | T_c,max 100 ℃ |
| 散热器热阻要求（散热器到空气） | 1.055 K/W | (T_s,允许 − T_环境) / P_总 | 电控箱内环境 50 ℃（示例），导热垫 R_cs 0.5 K/W（示例） |

| 判定 | 要求 | 实有 | 规则 | 结论 | 说明 |
|---|---|---|---|---|---|
| 选的散热器热阻够小 | 0.9 K/W | 1.055 K/W | R_sa,要求 ≥ R_sa,选用 | **待核对** | 选用值 0.9 K/W 是设计给定（散热器型号在 159d 定） |

## 用到的器件数据

| 器件 | 厂家 | 规格书 | 网址 |
|---|---|---|---|
| 0215010.MXP | Littelfuse | Axial Lead & Cartridge Fuses 5×20 mm > Time-Lag > 215 Series Revised: 01/12/17 | https://www.lcsc.com/datasheet/C142733.pdf |
| 500MXH330MEFCSN30X50 | Rubycon | Rubycon MXH series SNAP-IN aluminum electrolytic capacitors catalog page 115-116 (no revision printed) | https://www.lcsc.com/datasheet/C472902.pdf |
| B57364S0259M000 | TDK | NTC thermistors for inrush current limiting, Series/Type S364/**/M**, B57364S0***M0** Date: 2021-04-22, Version a | https://www.lcsc.com/datasheet/C17362791.pdf |
| B72214S0271K101 | TDK (EPCOS) | SIOV metal oxide varistors, Leaded varistors, StandarD series, Series/Type: B722* Date: March 2018 | https://www.lcsc.com/datasheet/C7502584.pdf |
| BFC233920474 | Vishay BCcomponents | MKP339 X2 Interference Suppression Film Capacitors Document Number: 28138, Revision: 24-Jul-2019 | https://www.lcsc.com/datasheet/C511073.pdf |
| BSC040N08NS5 | Infineon | BSC040N08NS5 OptiMOS 5 Power-Transistor, 80 V, Final Data Sheet Rev. 2.2, 2020-05-15 | https://www.infineon.com/assets/row/public/documents/24/49/infineon-bsc040n08ns5-datasheet-en.pdf |
| C3D06060A | Wolfspeed (Cree) | C3D06060A Silicon Carbide Schottky Diode Z-Rec Rectifier Rev. F, 10-2015 | https://www.lcsc.com/datasheet/C5693025.pdf |
| ES3D | onsemi (Fairchild) | ES3A - ES3J Fast Rectifiers Rev. 2.11, June 2016 | https://www.lcsc.com/datasheet/C241735.pdf |
| G5LE-1-E DC12 | Omron | Power Relay G5LE-G / G5LE-E (no revision printed) | https://www.lcsc.com/datasheet/C152711.pdf |
| GBU1006 | LGE (Luguang) | GBU1001 - GBU1007 Single Phase 10.0 AMP. Glass Passivated Bridge Rectifiers Version: A06 | https://www.lcsc.com/datasheet/C5183365.pdf |
| ICE3PCS01G | Infineon | ICE3PCS01G Standalone Power Factor Correction (PFC) Controller in Continuous Conduction Mode (CCM), Datasheet Version 3.0, 03 April 2017 | https://www.lcsc.com/datasheet/C192050.pdf |
| IPW60R060P7 | Infineon | IPW60R060P7 600V CoolMOS P7 Power Transistor, Final Data Sheet Rev. 2.1, 2018-05-15 | https://www.lcsc.com/datasheet/C454258.pdf |
| SMBJ24A | Littelfuse | Surface Mount - 600 W > SMBJ series TVS Diodes Revised: JC.07/04/25 v4 | https://www.lcsc.com/datasheet/C224017.pdf |
| STGIPS14K60T | STMicroelectronics | STGIPS14K60T SLLIMM small low-loss intelligent molded module IPM, 3-phase inverter, 14 A, 600 V, Datasheet - production data DocID018534 Rev 5, April 2015 | https://www.lcsc.com/datasheet/C5268145.pdf |
| STM32G431CBT6 | STMicroelectronics | STM32G431x6/x8/xB (DS12589) Rev 6, 2021-10 | https://www.st.com/resource/en/datasheet/stm32g431cb.pdf |
| TMC2226-SA | ADI / Trinamic | TMC2226 Datasheet, Power driver for stepper motors Rev. 1.06 / 2020-MAY-18 | https://www.lcsc.com/datasheet/C705366.pdf |
| TOP266KG | Power Integrations | TOP264-271 TOPSwitch-JX Family, Integrated Off-Line Switcher with EcoSmart Technology Rev. E 08/12 | https://www.lcsc.com/datasheet/C568204.pdf |
| WSLT2512R0250FEA | Vishay Dale | WSLT2512 Power Metal Strip Resistors, High Temperature (275 °C), Low Value, Surface-Mount Document Number: 30121, Revision: 04-Apr-2022 | https://www.lcsc.com/datasheet/C4210426.pdf |

这些数值录入时没有逐页对照 PDF 核对，标“待核对”。核对后在 `eda/parts/` 里把 checked 改成 true。

