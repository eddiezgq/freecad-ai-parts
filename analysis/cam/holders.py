"""车刀刀杆：ISO 5608 代号 → 刀杆外形（ADR-0106 Q2 第 3 步、ADR-0107）。

代号逐位（例 PCLNR 2525 M 12）：
1 夹紧方式  2 刀片形状  3 刀杆形式（主偏角）  4 刀片法后角  5 左右手（R / L / N）
6–7 刀杆高 h  8–9 刀杆宽 b（mm）  10 全长 l1 的字母（ISO 5608 长度表）  11–12 刀片切削刃长度（mm）
之后的字符是厂家自定的，不解析。

外形（车床坐标，刀尖为原点：X 沿半径向外，Z 沿主轴轴线，Y 为中心高方向）：
- 刀杆柄部是长方体：X 从“刀头长”到 l1，Y 从 −h 到 0（刀尖在刀杆顶面高度，h1 = h），
  Z 方向宽 b，位置由刀尖偏距 f（刀尖到刀杆远侧面）定：右手刀在刀尖的 +Z 一侧 [f − b, f]，左手刀镜像，N 居中。
- 刀头（离刀尖一个刀片刃长以内）形状各家不同，不画，报一条“刀头没查”。
- 没有 f（ISO 5608 不规定，厂家样本才有）就放不下刀杆，整个刀杆报“未知”。
"""

from __future__ import annotations

import re

# ISO 5608 全长字母 → l1（mm）；X 为特殊长度
LENGTH = {"A": 32, "B": 40, "C": 50, "D": 60, "E": 70, "F": 80, "G": 90, "H": 100, "J": 110, "K": 125, "L": 140,
          "M": 150, "N": 160, "P": 170, "Q": 180, "R": 200, "S": 250, "T": 300, "U": 350, "V": 400, "W": 450, "Y": 500}

_RE = re.compile(r"^([A-Z])([A-Z])([A-Z])([A-Z])([RLN])\s*(\d{2})(\d{2})\s*([A-Z])\s*(\d{2})(.*)$")


class HolderError(ValueError):
    pass


def parse(code: str) -> dict:
    m = _RE.match(code.strip().upper())
    if not m:
        raise HolderError(f"ISO 5608 刀杆代号看不懂：{code!r}（例：PCLNR 2525 M 12）")
    clamp, shape, style, clear, hand, h, b, ln, size, rest = m.groups()
    if ln not in LENGTH:
        raise HolderError(f"{code}：长度字母 {ln} 是特殊长度（X）或不在 ISO 5608 长度表里，要在刀具库里写明长度")
    return {"code": code.strip(), "clamp": clamp, "insert_shape": shape, "style": style, "clearance": clear, "hand": hand,
            "h_mm": float(h), "b_mm": float(b), "l1_mm": float(LENGTH[ln]), "edge_mm": float(size), "extra": rest.strip()}


_RE6261 = re.compile(r"^([A-Z])(\d{2})([A-Z])-([A-Z])([A-Z])([A-Z])([A-Z])([RLN])(\d{2})(.*)$")


def parse6261(code: str) -> dict:
    """ISO 6261 镗杆代号（例 A25R-PCLNR12）：1 杆的材料 / 内冷  2–3 杆径  4 全长字母（ISO 6261 与 5608 同一张长度表）  - 后：夹紧方式、刀片形状、
    刀杆形式、法后角、左右手、刀片刃长；之后厂家自定，不解析"""
    m = _RE6261.match(code.strip().upper())
    if not m:
        raise HolderError(f"ISO 6261 镗杆代号看不懂：{code!r}（例：A25R-PCLNR12）")
    kind, d, ln, clamp, shape, style, clear, hand, size, rest = m.groups()
    return {"code": code.strip(), "bar": kind, "bar_d_mm": float(d), "length_letter": ln, "clamp": clamp, "insert_shape": shape,
            "style": style, "clearance": clear, "hand": hand, "edge_mm": float(size), "extra": rest.strip()}


