# -*- coding: utf-8 -*-
"""板子热分析（第 111 轮 P4）：损耗 → 板子平板模型（CalculiX）→ 功率器件结温，和器件允许的最高结温比。

损耗（每个发热器件，按设计描述板子层 thermal.heat 列的位号）：
  mosfet  导通 P = I² · R_DS(on)；开关 P = ½ · V_母线 · I · (t_on + t_off) · f_PWM，
          t_on = Q_sw / I_g,on，t_off = Q_sw / I_g,off；I_g 取驱动器最小输出电流和栅极回路能给的电流中小的那个。
          保守：电流按额定相电流的直流算，每个管子都按整段导通、每次都硬开关算。
  shunt   P = I² · R
  calc    损耗直接取计算书的结果（item: <功能块>.<条目>，share 只数分摊；第 159 轮平缝机控制器加）：
          板上温度和板子允许温度（thermal.board_max_c）比
导热：每格的面内导热按铜层厚度和这一格的铜占比并联折算，厚度方向按各层串联折算（过孔的导热没算，偏保守）。
  铜 390 W/(m·K)、FR-4 0.25 W/(m·K)：Electronics Cooling, Calculation Corner “Conduction heat transfer in a printed
  circuit board”, 1998-05。
结温 = 器件焊盘下板子的最高温度 + 损耗 × 结到壳（底面）热阻。

判定：器件数据没核对 → 待核对；R_DS(on) 只有 25 ℃ 的值时，算出的结温偏低，没超上限也只能判“未知”。
纯计算部分不联网、不调 AI；只有 solve() 调本机 CalculiX。"""

from __future__ import annotations

from ..blocks import common as c
from . import plate

K_CU, K_FR4 = 390.0, 0.25
K_SOURCE = "Electronics Cooling 1998-05 Calculation Corner：铜 390、FR-4 0.25 W/(m·K)"
OZ_MM = 0.0348  # 1 oz/ft² 铜厚 ≈ 34.8 μm（1.37 mil）
DX_MM = 1.0


def _unit(doc_or_x, typ):
    for b in doc_or_x["blocks"]:
        for u in b.get("units") or []:
            if u["type"] == typ:
                return u["params"]
    return None


def calc_items(book):
    """计算书 → {"功能块.条目": (数值, 名称)}"""
    out = {}
    for u in (book or {}).get("units") or []:
        for it in u.get("items") or []:
            if it.get("key") and isinstance(it.get("value"), (int, float)):
                out["{}.{}".format(u["block"], it["key"])] = (float(it["value"]), it.get("name", ""))
    return out


def losses(doc, x, devices, book=None):
    """每个发热位号的损耗：[{ref, model, p_w, parts:[(名称, W)], status, notes}]。
    doc = 设计描述（读功能块参数）；book = 计算书（calc 模型要）"""
    items = calc_items(book)
    th, spec = x.get("thermal") or {}, doc["spec"]
    irat, vbus = spec.get("phase_current_a"), spec.get("bus_voltage_v")
    hb, gd, cs = _unit(doc, "half_bridge"), _unit(doc, "gate_drive"), _unit(doc, "current_sense")
    out = []
    for h in th.get("heat") or []:
        for ref in h["refs"]:
            row = {"ref": ref, "model": h["model"], "parts": [], "notes": [], "status": c.PASS}

            def need(part, key, row=row):
                v = devices.value(part, key)
                if v is None:
                    row["status"] = c.UNKNOWN
                    row["notes"].append("{} 没录 {}".format(part, key))
                elif not devices.checked(part, key) and row["status"] == c.PASS:
                    row["status"] = c.PENDING
                return v

            if h["model"] == "mosfet" and hb:
                fet = hb["fet"]
                rds_hot = devices.value(fet, "rds_on_max_hot")
                rds = rds_hot if rds_hot is not None else need(fet, "rds_on_max")
                if rds_hot is not None:
                    need(fet, "rds_on_max_hot")
                else:
                    row["notes"].append("R_DS(on) 用 25 ℃ 的最大值；结温高时更大，导通损耗偏低")
                    row["rds_cold"] = True
                if rds is not None and irat is not None:
                    row["parts"].append(("导通 I²·R_DS(on)", irat**2 * rds))
                f = th.get("f_pwm_hz")
                qsw, vpl, rgi = need(fet, "qsw"), need(fet, "v_plateau"), need(fet, "rg_int")
                drv = gd and gd.get("driver")
                ion, ioff = (need(drv, "io_plus_min"), need(drv, "io_minus_min")) if drv else (None, None)
                if None in (f, qsw, vpl, rgi, ion, ioff) or not gd:
                    row["notes"].append("开关损耗缺数据，没算")
                    row["status"] = c.UNKNOWN
                else:
                    rg = gd["RG_OHM"] + rgi
                    ig_on = min(ion, (gd["VDRV"] - vpl) / rg)
                    ig_off = min(ioff, vpl / rg)
                    t_sw = qsw / ig_on + qsw / ig_off
                    row["parts"].append(("开关 ½·V·I·(t_on+t_off)·f", 0.5 * vbus * irat * t_sw * f))
                    row["t_sw_ns"] = round(t_sw * 1e9, 1)
            elif h["model"] == "shunt" and cs:
                rs = cs["RS_MOHM"] * 1e-3
                row["parts"].append(("I²·R", irat**2 * rs))
            elif h["model"] == "calc":
                v = items.get(h.get("item"))
                if v is None:
                    row["status"] = c.UNKNOWN
                    row["notes"].append("计算书里没有 {}".format(h.get("item")))
                else:
                    share = h.get("share", 1)
                    row["parts"].append(("计算书 {}{}".format(v[1], "（{} 只分摊）".format(share) if share > 1 else ""),
                                         v[0] / share))
            row["p_w"] = sum(p for _, p in row["parts"])
            out.append(row)
    return out


