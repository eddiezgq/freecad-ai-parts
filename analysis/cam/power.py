"""切削功率检查（ADR-0059）：Kienzle 公式，单位切削力表 analysis/common/kienzle.yaml（每行带出处）。搬自数字工厂 cae/cam_power.py。
材料由使用者在表里选一行（不按牌号自动近似）；没选时功率为待确认。

  车削（主偏角 90°，h = f）：F_c = k_c1.1 · a_p · f^(1−m_c)，P_c = F_c · v_c / 60 000（kW）
  铣削：平均切屑厚度 h_m（满槽 h_m ≈ 2·f_z/π，侧铣 h_m ≈ f_z·√(a_e/D)），k_c = k_c1.1 · h_m^(−m_c)，P_c = a_p · a_e · v_f · k_c / (60·10⁶)（kW）
  钻孔：h = f/2，k_c = k_c1.1 · h^(−m_c)，P_c = f · D · k_c · v_c / 240 000（kW）
机床主电机功率 ≥ P_c / η 才够；超过 80% 提醒。
"""

from __future__ import annotations

import math
from functools import cache
from pathlib import Path

import yaml

TABLE = Path(__file__).resolve().parent.parent / "common" / "kienzle.yaml"


@cache
def _table() -> dict:
    return yaml.safe_load(TABLE.read_text(encoding="utf-8"))


def rows() -> list[dict]:
    """表中各行：key、材料、中文名、kc1.1、mc、出处。"""
    t = _table()
    src = {s["key"]: s["title"] for s in t["sources"]}
    return [{"key": r["key"], "material": r["material"], "material_cn": r.get("material_cn", ""), "kc11_mpa": r["kc11_MPa"],
             "mc": r["mc"], "source": "；".join(src[k] for k in str(r["src"]).split("+") if k in src)} for r in t["rows"]]


def row(key: str) -> dict | None:
    return next((r for r in rows() if r["key"] == key), None)


def turning_kw(kc11, mc, ap, f, vc):
    return kc11 * ap * f ** (1 - mc) * vc / 60000.0


def milling_kw(kc11, mc, fz, ap, ae, d, vf):
    ae = min(ae, d)
    hm = 2 * fz / math.pi if ae >= d - 1e-9 else fz * math.sqrt(ae / d)
    return ap * ae * vf * kc11 * max(hm, 1e-3) ** (-mc) / 60e6


def drilling_kw(kc11, mc, f, d, vc):
    return f * d * kc11 * max(f / 2, 1e-3) ** (-mc) * vc / 240000.0


def check(key: str | None, machine: dict, items: list[tuple[str, str, dict]]) -> tuple[list[dict], dict]:
    """items：[(名称, "turn" | "mill" | "drill", 参数)]。返回 (检查条目, 明细)；没选材料行时只给“待确认”。"""
    r = row(key) if key else None
    if r is None:
        return ([{"line": None, "level": "unknown", "text": "切削功率待确认：没有选 Kienzle 表中的材料行"}],
                {"items": [], "status": "unknown"})
    k11, mc = float(r["kc11_mpa"]), float(r["mc"])
    out, detail = [], []
    for name, kind, x in items:
        if kind == "drill":
            p = drilling_kw(k11, mc, x["f"], x["d"], x["vc"])
        elif kind == "turn":
            p = turning_kw(k11, mc, x["ap"], x["f"], x["vc"])
        else:
            p = milling_kw(k11, mc, x["fz"], x["ap"], x["ae"], x["d"], x["vf"])
        need = p / machine["eff"]
        detail.append({"name": name, "cut_kw": round(p, 4), "need_kw": round(need, 4)})
        if need > machine["power_kw"]:
            out.append({"line": None, "level": "error",
                        "text": f"{name}：切削功率约 {p:.2f} kW，按效率 {machine['eff']:g} 要 {need:.2f} kW，超过 {machine['name']} "
                                f"主电机 {machine['power_kw']:g} kW——减小切深或进给"})
        elif need > 0.8 * machine["power_kw"]:
            out.append({"line": None, "level": "warn",
                        "text": f"{name}：要 {need:.2f} kW，已到主电机 {machine['power_kw']:g} kW 的 {need / machine['power_kw']:.0%}"})
    return out, {"items": detail, "status": "ok", "row": r["key"], "material": r["material"], "kc11_mpa": k11, "mc": mc,
                 "source": r["source"], "machine_kw": machine["power_kw"], "eff": machine["eff"]}
