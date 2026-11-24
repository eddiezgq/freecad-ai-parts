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

import itertools
import math
import re

# ISO 5608 全长字母 → l1（mm）；X 为特殊长度
LENGTH = {"A": 32, "B": 40, "C": 50, "D": 60, "E": 70, "F": 80, "G": 90, "H": 100, "J": 110, "K": 125, "L": 140,
          "M": 150, "N": 160, "P": 170, "Q": 180, "R": 200, "S": 250, "T": 300, "U": 350, "V": 400, "W": 450, "Y": 500}

# 外圆车刀的主偏角 κ（刀杆形式，沿 Z 走刀量的那几种）与刀片刀尖角 ε（刀片形状）：泰珂洛综合样本 2020–2021 外圆车削 C004
# 的“刀杆形式”“刀片形状”两张图（ADR-0106 C4a）。端面走刀量角的形式（C、F、K、U、X、Y 等）和没标角度的不收，查不了就 unknown
KAPPA_DEG = {"A": 90.0, "B": 75.0, "D": 45.0, "G": 91.0, "H": 100.0, "I": 76.5, "J": 93.0, "L": 95.0, "N": 63.0,
             "S": 45.0, "V": 72.5}
EPSILON_DEG = {"C": 80.0, "D": 55.0, "K": 55.0, "S": 90.0, "T": 60.0, "V": 35.0}


def turn_angles(holder_code: str, insert_iso: str) -> tuple[float, float] | None:
    """ISO 5608 刀杆代号 + ISO 1832 刀片代号 → (主偏角 κ, 副偏角 κ′ = 180 − κ − ε)（度）；查不到返回 None"""
    try:
        h = parse(holder_code)
    except HolderError:
        return None
    shape = (insert_iso or "").strip().upper()[:1]
    if h["style"] not in KAPPA_DEG or shape not in EPSILON_DEG or (h["insert_shape"] and h["insert_shape"] != shape):
        return None
    k = KAPPA_DEG[h["style"]]
    return k, 180.0 - k - EPSILON_DEG[shape]


def profile_slopes(profile) -> tuple[float, float]:
    """外圆车削轮廓 [(z, d), …]（从右往左，Z 递减）→ (最陡的往上台阶斜角, 最陡的往下斜角)（度，从 −Z 方向量，90 = 直角台阶）；没有就 0"""
    up = down = 0.0
    for (z0, d0), (z1, d1) in itertools.pairwise(profile):
        dz, dr = z0 - z1, (d1 - d0) / 2.0
        if dz < -1e-9 or (abs(dz) < 1e-9 and abs(dr) < 1e-9):
            continue
        ang = math.degrees(math.atan2(abs(dr), dz))
        if dr > 1e-9:
            up = max(up, ang)
        elif dr < -1e-9:
            down = max(down, ang)
    return up, down


CLEAR_DEG = 2.0                                                    # 副切削刃与下坡之间留的间隙


def angle_issues(kappa: float, kappa2: float, up: float, down: float, beta: float = 0.0) -> list[str]:
    """B 转 β（正 = 主偏角变大）后：往上台阶 > κ + β 车不出，往下斜角 > κ′ − β − 间隙 副切削刃啃工件"""
    out = []
    k, k2 = kappa + beta, kappa2 - beta
    if up > k + 1e-6:
        out.append(f"台阶斜角 {up:.1f}° 比主偏角 {k:g}° 陡，车不出")
    if down > k2 - CLEAR_DEG + 1e-6:
        out.append(f"往下斜角 {down:.1f}° 超过副偏角 {k2:g}° 减 {CLEAR_DEG:g}° 间隙，副切削刃会啃工件")
    return out