def k_layers(x):
    """各铜层厚度 mm（外层、内层按叠层）和 FR-4 厚度"""
    st = x["stackup"]
    n = x["layers"]
    t_cu = [st["outer_oz"] * OZ_MM] + [st["inner_oz"] * OZ_MM] * (n - 2) + [st["outer_oz"] * OZ_MM]
    return t_cu, st["thickness_mm"] - sum(t_cu)


def cell_k(fracs, t_cu, t_fr4):
    """一格的 (面内 k, 厚度方向 k)：fracs = 每层这一格的铜占比"""
    t = t_fr4 + sum(t_cu)
    kin = (
        sum(f * tc * K_CU for f, tc in zip(fracs, t_cu, strict=True))
        + (t_fr4 + sum((1 - f) * tc for f, tc in zip(fracs, t_cu, strict=True))) * K_FR4
    ) / t
    kz = t / (t_fr4 / K_FR4 + sum(tc / K_CU for tc in t_cu))
    return kin, kz


def grid(board, x, dx=DX_MM):
    """板子模型 → 网格：每格每层的铜占比、热源分到哪些格"""
    import shapely
    from shapely.geometry import box
    from shapely.ops import unary_union

    x0, y0, x1, y1 = board.outline_geom.bounds if board.outline_geom is not None else board.outline
    nx, ny = max(1, round((x1 - x0) / dx)), max(1, round((y1 - y0) / dx))
    cells = [box(x0 + i * dx, y0 + j * dx, x0 + (i + 1) * dx, y0 + (j + 1) * dx) for j in range(ny) for i in range(nx)]
    order = ["F"] + ["In{}".format(k) for k in range(1, x["layers"] - 1)] + ["B"]
    fr = {}
    for lay in order:
        u = unary_union([f.geom for f in board.features if f.layer == lay])
        a = shapely.area(shapely.intersection(cells, u)) / (dx * dx) if not u.is_empty else [0.0] * len(cells)
        fr[lay] = list(a)
    return {"nx": nx, "ny": ny, "dx": dx, "x0": x0, "y0": y0, "cells": cells, "layers": order, "frac": fr}


