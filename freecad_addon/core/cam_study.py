"""问渠CAM 窗口背后的逻辑（ADR-0104 产品化第 2 步）：不需要界面，可测。

- 车削件：输入文字（“直径×长度”各段、槽、螺纹、内孔）→ analysis.cam.run 的 turn 设置；
- 夹具模板：车床卡爪、铣床平口钳 → 整机仿真的 fixtures（工件坐标）；
- 起草（规则 / AI）、计算（先过免费 / 专业两档的门）、保存正式程序与工艺卡；
- 结果整理成界面要显示的检查清单与摘要。
"""

from __future__ import annotations

import re
from pathlib import Path

from analysis import cam
from analysis.cam import machines
from analysis.cam import tools as TL
from assist import cam_edition, cam_process

LEVEL_ORDER = {"error": 0, "warn": 1, "unknown": 2}
NUM = r"[-+]?\d+(?:\.\d+)?"


class StudyError(ValueError):
    pass


# ---------------- 输入 ----------------

def _nums(line: str) -> list[float]:
    return [float(x) for x in re.findall(NUM, line)]


def parse_segments(text: str) -> list[list[float]]:
    """“30x40, 40x60” 或一行一段 → [[直径, 长度], …]（从左到右）"""
    out = []
    for piece in re.split(r"[,，;；\n]+", text or ""):
        if not piece.strip():
            continue
        v = _nums(piece)
        if len(v) != 2:
            raise StudyError(f"“{piece.strip()}”要写成 直径x长度")
        out.append(v)
    if not out:
        raise StudyError("至少要一段 直径x长度")
    return out


def parse_rows(text: str, n: int, what: str) -> list[list[float]]:
    rows = []
    for line in (text or "").splitlines():
        if not line.strip():
            continue
        v = _nums(line)
        if len(v) != n:
            raise StudyError(f"{what}每行要 {n} 个数：“{line.strip()}”")
        rows.append(v)
    return rows


def turn_part(*, item: str, segments: str, chamfer: float = 0.0, grooves: str = "", threads: str = "", bore: str = "",
              machine: str = "EX-LATHE", kienzle: str | None = None) -> dict:
    """车削件文字输入 → turn 设置（不含切削参数）。
    grooves：每行“槽右边 z, 槽宽, 槽底直径”；threads：每行“z 起, z 止, 大径, 螺距”；bore：“直径x深度, …”（从孔口往里）"""
    part = {"mode": "turn", "machine": machine, "item": item, "segments": parse_segments(segments), "chamfer_mm": float(chamfer)}
    if kienzle:
        part["kienzle"] = kienzle
    g = parse_rows(grooves, 3, "槽")
    if g:
        part["grooves"] = [{"z": z, "width": w, "d": d} for z, w, d in g]
    t = parse_rows(threads, 4, "螺纹")
    if t:
        part["threads"] = [{"z_start": a, "z_end": b, "d": d, "pitch": p} for a, b, d, p in t]
    if (bore or "").strip():
        part["bore"] = {"segments": parse_segments(bore)}
    return part


def lathe_jaws(part: dict, jaw_len: float, jaw_d: float) -> list[dict]:
    """三爪卡盘的卡爪按圆柱算：夹住毛坯左端 jaw_len，外径 jaw_d；坐标同每次装夹（Z0 在右端面，毛坯左端在 −(全长 + 端面余量)）"""
    total = float(part["profile"][-1][0]) if part.get("profile") else sum(L for _, L in part["segments"])
    e = float(part.get("face_allow_mm", 1.0))
    z_left = -(total + e)
    return [{"id": "jaws", "name": "卡爪", "cylinder_mm": {"p0": [0, 0, z_left - 40.0], "p1": [0, 0, z_left + jaw_len], "r": jaw_d / 2}}]


def vise_jaws(stock: dict, grip: float, jaw_h: float = 40.0, jaw_t: float = 20.0) -> list[dict]:
    """平口钳两块钳口夹在毛坯 Y 向两侧，夹持高度 grip（从毛坯底面量），钳口高 jaw_h、厚 jaw_t；工件坐标（毛坯顶面 Z0）"""
    x0, y0, x1, y1 = stock["box"]
    zb = -float(stock["height"])
    top = zb + grip
    return [{"id": "jaw1", "name": "钳口", "box_mm": [x0 - 10, y0 - jaw_t, top - jaw_h, x1 + 10, y0, top]},
            {"id": "jaw2", "name": "钳口", "box_mm": [x0 - 10, y1, top - jaw_h, x1 + 10, y1 + jaw_t, top]}]