def pick_beta(kappa: float, kappa2: float, up: float, down: float, lo: float = -90.0, hi: float = 90.0) -> int | None:
    """B 轴车削（ADR-0106 C4a）：挑一个让台阶、下坡都车得到的整数 β（绝对值最小的）；挑不到 None"""
    a = math.ceil(up - kappa - 1e-9)
    b = math.floor(kappa2 - CLEAR_DEG - down + 1e-9)
    a, b = max(a, math.ceil(lo)), min(b, math.floor(hi))
    if a > b:
        return None
    return 0 if a <= 0 <= b else (a if a > 0 else b)


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
    if holder.get("vendor_code") and holder.get("h_mm") and holder.get("b_mm") and not holder.get("bar_d_mm"):
        return _square_vendor_boxes(holder)                      # 厂家代号的方柄刀杆（切槽刀杆，ADR-0118）
    if holder.get("iso6261") or holder.get("vendor_code"):
        if holder.get("iso6261"):
            p6 = parse6261(holder["iso6261"])
        else:                                                    # 厂家代号（ADR-0115）：杆径、全长、刀头长照刀杆库
            p6 = {"code": holder["vendor_code"], "bar_d_mm": holder.get("bar_d_mm"), "edge_mm": holder.get("head_mm") or 0.0,
                  "length_letter": None}
        f, bd = holder.get("f_mm"), float(holder.get("bar_d_mm") or p6["bar_d_mm"])
        if f is None:
            return [], [f"镗杆 {p6['code']} 没写刀尖到杆轴线的距离 f，镗杆没查"]
        head = float(holder.get("head_mm") or p6["edge_mm"])
        l1 = holder.get("l1_mm") or LENGTH.get(p6["length_letter"] or "")
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


def vendor_hand(code: str) -> str | None:
    """厂家代号里的左右手：前三个字母后面的 R / L（京瓷 KGMR2525M-3 → R）；读不出返回 None"""
    m = re.match(r"^[A-Z]{3}([RL])", (code or "").strip().upper())
    return m.group(1) if m else None


def _square_vendor_boxes(holder: dict) -> tuple[list[list[float]], list[str]]:
    """方柄刀杆（厂家代号，ADR-0118）：同外圆刀杆，刀杆高 h、宽 b、全长 l1 照刀杆库，从刀头 LH 到全长；刀头一段报“未知”"""
    code = holder["vendor_code"]
    f = holder.get("f_mm")
    if f is None:
        return [], [f"刀杆 {code} 没写刀尖偏距 f（厂家样本里查），刀杆没查"]
    if holder.get("l1_mm") is None:
        return [], [f"刀杆 {code} 没写全长，刀杆没查"]
    f, b, h, l1 = float(f), float(holder["b_mm"]), float(holder["h_mm"]), float(holder["l1_mm"])
    head = float(holder.get("head_mm") or 0.0)
    hand = vendor_hand(code)
    if hand == "R":
        z0, z1 = f - b, f
    elif hand == "L":
        z0, z1 = -f, -(f - b)
    else:
        z0, z1 = -b / 2, b / 2
    return ([[head, -h, z0, l1, 0.0, z1]],
            [f"刀杆 {code}：离刀尖 {head:g} mm 以内的刀头外形各家不同，没查（切槽深度按刀杆最大槽深另查）"])


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
             if h.get("use") == use and h.get("iso5608" if use == "external" else "iso6261")
             and key[0] in h["insert"].get("codes", []) and h["insert"].get("size") == key[1] and code(h)[4] == hand
             and (use == "external" or h["min_bore_mm"] <= bore_d + 1e-9)]
    if not cands:
        return None
    if use == "internal":
        return min(cands, key=lambda h: (-h["bar_d_mm"], code(h)[2] != want, h["id"]))
    return min(cands, key=lambda h: (code(h)[2] != want, abs(h.get("h_mm", 25) - 25) + abs(h.get("b_mm", 25) - 25), h["id"]))


def groove_reach(h: dict, edges: int | None) -> float | None:
    """刀杆能切的深度（ADR-0118、0119）：两刃刀片、或刃数不知道时，刀杆另注了两刃最大切深就按它；否则按最大槽深 CDX"""
    two = h.get("max_depth_two_edge_mm")
    if two is not None and edges != 1:
        return float(two)
    return None if h.get("max_depth_mm") is None else float(h["max_depth_mm"])


