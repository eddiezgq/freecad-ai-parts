# -*- coding: utf-8 -*-
"""切削功率检查（第 13 轮 C6）：与工艺规程的切削功率校核用同一张 Kienzle 表（std/kienzle.yaml，读表模块 std/stdtab.py）。
切深用仿真算出的“实际最大切深”，不是编程单上写的值——端面、轴肩处常常比编程单大。

  车削（主偏角 90°，h = f）：F_c = k_c1.1 · a_p · f^(1−m_c)，P_c = F_c · v_c / 60 000（kW）
  铣削：平均切屑厚度 h_m（满槽 h_m ≈ 2·f_z/π，侧铣 h_m ≈ f_z·√(a_e/D)），k_c = k_c1.1 · h_m^(−m_c)，P_c = a_p · a_e · v_f · k_c / (60·10⁶)（kW）
  钻孔：h = f/2，P_c = f · D · k_c · v_c / 240 000（kW）
机床主电机功率 ≥ P_c / η 才够；超过 80% 提醒。"""
import math
import os
import sys

MATERIAL = {"45": "C45E", "45 钢": "C45E", "40Cr": "MD07", "20CrMnTi": "C45E", "Q235": "S235JR", "6061": "MD22", "7075": "MD22",
            "HT200": "MD15", "304": "MD14"}


def _row(material):
    p = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "std"))
    if p not in sys.path:
        sys.path.insert(0, p)
    import stdtab
    t = stdtab.table("kienzle")
    key = next((v for k, v in MATERIAL.items() if k in str(material or "45")), "C45E")
    return t.row(key), t.label()


def check(kind, material, machine, items):
    """items：[(名称, dict)]；dict 按 kind：
       turn  {vc, f, ap}；slot/mill {vc 不用, fz, z, ap, ae, D, vf}；drill {vc, f, D}
    返回 (检查条目, 明细)"""
    from cae.cam_post import MACHINES
    m = MACHINES[machine]
    row, label = _row(material)
    k11, mc = float(row["kc11_MPa"]), float(row["mc"])
    out, detail = [], []
    for name, x in items:
        if x.get("type") == "drill":
            h = max(x["f"] / 2, 1e-3)
            kc = k11 * h ** (-mc)
            P = x["f"] * x["D"] * kc * x["vc"] / 240000.0
        elif kind == "turn":
            Fc = k11 * x["ap"] * x["f"] ** (1 - mc)
            P = Fc * x["vc"] / 60000.0
        else:
            ae, D = min(x["ae"], x["D"]), x["D"]
            hm = 2 * x["fz"] / math.pi if ae >= D - 1e-9 else x["fz"] * math.sqrt(ae / D)
            kc = k11 * max(hm, 1e-3) ** (-mc)
            P = x["ap"] * ae * x["vf"] * kc / 60e6
        need = P / m["eff"]
        detail.append({"name": name, "P_kw": round(P, 3), "need_kw": round(need, 3)})
        if need > m["power_kw"]:
            out.append({"line": None, "level": "error", "text": "{}：切削功率约 {:.1f} kW，按效率 {:g} 要 {:.1f} kW，超过 {} 主电机 {:g} kW——减小切深或进给".format(
                name, P, m["eff"], need, m["name"], m["power_kw"])})
        elif need > 0.8 * m["power_kw"]:
            out.append({"line": None, "level": "warn", "text": "{}：要 {:.1f} kW，已到主电机 {:g} kW 的 {:.0%}".format(name, need, m["power_kw"], need / m["power_kw"])})
    return out, {"items": detail, "table": label, "material_row": row.get("material"), "kc11_MPa": k11, "mc": mc,
                 "machine_kw": m["power_kw"], "eff": m["eff"]}