def iso_group(kienzle: str | None) -> str:
    if not kienzle:
        raise StudyError("先选工件材料（Kienzle 表中的材料行），才知道用刀具样本里哪一组切削参数")
    from analysis.cam import power

    r = power.row(kienzle)
    if r is None or not r.get("iso_group"):
        raise StudyError(f"材料行 {kienzle} 没有 ISO 材料组")
    return r["iso_group"]


# ---------------- 起草、计算、保存 ----------------

def draft(part: dict, *, client=None, tool_library: str | None = None, tool_lengths: dict | None = None, note: str = "") -> dict:
    if client is not None:
        cam_edition.gate(feature="ai")
    lib = TL.load(tool_library) if tool_library else TL.load()
    d = cam_process.draft(part, iso_group(part.get("kienzle")), lib, client, note=note, tool_lengths=tool_lengths)
    if tool_library:
        d["setup"].setdefault("machine_sim", {})["tool_library"] = tool_library
    return d


def run(setup: dict) -> dict:
    """先过两档的门，再算（analysis.cam.run）"""
    m = machines.model(setup["machine"])
    cam_edition.gate(setup, machine_model=m)
    r = cam.run(setup)
    if r["status"] != "ok":
        raise StudyError("；".join(r.get("messages") or ["计算失败"]))
    return r


def checks(result: dict) -> list[dict]:
    """各程序的检查合并去重，按严重程度排：[{level, text, program}]"""
    out, seen = [], set()
    for p in result["data"]["programs"]:
        for c in p["checks"]:
            if c["level"] not in LEVEL_ORDER or (c["level"], c["text"]) in seen:
                continue
            seen.add((c["level"], c["text"]))
            out.append({"level": c["level"], "text": c["text"], "program": p.get("title", "")})
    return sorted(out, key=lambda c: LEVEL_ORDER[c["level"]])


def summary(result: dict) -> list[str]:
    d = result["data"]
    lines = [f"{d['machine']['name']}：{len(d['programs'])} 个程序，合计 {d['total_time_s'] / 60:.1f} min"]
    for p in d["programs"]:
        ms = p.get("machine_sim")
        rel = p.get("release")
        sim_txt = {"pass": "通过", "unknown": "通过（有未知项）", "error": "不通过"}.get(ms["status"]) if ms else "没跑"
        lines.append(f"{p.get('title', '')}：{p['time']['total_s'] / 60:.1f} min，整机仿真{sim_txt}"
                     + (f"，指纹 {ms['fingerprint']}" if ms else "")
                     + ("，正式程序已出" if rel else "，没有正式程序"))
    return lines


def save(result: dict, out_dir, *, draft_doc: dict | None = None, lang: str = "zh", card: bool = True, pdf: bool = True) -> list[Path]:
    """保存正式程序（每次装夹一个 .nc）与工艺卡（Word，可转 PDF）。没有正式程序的不存；工艺卡是专业版功能"""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    files = []
    for p in result["data"]["programs"]:
        rel = p.get("release")
        if not rel:
            continue
        f = out / f"O{int(p.get('number', 1)):04d}_{rel['controller']}.nc"
        f.write_text(rel["text"], encoding="utf-8")
        files.append(f)
    if not files:
        raise StudyError("没有可以保存的正式程序（整机仿真没跑、没通过，或没选数控系统）")
    if card and draft_doc is not None:
        cam_edition.gate(feature="card")
        from assist import cam_card

        name = "工艺卡与程序单.docx" if lang == "zh" else "process-card.docx"
        o = cam_card.build_docx(draft_doc, result, out / name, lang=lang)
        files += [o["docx"], o["ledger"]]
        if pdf:
            from assist.fea_report import to_pdf

            p = to_pdf(o["docx"])
            if p:
                files.append(p)
    return files
