"""阶梯轴设计 → 三维模型 → 测量回读 → 二维图、BOM（ADR-0100 42.3）。

1. 模型：校核通过的轴段（`assist.shaft_design.check_proposal` 的结果，直径、长度、台阶圆角）沿 z 排，左端 z = 0。
   相邻同径的段（例如曲柄座与轴承位同为 Ø12）在模型里是同一个圆柱面；台阶处在小径一侧按方案的圆角倒圆
   （OCCT，经 Gmsh 的 OpenCASCADE 接口，与 FreeCAD 同一内核），写 STEP。
2. 回读：用 41.4 的测量（`assist.measure.measure`）量这个 STEP，与设计逐段核对：
   直径 ±0.01 mm、圆柱面的起点与长度 ±0.05 mm。圆角吃掉小径圆柱面靠台阶的一头 r，期望值里已扣掉。
   回读不一致的模型不交付（结论 fail，列出哪一段差多少）。
3. 二维图：轴的外形轮廓（SVG），标各段直径、长度、圆角与总长；尺寸全部来自设计数据，回读一致后才出。
4. BOM：自制件（这根轴：图号、材料、质量取回读的体积 × 材料密度）+ 库里选用的轴承（组件 id、数量）。

纯计算与本机几何内核：不联网、不调用 AI。
"""

from __future__ import annotations

import json
from html import escape
from itertools import pairwise
from pathlib import Path

D_TOL_MM = 0.01
L_TOL_MM = 0.05


class ModelError(RuntimeError):
    pass


def runs(segs: list[dict]) -> list[dict]:
    """相邻同径的段合成一个圆柱：[{d, z0, z1, r_left, r_right, parts}]；r_* 是该圆柱两头台阶的圆角（只在它是小径一侧时）"""
    out: list[dict] = []
    z = 0.0
    for i, s in enumerate(segs):
        if out and abs(out[-1]["d"] - s["d"]) < 1e-9:
            out[-1]["z1"] = z + s["L"]
            out[-1]["parts"].append(i)
            out[-1]["r_out"] = s.get("r")
        else:
            out.append({"d": float(s["d"]), "z0": z, "z1": z + s["L"], "parts": [i], "r_out": s.get("r")})
        z += s["L"]
    for a, b in pairwise(out):
        r = a["r_out"]                                   # 方案里圆角写在台阶左边那一段
        if r is None:
            raise ModelError(f"z {a['z1']:g} 的台阶没有圆角，模型不生成（先补圆角，校核也会是待确认）")
        if r >= abs(a["d"] - b["d"]) / 2 - 1e-9:
            raise ModelError(f"z {a['z1']:g} 的台阶圆角 {r:g} 不小于台阶高度，做不出来")
        if a["d"] < b["d"]:
            a["r_right"] = r
        else:
            b["r_left"] = r
    for r in out:
        r.setdefault("r_left", 0.0)
        r.setdefault("r_right", 0.0)
        r.pop("r_out")
    return out


def build_step(segs: list[dict], path: str | Path) -> str:
    """写阶梯轴 STEP（单位 mm，轴线 z）"""
    from analysis.fea.geometry import _LOCK, _gmsh

    rs = runs(segs)
    path = Path(path)
    with _LOCK:
        g = _gmsh()
        g.clear()
        g.model.add("shaft")
        occ = g.model.occ
        vols = [(3, occ.addCylinder(0, 0, r["z0"], 0, 0, r["z1"] - r["z0"], r["d"] / 2)) for r in rs]
        out = occ.fuse([vols[0]], vols[1:])[0] if len(vols) > 1 else vols
        occ.synchronize()
        if len(out) != 1:
            g.clear()
            raise ModelError(f"轴段合成后不是一个实体（{len(out)} 个）")
        edges, radii = [], []
        for a, b in pairwise(rs):
            small, r = (a["d"], a["r_right"]) if a["d"] < b["d"] else (b["d"], b["r_left"])
            for _, t in g.model.getEntities(1):
                bb = g.model.getBoundingBox(1, t)
                if abs(bb[2] - a["z1"]) < 1e-6 and abs(bb[5] - a["z1"]) < 1e-6 and abs((bb[3] - bb[0]) / 2 - small / 2) < 1e-6:
                    edges.append(t)
                    radii.append(r)
        if edges:
            try:
                occ.fillet([out[0][1]], edges, radii)
            except Exception as ex:                      # 内核做不出圆角：不交付模型，说原因
                g.clear()
                raise ModelError(f"圆角做不出来：{ex}") from ex
            occ.synchronize()
        g.write(str(path))
        g.clear()
    return str(path)


