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


def boxes(holder: dict) -> tuple[list[list[float]], list[str]]:
    """刀具库里的 holder（iso5608、f_mm）→ 刀尖坐标系里的长方体 [[x0, y0, z0, x1, y1, z1], …] 与说明（查不了的部分）"""
    p = parse(holder["iso5608"])
    notes = []
    f = holder.get("f_mm")
    if f is None:
        return [], [f"刀杆 {p['code']} 没写刀尖偏距 f（厂家样本里查），刀杆没查"]
    f, b, h, l1, head = float(f), p["b_mm"], p["h_mm"], p["l1_mm"], p["edge_mm"]
    if p["hand"] == "R":
        z0, z1 = f - b, f
    elif p["hand"] == "L":
        z0, z1 = -f, -(f - b)
    else:
        z0, z1 = -b / 2, b / 2
    notes.append(f"刀杆 {p['code']}：离刀尖 {head:g} mm 以内的刀头外形各家不同，没查")
    return [[head, -h, z0, l1, 0.0, z1]], notes