def pick_groove(width: float, depth: float | None = None, hand: str = "R", cats: list[dict] | None = None,
                ref: str | None = None, code: str | None = None, edges: int | None = None) -> dict | None:
    """切槽刀、切断刀配切槽刀杆（ADR-0118、0119）：刀片刃宽在刀杆的 CW 范围内、手向对上、能切的深度不小于要切的（给了的话；
    两刃刀片按两刃最大切深）；切槽刀片的刀座各家不通用，给了 ref（刀片的样本来源）就只挑同一家样本的刀杆；
    刀杆写了能装的刀片系列、又给了刀片代号 code，代号要以其中之一开头（京瓷 KGM 装 GM…、KGD 装 GD…）；
    截面优先 25×25，再取最大槽深小的（刀头短、刚性好），再按代号排序。没有对得上的返回 None"""
    def ok(h):
        rng = h["insert"]["groove_width_mm"]
        if not (rng["min"] - 1e-9 <= width <= rng["max"] + 1e-9) or vendor_hand(h["vendor_code"]) != hand:
            return False
        if ref is not None and (h.get("source") or {}).get("ref") != ref:
            return False
        ser = h["insert"].get("series")
        if ser and code and not any(code.upper().startswith(x) for x in ser):
            return False
        reach = groove_reach(h, edges)
        return depth is None or (reach is not None and reach >= depth - 1e-9)

    cands = [h for c in (catalogs() if cats is None else cats) for h in c["holders"] if h.get("use") == "groove" and ok(h)]
    if not cands:
        return None
    return min(cands, key=lambda h: (abs(h["h_mm"] - 25) + abs(h["b_mm"] - 25), h["max_depth_mm"], h["id"]))


def as_tool_holder(h: dict) -> dict:
    """刀杆库的一条 → 刀具的 holder（cam-tool/1）"""
    if h.get("use") == "groove":
        return {"id": h["id"], "vendor_code": h["vendor_code"], "f_mm": h["f_mm"], "h_mm": h["h_mm"], "b_mm": h["b_mm"],
                "l1_mm": h["l1_mm"], "max_depth_mm": h["max_depth_mm"], **({"head_mm": h["head_mm"]} if "head_mm" in h else {}),
                **({"max_depth_two_edge_mm": h["max_depth_two_edge_mm"]} if "max_depth_two_edge_mm" in h else {})}
    if h.get("use") == "internal" and h.get("vendor_code"):
        return {"id": h["id"], "vendor_code": h["vendor_code"], "f_mm": h["f_mm"], "bar_d_mm": h["bar_d_mm"], "l1_mm": h["l1_mm"],
                "min_bore_mm": h["min_bore_mm"], **({"head_mm": h["head_mm"]} if "head_mm" in h else {})}
    if h.get("use") == "internal":
        return {"id": h["id"], "iso6261": h["iso6261"], "f_mm": h["f_mm"], "bar_d_mm": h["bar_d_mm"], "min_bore_mm": h["min_bore_mm"],
                **({"head_mm": h["head_mm"]} if "head_mm" in h else {})}
    return {"id": h["id"], "iso5608": h["iso5608"], "f_mm": h["f_mm"], **({"head_mm": h["head_mm"]} if "head_mm" in h else {})}


def thread_size(insert_iso: str) -> str | None:
    """平装螺纹刀片的尺寸位：16IR15ISO → "16"，06IR10ISO → "06"（ADR-0115）"""
    m = re.match(r"^(\d{2})[EI][RL]", (insert_iso or "").strip().upper())
    return m.group(1) if m else None


def pick_thread_bar(insert_iso: str, bore_d: float, cats: list[dict] | None = None) -> dict | None:
    """内螺纹刀片配螺纹镗杆（ADR-0115）：刀片尺寸位对上、手向对上（IR → 右手杆）、最小孔径 ≤ 孔径（小径），取杆最粗的"""
    ts = thread_size(insert_iso)
    if ts is None:
        return None
    hand = (insert_iso.strip().upper()[3] if len(insert_iso) > 3 else "R")
    cands = [h for c in (catalogs() if cats is None else cats) for h in c["holders"]
             if h.get("use") == "internal" and h["insert"].get("thread_size") == ts and h["min_bore_mm"] <= bore_d + 1e-9
             and _bar_hand(h) == hand]
    return min(cands, key=lambda h: (-h["bar_d_mm"], h["id"])) if cands else None


def _bar_hand(h: dict) -> str:
    code = h.get("vendor_code") or h.get("iso6261", "")
    m = re.match(r"^[A-Z]*?([RL])\d", code.split("-", 1)[1] if h.get("iso6261") else code)
    return m.group(1) if m else "R"
