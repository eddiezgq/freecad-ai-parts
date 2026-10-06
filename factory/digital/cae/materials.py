# -*- coding: utf-8 -*-
"""材料库（第 11 轮 F5）：常用 12 种。每条注明出处；“估算”的数字也写明怎么估的。

单位：E_mpa、强度 MPa，密度 g/cm³。疲劳：sigma_1 = 对称循环弯曲疲劳极限 σ₋₁（光滑试样），
在 N_D 次时；S-N 曲线斜率 k（Basquin，σᵏ·N = 常数）。
"""

# 出处简称
SRC = {
    "PU": "濮良贵、陈国定《机械设计》第十版，高等教育出版社，表 15-1（轴的常用材料及其主要力学性能）",
    "699": "GB/T 699-2015《优质碳素结构钢》",
    "3077": "GB/T 3077-2015《合金结构钢》",
    "700": "GB/T 700-2006《碳素结构钢》",
    "1591": "GB/T 1591-2018《低合金高强度结构钢》（Q345 已改称 Q355，数值按 Q355）",
    "9439": "GB/T 9439-2023《灰铸铁件》",
    "1348": "GB/T 1348-2019《球墨铸铁件》（附录：力学和物理性能参考值）",
    "3191": "GB/T 3191-2019《铝及铝合金挤压棒材》",
    "ASM": "ASM Handbook Vol.2《Properties and Selection: Nonferrous Alloys》",
    "1220": "GB/T 1220-2007《不锈钢棒》",
    "ASM1": "ASM Handbook Vol.1《Properties and Selection: Irons, Steels》",
    "HB": "成大先《机械设计手册》第六版 第 1 卷（材料弹性常数）",
    "PL": "塑料典型值（厂商物性表区间的中值，如 CHIMEI PA-757、DuPont Zytel 101 干态），仅作教学",
    "TH": "热物性（导热系数 k、比热 c、线膨胀系数 α，20–100 ℃）：钢、不锈钢、铝取 ASM Handbook Vol.1/Vol.2 对应牌号"
          "（45→AISI 1045、40Cr→4140、20CrMnTi→8620、Q235→A36、304、6061-T6、7075-T6）的典型值；"
          "铸铁取 GB/T 9439、GB/T 1348 附录的物理性能参考值；塑料取厂商物性表中值。教学用，精确计算请查牌号实测值",
}

# 热物性：k 导热系数 W/(m·K)，c 比热 J/(kg·K)，alpha 线膨胀系数 10⁻⁶/K（第 14 轮）
THERMAL = {
    "45-QT": (49.8, 486, 11.2), "40Cr-QT": (42.6, 473, 12.2), "20CrMnTi-CQ": (46.6, 477, 11.9),
    "Q235": (51.9, 486, 11.7), "Q345": (46.0, 480, 12.0), "HT200": (50.0, 460, 10.5), "QT500-7": (35.2, 515, 12.5),
    "6061-T6": (167.0, 896, 23.6), "7075-T6": (130.0, 960, 23.6), "304": (16.2, 500, 17.3),
    "ABS": (0.17, 1400, 90.0), "PA66": (0.25, 1700, 80.0),
}

_STEEL_SN = {"N_D": 1e7, "k": 9, "sn_note": "钢：N₀ = 10⁷，m = 9（濮良贵《机械设计》第 3 章）"}