def expected_faces(segs: list[dict]) -> list[dict]:
    """回读应量到的外圆柱面：[{diameter_mm, start_mm, length_mm}]（圆角吃掉的长度已扣）"""
    return [{"diameter_mm": r["d"], "start_mm": round(r["z0"] + r["r_left"], 4),
             "length_mm": round(r["z1"] - r["z0"] - r["r_left"] - r["r_right"], 4)} for r in runs(segs)]


def compare(expected: list[dict], measured: list[dict]) -> dict:
    """逐段核对：{"overall": pass / fail, "rows": [...], "problems": [...]}"""
    rows, problems = [], []
    if len(expected) != len(measured):
        problems.append(f"圆柱面个数：设计 {len(expected)} 段，模型量出 {len(measured)} 段")
    for k, (e, m) in enumerate(zip(expected, measured, strict=False), 1):
        dd = m["diameter_mm"] - e["diameter_mm"]
        ds = m["start_mm"] - e["start_mm"]
        dl = m["length_mm"] - e["length_mm"]
        ok = abs(dd) <= D_TOL_MM and abs(ds) <= L_TOL_MM and abs(dl) <= L_TOL_MM
        rows.append({"segment": k, "design": e, "measured": m, "diff_mm": {"diameter": round(dd, 4), "start": round(ds, 4),
                                                                          "length": round(dl, 4)}, "ok": ok})
        if not ok:
            problems.append(f"第 {k} 段：直径差 {dd:+.3f}、起点差 {ds:+.3f}、长度差 {dl:+.3f} mm")
    return {"overall": "fail" if problems else "pass", "tolerance_mm": {"diameter": D_TOL_MM, "length": L_TOL_MM},
            "rows": rows, "problems": problems}


def readback(segs: list[dict], step: str | Path, material: str | None) -> dict:
    """量 STEP 并与设计核对；返回 compare 的结果加上测量（体积、质量、包络）"""
    from assist import measure

    m = measure.measure(step, material=material)
    res = compare(expected_faces(segs), m["segments"])
    res["measurement"] = {k: m[k] for k in ("file", "sha256", "envelope_mm", "volume_mm3", "mass_kg", "material",
                                            "density_kg_m3", "geometry_check") if k in m}
    return res


# ---------------------------------------------------------------- 二维图（SVG）


def drawing_svg(segs: list[dict], *, title: str, drawing_no: str, material: str, scale: float | None = None) -> str:
    """轴的外形轮廓图：中心线、各段轮廓、直径与长度尺寸、总长；数字全部取设计数据"""
    rs = runs(segs)
    total = rs[-1]["z1"]
    dmax = max(r["d"] for r in rs)
    k = scale or min(900.0 / total, 12.0)               # 每 mm 多少像素
    x0, yc = 60.0, 60.0 + dmax * k / 2 + 40
    w, h = x0 * 2 + total * k, yc + dmax * k / 2 + 150
    el = [f'<line x1="{x0 - 20:.1f}" y1="{yc:.1f}" x2="{x0 + total * k + 20:.1f}" y2="{yc:.1f}" class="c"/>']
    pts = [(x0, yc)]
    for r in rs:
        y = yc - r["d"] / 2 * k
        pts += [(x0 + r["z0"] * k, y), (x0 + r["z1"] * k, y)]
    pts.append((x0 + total * k, yc))
    up = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    down = " ".join(f"{x:.1f},{2 * yc - y:.1f}" for x, y in reversed(pts))
    el.append(f'<polygon points="{up} {down}" class="o"/>')
    for a, b in pairwise(rs):                            # 台阶竖线
        x = x0 + a["z1"] * k
        hi = max(a["d"], b["d"]) / 2 * k
        el.append(f'<line x1="{x:.1f}" y1="{yc - hi:.1f}" x2="{x:.1f}" y2="{yc + hi:.1f}" class="t"/>')
    for i, r in enumerate(rs):                           # 直径（写在段中间）与长度（下方一排）
        xm = x0 + (r["z0"] + r["z1"]) / 2 * k
        el.append(f'<text x="{xm:.1f}" y="{yc - r["d"] / 2 * k - 8:.1f}" class="n">Ø{r["d"]:g}</text>')
        y = yc + dmax / 2 * k + 30 + (i % 2) * 18
        xa, xb = x0 + r["z0"] * k, x0 + r["z1"] * k
        el.append(f'<line x1="{xa:.1f}" y1="{y:.1f}" x2="{xb:.1f}" y2="{y:.1f}" class="d"/>')
        el.append(f'<text x="{(xa + xb) / 2:.1f}" y="{y - 3:.1f}" class="n">{r["z1"] - r["z0"]:g}</text>')
    y = yc + dmax / 2 * k + 80
    el.append(f'<line x1="{x0:.1f}" y1="{y:.1f}" x2="{x0 + total * k:.1f}" y2="{y:.1f}" class="d"/>')
    el.append(f'<text x="{x0 + total * k / 2:.1f}" y="{y - 3:.1f}" class="n">{total:g}</text>')
    steps = [f"z {a['z1']:g} R{(a['r_right'] or b['r_left']):g}" for a, b in pairwise(rs)]
    note = f"台阶圆角：{'，'.join(steps)}" if steps else ""
    el.append(f'<text x="{x0:.1f}" y="{h - 30:.1f}" class="l">{escape(title)}　图号 {escape(drawing_no)}　材料 {escape(material)}'
              f'　单位 mm　{escape(note)}</text>')
    style = ("<style>.c{stroke:#555;stroke-dasharray:12 3 2 3;stroke-width:.8}.o{fill:none;stroke:#000;stroke-width:1.6}"
             ".t{stroke:#000;stroke-width:1}.d{stroke:#000;stroke-width:.6;marker-start:url(#a);marker-end:url(#a)}"
             ".n{font:12px sans-serif;text-anchor:middle}.l{font:13px sans-serif}</style>")
    marker = ('<defs><marker id="a" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">'
              '<path d="M0,2 L10,5 L0,8 z"/></marker></defs>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w:.0f}" height="{h:.0f}" viewBox="0 0 {w:.0f} {h:.0f}">'
            f'<rect width="100%" height="100%" fill="#fff"/>{style}{marker}{"".join(el)}</svg>\n')