def heat_cells(board, g, rows):
    """每个位号的损耗按它的焊盘面积分到格子里"""
    import shapely
    from shapely.ops import unary_union

    q, where = {}, {}
    for r in rows:
        pads = [
            f.geom for f in board.features if f.kind in ("pad", "pth") and f.ref == r["ref"] and f.layer in ("F", "B")
        ]
        if not pads or r["p_w"] <= 0:
            continue
        u = unary_union(pads)
        a = shapely.area(shapely.intersection(g["cells"], u))
        tot = float(sum(a))
        idx = [k for k, v in enumerate(a) if v > 0]
        where[r["ref"]] = [(k % g["nx"], k // g["nx"]) for k in idx]
        for k in idx:
            key = (k % g["nx"], k // g["nx"])
            q[key] = q.get(key, 0.0) + r["p_w"] * a[k] / tot
    return q, where


def solve(board, doc, x, devices, workdir=None, dx=DX_MM, book=None):
    """整套：损耗 → 网格 → CalculiX → 结温判定。返回报告用的字典（没写热分析条件、缺板子形状时 status = unknown）"""
    th = x.get("thermal") or {}
    if not th or not x.get("stackup"):
        return {
            "status": c.UNKNOWN,
            "detail": "设计描述没写热分析条件（board.thermal）或叠层（board.stackup）",
            "rows": [],
        }
    if not board.features:
        return {"status": c.UNKNOWN, "detail": "板子模型里没有铜的形状", "rows": []}
    rows = losses(doc, x, devices, book)
    g = grid(board, x, dx)
    t_cu, t_fr4 = k_layers(x)
    k = {}
    for idx in range(g["nx"] * g["ny"]):
        fr = [g["frac"][lay][idx] for lay in g["layers"]]
        k[(idx % g["nx"], idx // g["nx"])] = cell_k(fr, t_cu, t_fr4)
    q, where = heat_cells(board, g, rows)
    from . import ccx

    nt = ccx.run(
        plate.deck(g["nx"], g["ny"], g["dx"], x["stackup"]["thickness_mm"], k, q, th["h_w_m2k"], th["ambient_c"]),
        workdir,
    )
    T = plate.cell_temps(nt, g["nx"], g["ny"])
    hb = _unit(doc, "half_bridge")
    for r in rows:
        cells = where.get(r["ref"]) or []
        r["t_board_c"] = round(max(T[cc] for cc in cells), 1) if cells else None
        if r["model"] == "mosfet" and hb and r["t_board_c"] is not None:
            fet = hb["fet"]
            rth, tjm = devices.value(fet, "rth_jc_bottom"), devices.value(fet, "tj_max")
            if rth is None or tjm is None:
                r["status"] = c.UNKNOWN
                r["notes"].append("没录结到壳热阻或最高结温")
                continue
            for key in ("rth_jc_bottom", "tj_max"):
                if not devices.checked(fet, key) and r["status"] == c.PASS:
                    r["status"] = c.PENDING
            r["tj_c"] = round(r["t_board_c"] + r["p_w"] * rth, 1)
            r["tj_max_c"] = tjm
            if r["tj_c"] > tjm:
                r["status"] = c.FAIL
            elif r.get("rds_cold"):
                r["status"] = c.UNKNOWN
                r["notes"].append("结温 {:.0f} ℃ 没超上限，但损耗偏低，判不了".format(r["tj_c"]))
    for r in rows:
        if r["model"] != "calc" or r["status"] == c.UNKNOWN:
            continue
        lim = th.get("board_max_c")
        if r["t_board_c"] is None:
            r["status"] = c.UNKNOWN
            r["notes"].append("板子上找不到它的焊盘")
        elif lim is None:
            r["status"] = c.UNKNOWN
            r["notes"].append("设计描述没写板子允许温度（thermal.board_max_c）")
        else:
            r["t_limit_c"] = lim
            r["status"] = c.PASS if r["t_board_c"] <= lim else c.FAIL
    tmax = max(T.values())
    st = {r["status"] for r in rows}
    status = next((s for s in (c.FAIL, c.UNKNOWN, c.PENDING) if s in st), c.PASS)
    imax = max(T, key=T.get)
    return {
        "status": status,
        "rows": rows,
        "t_max_c": round(tmax, 1),
        "t_max_at": [round(g["x0"] + (imax[0] + 0.5) * g["dx"], 1), round(g["y0"] + (imax[1] + 0.5) * g["dx"], 1)],
        "total_w": round(sum(r["p_w"] for r in rows), 2),
        "ambient_c": th["ambient_c"],
        "h_w_m2k": th["h_w_m2k"],
        "source": th.get("source", ""),
        "k_source": K_SOURCE,
        "grid": "{} × {} 格，每格 {:g} mm".format(g["nx"], g["ny"], g["dx"]),
        "temps": {
            "nx": g["nx"],
            "ny": g["ny"],
            "dx": g["dx"],
            "x0": g["x0"],
            "y0": g["y0"],
            "t": [round(T[(i, j)], 1) for j in range(g["ny"]) for i in range(g["nx"])],
        },
        "detail": "简化模型：板子当一块平板，没算器件本体、外壳和过孔导热；只作布局阶段的估算，不替代样板实测",
    }