def boxes(holder: dict) -> tuple[list[list[float]], list[str]]:
    """刀具库里的 holder（iso5608、f_mm）→ 刀尖坐标系里的长方体 [[x0, y0, z0, x1, y1, z1], …] 与说明（查不了的部分）。
    镗杆（iso6261，ADR-0114）：圆杆沿 +Z 从刀头到全长，轴线在刀尖往里 f 处，按外接方柱查"""
    if holder.get("iso6261"):
        p6 = parse6261(holder["iso6261"])
        f, bd = holder.get("f_mm"), float(holder.get("bar_d_mm") or p6["bar_d_mm"])
        if f is None:
            return [], [f"镗杆 {p6['code']} 没写刀尖到杆轴线的距离 f，镗杆没查"]
        head = float(holder.get("head_mm") or p6["edge_mm"])
        l1 = holder.get("l1_mm") or LENGTH.get(p6["length_letter"])
        if l1 is None:
            return [], [f"镗杆 {p6['code']}：长度字母 {p6['length_letter']} 不在长度表里，镗杆没查"]
        r, f = bd / 2.0, float(f)
        return ([[-f - r, -r, head, -f + r, r, float(l1)]],
                [f"镗杆 {p6['code']}：离刀尖 {head:g} mm 以内的刀头外形各家不同，没查；圆杆按外接方柱查（偏保守）"])
    p = parse(holder["iso5608"])
    notes = []
    f = holder.get("f_mm")
    if f is None:
        return [], [f"刀杆 {p['code']} 没写刀尖偏距 f（厂家样本里查），刀杆没查"]
    f, b, h, l1 = float(f), p["b_mm"], p["h_mm"], p["l1_mm"]
    head = float(holder.get("head_mm") or p["edge_mm"])        # 刀头长：样本的 LH（ADR-0112），没写按刀片刃长
    if p["hand"] == "R":
        z0, z1 = f - b, f
    elif p["hand"] == "L":
        z0, z1 = -f, -(f - b)
    else:
        z0, z1 = -b / 2, b / 2
    notes.append(f"刀杆 {p['code']}：离刀尖 {head:g} mm 以内的刀头外形各家不同，没查")
    return [[head, -h, z0, l1, 0.0, z1]], notes


# ---------------------------------------------------------------- 刀杆库（cam-holder/1，ADR-0112）：起草时给车刀片配刀杆
STYLE = {"C": "L", "W": "L", "D": "J", "V": "J", "T": "G", "S": "B"}   # 刀片形状 → 首选刀杆形式（L 95°、J 93°、G 90°、B 75°）


def insert_key(iso: str) -> tuple[str, str] | None:
    """ISO 1832 刀片代号 → (前两位 形状 + 法后角, 尺寸位 刃长 2 位 + 厚度 2 位)：CNMG120408-TM → ("CN", "1204")"""
    m = re.match(r"^([A-Z]{2})[A-Z]{2}(\d{4})", (iso or "").strip().upper())
    return (m.group(1), m.group(2)) if m else None


def catalogs(root=None) -> list[dict]:
    """厂商刀杆库（analysis/cam/libraries/*.json 里 format = cam-holder/1 的）"""
    import json
    from pathlib import Path

    d = Path(root) if root else Path(__file__).resolve().parent / "libraries"
    out = []
    for f in sorted(d.glob("*.json")):
        try:
            j = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if j.get("format") == "cam-holder/1":
            out.append(j)
    return out


def pick(insert_iso: str, hand: str = "R", cats: list[dict] | None = None, bore_d: float | None = None) -> dict | None:
    """按刀片代号从刀杆库里挑刀杆：前两位、尺寸位都对上，手向对上。
    外圆（bore_d 不给）：按刀片形状挑刀杆形式（C、W → L，D、V → J，T → G，S → B），截面优先 25×25，再按代号排序。
    内孔（给孔径 bore_d，ADR-0114）：镗杆的最小孔径不大于孔径，取杆最粗的（刚性好），同样粗的按刀杆形式、代号排序。没有对得上的返回 None"""
    key = insert_key(insert_iso)
    if key is None:
        return None
    want = STYLE.get(key[0][0])
    use = "external" if bore_d is None else "internal"

    def code(h):
        return h["iso5608"] if use == "external" else h["iso6261"].split("-", 1)[1]

    cands = [h for c in (catalogs() if cats is None else cats) for h in c["holders"]
             if h.get("use") == use and key[0] in h["insert"]["codes"] and h["insert"]["size"] == key[1] and code(h)[4] == hand
             and (use == "external" or h["min_bore_mm"] <= bore_d + 1e-9)]
    if not cands:
        return None
    if use == "internal":
        return min(cands, key=lambda h: (-h["bar_d_mm"], code(h)[2] != want, h["id"]))
    return min(cands, key=lambda h: (code(h)[2] != want, abs(h.get("h_mm", 25) - 25) + abs(h.get("b_mm", 25) - 25), h["id"]))


def as_tool_holder(h: dict) -> dict:
    """刀杆库的一条 → 刀具的 holder（cam-tool/1）"""
    if h.get("use") == "internal":
        return {"id": h["id"], "iso6261": h["iso6261"], "f_mm": h["f_mm"], "bar_d_mm": h["bar_d_mm"], "min_bore_mm": h["min_bore_mm"],
                **({"head_mm": h["head_mm"]} if "head_mm" in h else {})}
    return {"id": h["id"], "iso5608": h["iso5608"], "f_mm": h["f_mm"], **({"head_mm": h["head_mm"]} if "head_mm" in h else {})}