# ---------------------------------------------------------------- BOM 与整套输出


def bom(segs: list[dict], rb: dict, *, drawing_no: str, name: str, get) -> list[dict]:
    """自制件一行（质量取回读）+ 选用的轴承（按组件 id 合并数量）"""
    meas = rb.get("measurement", {})
    rows = [{"item": 1, "kind": "custom_part", "drawing_no": drawing_no, "name": name, "qty": 1,
             "material": meas.get("material"), "mass_kg": meas.get("mass_kg"),
             "mass_source": "回读模型的体积 × 材料密度" if meas.get("mass_kg") is not None else None}]
    count: dict[str, int] = {}
    for s in segs:
        if s.get("bearing"):
            count[s["bearing"]] = count.get(s["bearing"], 0) + 1
    for cid, n in count.items():
        c = get(cid) or {}
        mass = ((c.get("params") or {}).get("mass_kg") or {}).get("value")
        rows.append({"item": len(rows) + 1, "kind": "bearing", "component": cid, "vendor": c.get("vendor"),
                     "model": c.get("model"), "qty": n, **({"mass_kg": mass} if mass is not None else {})})
    return [{k: v for k, v in r.items() if v is not None} for r in rows]


def generate(result: dict, out_dir: str | Path, get, *, drawing_no: str = "AI-SHAFT-1", name: str = "上轴（AI 设计）") -> dict:
    """design() 的结果（status pass）→ out_dir 下 shaft.step、readback.json、drawing.svg、bom.json；返回摘要"""
    from assist import shaft_design as SD

    if not str(result.get("status", "")).startswith("pass"):
        raise ModelError(f"设计没有通过（{result.get('status')}），不生成模型")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    segs, _ = SD.check_proposal(_chosen(result)["proposal"], get)
    material = result["conditions"].get("material")
    step = build_step(segs, out_dir / "shaft.step")
    rb = readback(segs, step, material)
    (out_dir / "readback.json").write_text(json.dumps(rb, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    summary = {"readback": rb["overall"], "problems": rb["problems"], "step": "shaft.step", "readback_rows": len(rb["rows"]),
               "mass_kg": rb["measurement"].get("mass_kg"), "volume_mm3": rb["measurement"].get("volume_mm3")}
    if rb["overall"] != "pass":
        summary["delivered"] = False
        return summary
    (out_dir / "drawing.svg").write_text(drawing_svg(segs, title=name, drawing_no=drawing_no, material=material or "未定"),
                                         encoding="utf-8")
    rows = bom(segs, rb, drawing_no=drawing_no, name=name, get=get)
    (out_dir / "bom.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    summary.update(delivered=True, drawing="drawing.svg", bom=rows)
    return summary


def _chosen(result: dict) -> dict:
    from assist.design import chosen

    return chosen(result)