MATERIALS = [
    dict(id="45-QT", name="45 钢（调质）", E_mpa=210000, nu=0.30, density=7.85, yield_mpa=355, ultimate_mpa=640,
         sigma_1=275, tau_1=155, **_STEEL_SN, src=["PU", "699", "HB"],
         note="减速器轴最常用；σb、σs、σ₋₁、τ₋₁ 取濮良贵表 15-1（直径 ≤ 200 mm）"),
    dict(id="40Cr-QT", name="40Cr（调质）", E_mpa=210000, nu=0.30, density=7.85, yield_mpa=540, ultimate_mpa=735,
         sigma_1=355, tau_1=200, **_STEEL_SN, src=["PU", "3077", "HB"],
         note="受载较大的轴、齿轮；表 15-1（直径 ≤ 100 mm）"),
    dict(id="20CrMnTi-CQ", name="20CrMnTi（渗碳淬火回火）", E_mpa=207000, nu=0.30, density=7.85, yield_mpa=835,
         ultimate_mpa=1080, sigma_1=525, tau_1=300, **_STEEL_SN, src=["PU", "3077"],
         note="齿轮轴、高速重载；表 15-1（直径 ≤ 15 mm 时的芯部性能）"),
    dict(id="Q235", name="Q235", E_mpa=206000, nu=0.30, density=7.85, yield_mpa=235, ultimate_mpa=440,
         sigma_1=180, tau_1=105, **_STEEL_SN, src=["700", "PU"],
         note="不重要、受载小的轴、支架；σs 按 GB/T 700（≤16 mm），σb、σ₋₁ 取表 15-1 的 Q235-A"),
    dict(id="Q345", name="Q345（Q355）", E_mpa=206000, nu=0.30, density=7.85, yield_mpa=355, ultimate_mpa=470,
         sigma_1=210, tau_1=120, **_STEEL_SN, src=["1591", "HB"],
         note="焊接结构、机架；σ₋₁ ≈ 0.45σb 估算（GB/T 1591 不给疲劳值）"),
    dict(id="HT200", name="HT200 灰铸铁", E_mpa=110000, nu=0.26, density=7.20, yield_mpa=None, ultimate_mpa=200,
         sigma_1=80, tau_1=None, N_D=1e7, k=9, sn_note="铸铁按钢的曲线形状估算", src=["9439", "HB"], brittle=True,
         note="脆性材料没有屈服，安全系数按抗拉强度 Rm 算；E 取 GB/T 9439 附录区间中值；σ₋₁ ≈ 0.4Rm 估算"),
    dict(id="QT500-7", name="QT500-7 球墨铸铁", E_mpa=169000, nu=0.275, density=7.10, yield_mpa=320, ultimate_mpa=500,
         sigma_1=224, tau_1=None, N_D=1e7, k=9, sn_note="GB/T 1348 附录无缺口疲劳极限", src=["1348"],
         note="箱体、轮毂"),
    dict(id="6061-T6", name="6061-T6 铝合金", E_mpa=68900, nu=0.33, density=2.70, yield_mpa=276, ultimate_mpa=310,
         sigma_1=96.5, tau_1=None, N_D=5e8, k=8, sn_note="铝没有真正的疲劳极限：取 5×10⁸ 次的值（ASM，R.R. Moore 旋转弯曲），k=8 估算",
         src=["3191", "ASM"], note="机器人连杆、支架常用"),
    dict(id="7075-T6", name="7075-T6 铝合金", E_mpa=71700, nu=0.33, density=2.81, yield_mpa=503, ultimate_mpa=572,
         sigma_1=159, tau_1=None, N_D=5e8, k=8, sn_note="同 6061-T6", src=["3191", "ASM"], note="高强度轻量件"),
    dict(id="304", name="304 不锈钢（固溶）", E_mpa=193000, nu=0.29, density=7.93, yield_mpa=205, ultimate_mpa=520,
         sigma_1=240, tau_1=None, N_D=1e7, k=9, sn_note="ASM 退火态疲劳极限", src=["1220", "ASM1"],
         note="耐腐蚀件；冷加工后强度会高很多"),
    dict(id="ABS", name="ABS 塑料", E_mpa=2300, nu=0.35, density=1.05, yield_mpa=42, ultimate_mpa=45,
         sigma_1=13, tau_1=None, N_D=1e7, k=8, sn_note="约 0.3 倍屈服强度估算", src=["PL"],
         note="3D 打印、外壳；打印件层间强度还要再打折（约 0.5–0.8）"),
    dict(id="PA66", name="PA66 尼龙（干态）", E_mpa=3000, nu=0.39, density=1.14, yield_mpa=80, ultimate_mpa=85,
         sigma_1=25, tau_1=None, N_D=1e7, k=8, sn_note="约 0.3 倍屈服强度估算", src=["PL"],
         note="吸湿后 E、强度约降一半，潮湿环境要按湿态算"),
]

BY_ID = {m["id"]: m for m in MATERIALS}


def get(mid):
    m = BY_ID.get(mid)
    if not m:
        raise ValueError("材料库里没有 {}".format(mid))
    m = dict(m)
    m["density_t_mm3"] = m["density"] * 1e-9
    m["strength_mpa"] = m["yield_mpa"] or m["ultimate_mpa"]       # 安全系数按这个算
    m["strength_kind"] = "屈服强度" if m["yield_mpa"] else "抗拉强度"
    k, c, a = THERMAL[mid]
    m.update(k_w_mk=k, c_j_kgk=c, alpha_1e6=a, thermal_src=SRC["TH"])
    return m


def public():
    out = []
    for m in MATERIALS:
        d = dict(m)
        d["sources"] = [SRC[s] for s in m["src"]] + [SRC["TH"]]
        d["k_w_mk"], d["c_j_kgk"], d["alpha_1e6"] = THERMAL[m["id"]]
        out.append(d)
    return out


# 表面换热系数参考（第 14 轮）：W/(m²·K)。对流 + 辐射合在一起的“散热系数”，用于箱体外表面
FILM = [
    {"id": "air-still", "name": "室内静止空气，自然对流（通风差）", "h": 8.15, "src": "濮良贵《机械设计》第十版 11.6 节：散热系数 K_s = 8.15–17.45 W/(m²·℃)，通风差取小值"},
    {"id": "air-vent", "name": "通风良好，自然对流", "h": 17.45, "src": "同上，通风良好取大值"},
    {"id": "fan-1000", "name": "轴端装风扇（风扇转速 1000 r/min）", "h": 31.0, "src": "濮良贵《机械设计》第十版 第 11 章蜗杆传动热平衡：风扇冷却时的散热系数（风扇转速 750 r/min 约 27、1000 r/min 约 31、1550 r/min 约 38 W/(m²·℃)）"},
    {"id": "fan-1500", "name": "轴端装风扇（风扇转速约 1500 r/min）", "h": 38.0, "src": "同上"},
    {"id": "air-forced", "name": "强制风冷（散热片、风扇直吹）", "h": 50.0, "src": "传热学教材常用区间：强制对流空气 25–250 W/(m²·K)，取偏小值"},
    {"id": "oil", "name": "箱内油液与内壁（参考）", "h": 100.0, "src": "传热学教材：油液自然对流约 50–350 W/(m²·K)，教学取 100"},
    {"id": "water", "name": "水冷（参考）", "h": 1000.0, "src": "传热学教材：水强制对流约 500–10000 W/(m²·K)，教学取 1000"},
]
