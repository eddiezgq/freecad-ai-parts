# -*- coding: utf-8 -*-
"""平缝机控制器 CTRL-LS 的布局（第 159 轮 159d2b）：分区 + 大件定位 + 其余按功能块排，结果写进设计描述 board.placement。

    python3 ctrl_ls_place.py          # 算布局、写回 ../ctrl-ls/design.yaml 的 board.placement（只改这一段）

做法：板子分成几个区（交流输入、校正、辅助电源、逆变、执行器、主控、隔离面板口），散热器边（上边）一排放整流桥、升压管、
升压二极管、功率模块（159c：电控箱顶板当散热器）；接插件靠板边；其余器件在自己功能块的区里按位号顺序一行一行排（行内按外框宽度，
互不重叠、留 1.2 mm 间隙）。写回后人可以在 KiCad 里挪，再用 wqeda.readback 读回设计描述。示例设计，未经硬件验证。"""
from __future__ import annotations

import os
import re
import sys

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ctrl_ls as D  # noqa: E402

FPDIR = "/usr/share/kicad/footprints"
LOCAL = os.path.join(os.path.dirname(HERE), "libs")
W, H = D.X["board_mm"]
GAP = 1.2
# 高压功能块里器件之间多留：高压线布线间距 2.2–2.6 mm、线宽 2–2.5 mm，器件挨得太紧线穿不过去（159d2b 第七次布线 71 处没连上）
GAP_HV = {"mains": 3.5, "pfc": 3.0, "aux": 2.5}
EDGE = 1.0
# 带高压网络（safety.yaml 的相线、零线、母线组）的器件和不带的器件之间至少隔这么多：
# 安全距离“母线 ↔ 弱电”要 2.0 mm，焊盘贴着外框，两边器件挨着放时焊盘之间就不够（159d2b 第十二次：分压电阻 ↔ 接地电阻 1.75 mm）
GAP_HV_LOW = 2.6

# 区：功能块 → [(x0, y0, x1, y1)]（可以几块）
REGIONS = {
    "mains": [(EDGE, 24, 66, 51), (45, 52, 66, 75)],
    "aux": [(41, 77, 66, H - EDGE), (EDGE, 115, 41, H - EDGE), (110, 138, 150, H - EDGE), (13, 129, 41, H - EDGE)],
    "pfc": [(66, 9, 150, 33), (66, 112, 150, 124)],
    "servo": [(150, 30.5, 236, 37.5), (150, 70, W - EDGE, 84)],
    "act": [(150, 86, W - EDGE, 118), (150, 120, 208, 136)],
    "comm": [(215, 119, W - EDGE, H - 10)],
    "io": [(66, 126, 150, 138), (66, 112, 150, 124)],
}
# 跨隔离带的器件按引脚位置定（器件原点位置 x, y 和角度）：数字隔离器两排脚分在带两边；隔离电源 2、3 脚之间是带的收窄处
B = D.BARRIER
FIXED_POS = {"U601": (B["x"], 124.0, 0), "U602": (B["x"] - 3.81, 132.0, 0), "C601": (B["x"] - 6.5, 120.5, 90),
             "C603": (B["x"] - 9.0, 128.0, 90),
             # 自举电容紧贴功率模块控制脚（模块转 180° 后控制脚一排在 y ≈ 28）：1 脚 VB 对着 VBOOT 脚、2 脚对着 OUT 脚
             "C401": (194.94, 32.0, 0), "C402": (180.69, 32.0, 0), "C403": (166.44, 32.0, 0),
             "C405": (188.6, 32.0, 0), "C404": (188.6, 35.6, 0),
             # 校正的采样电阻放在整流桥负端旁边，离开整流后的高压（旁路二极管）
             "R203": (91.0, 12.0, 90),
             # 升压管栅极电阻紧挨栅极脚（第十九次：按顺序排到了 42 mm 外，栅极回路太长，这根也没布通）
             "R201": (96.78, 9.5, 90),
             # 钳位电阻两只串联排成一行，焊盘下各有一块散热铜（设计描述 board.pours，159d2c 报告热分析查出 R310 板温超）
             "R303": (10.0, 124.0, 0), "R310": (22.0, 124.0, 0),
             # 欠压检测的两只二极管从整流桥交流脚取电，放在整流桥下面（159d2c：排到了 110 mm 外，交流线横穿半块板，零线没布通）；
             # 两只同向（极性元件方向统一，工艺检查 F7）：零线那只在左，相线那只在右
             "D204": (75.0, 19.0, 0), "D203": (82.5, 19.0, 0),
             # 步进驱动和它的电荷泵电容放在一起（159d2c：电容排到了 22 mm 外，没布通）；驱动放在步进电机插座 J502 上方
             # （原来在隔离带另一侧，输出线绕过隔离带拐角布不通）
             "U501": (196.0, 128.0, 0), "C501": (190.07, 128.32, 90),
             # 功率模块下桥采样电阻放在模块右边、电机端子左边的空地（159d2c：排到了 70 mm 外，N_U 没布通）
             "R411": (205.0, 25.0, 0), "R412": (215.0, 25.0, 0), "R413": (225.0, 25.0, 0),
             "R414": (205.0, 20.5, 0), "R415": (215.0, 20.5, 0), "R416": (225.0, 20.5, 0)}
# 散热铜占的地方（别的器件不放进来）
RESERVE = [(4.5, 121.0, 28.0, 127.0)]
# 大件、板边件：外框左上角 (x, y) 和角度
FIXED = {
    # 散热器边（上边）：整流桥、升压管、升压二极管、功率模块的散热面朝上边
    "BR101": (68, EDGE, 0), "C104": (68, 8, 0), "Q201": (94, EDGE, 0), "D201": (114, EDGE, 0), "U401": (152, EDGE, 180),
    "J101": (EDGE, 2, 90), "F101": (14, 2, 0), "J401": (W - 12.5, 4, 90),
    "L101": (EDGE, 53, 0), "K101": (EDGE + 44, 2, 0),
    "L201": (68, 34, 0), "C221": (151, 38.5, 0), "C222": (183, 38.5, 0), "C223": (W - 33, 38.5, 0),
    # Y 电容分开放（一只接相线、一只接零线，两只的保护地脚之外隔开 4 mm 以上）
    "C102": (16, 22, 90), "C103": (16, 38, 90),
    "T301": (EDGE + 1, 77, 0),
    "J501": (152, H - 10.5, 0), "J502": (190, H - 8, 0), "J601": (W - 34, H - 8, 0),
    "J701": (70, H - 8, 0), "J702": (97, H - 8, 0), "U10": (114, 127, 0),
}


def load(fpid):
    lib, name = fpid.split(":", 1)
    d = os.path.join(LOCAL if lib == "wq" else FPDIR, lib + ".pretty")
    f = pcbnew.FootprintLoad(d, name)
    if f is None:
        raise KeyError(fpid)
    return f


def bbox(fpid, rot):
    """器件在原点、转 rot 度时的外框（含丝印与安装面，mm）：(左, 上, 宽, 高)"""
    f = load(fpid)
    f.SetOrientationDegrees(rot)
    b = f.GetBoundingBox(False, False)
    mm = pcbnew.ToMM
    return mm(b.GetX()), mm(b.GetY()), mm(b.GetWidth()), mm(b.GetHeight())


def overlaps(a, b):
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def hv_nets():
    import yaml
    with open(os.path.join(os.path.dirname(D.DESIGN_PATH), "safety.yaml"), encoding="utf-8") as f:
        g = yaml.safe_load(f)["groups"]
    return set(g["ac_l"]) | set(g["ac_n"]) | set(g["bus_hv"])


def main():
    hv = hv_nets()
    is_hv = {p["ref"]: bool(set(p["pins"].values()) & hv) for p in D.PARTS}
    place, used = {}, [(hx - 8, hy - 8, hx + 8, hy + 8, None) for hx, hy in D.X["holes"]]   # 安装孔周围留空（孔焊盘 + 4 mm）
    bw = B["w"] / 2 + 1.0                                                                       # 隔离带两边再各留 1 mm
    used += [(B["x"] - bw, B["y"] - bw, B["x"] + bw, H, None), (B["x"] - bw, B["y"] - bw, W, B["y"] + bw, None)]
    used += [r + (True,) for r in RESERVE]   # 散热铜是高压网络（母线、钳位）
    parts = {p["ref"]: p for p in D.PARTS}
    for ref, (x, y, rot) in FIXED_POS.items():
        bx, by, bw_, bh = bbox(parts[ref]["fp"], rot)
        place[ref] = (round(x, 2), round(y, 2), rot, "F")
        used.append((x + bx, y + by, x + bx + bw_, y + by + bh, is_hv[ref]))
    for ref, (x, y, rot) in FIXED.items():
        bx, by, bw, bh = bbox(parts[ref]["fp"], rot)
        place[ref] = (round(x - bx, 2), round(y - by, 2), rot, "F")
        used.append((x, y, x + bw, y + bh, is_hv[ref]))
    # 底面 ICT 测试点（159e）不在这里排：ctrl_ls_build.py --testpoints 按布好的线找空地放，位置照 design.yaml 原样保留
    rule = D.DOC["circuit"].get("ict_test_points") or {}
    ict = {p["ref"] for p in D.PARTS if p["ref"].startswith("TP") and p["note"] == rule.get("note")}
    place.update({r: D.X["placement"][r] for r in ict if r in D.X["placement"]})
    order = {k: [p for p in D.PARTS if p["sheet"] == k and p["ref"] not in FIXED and p["ref"] not in FIXED_POS and p["ref"] not in ict]
             for k in REGIONS}
    left = []
    global GAP
    for k, plist in order.items():
        GAP = GAP_HV.get(k, 1.2)
        queue = list(plist)
        for (x0, y0, x1, y1) in REGIONS[k]:
            cx, cy, rowh = x0, y0, 0.0
            rest = []
            for p in queue:
                bx, by, bw, bh = bbox(p["fp"], 0)
                ok = False
                while cy + bh <= y1:
                    if cx + bw > x1:
                        cx, cy, rowh = x0, cy + rowh + GAP, 0.0
                        continue
                    r = (cx, cy, cx + bw, cy + bh)
                    hit = next((u for u in used if overlaps(r, _grow(u, _gap(is_hv[p["ref"]], u[4])))), None)
                    if hit:
                        cx = hit[2] + _gap(is_hv[p["ref"]], hit[4])
                        continue
                    ok = True
                    break
                if not ok:
                    rest.append(p)
                    continue
                place[p["ref"]] = (round(cx - bx, 2), round(cy - by, 2), 0, "F")
                used.append(r + (is_hv[p["ref"]],))
                cx += bw + GAP
                rowh = max(rowh, bh)
            queue = rest
        left += [p["ref"] for p in queue]
    if left:
        raise SystemExit("放不下：" + " ".join(left))
    write(place)
    print("摆好 {} 个器件，写回 design.yaml".format(len(place)))


def _gap(a, b):
    """两个器件之间留多少：一个带高压、一个不带时至少 GAP_HV_LOW；其余按所在区的间隙"""
    return max(GAP, GAP_HV_LOW) if (a is not None and b is not None and a != b) else GAP


def _grow(u, g):
    return (u[0] - g, u[1] - g, u[2] + g, u[3] + g)


def write(place):
    """只改 design.yaml 的 board.placement 段（其余原样，注释也在）"""
    path = D.DESIGN_PATH
    with open(path, encoding="utf-8") as f:
        txt = f.read()
    body = "  placement:\n" + "".join(
        "    {}: [{:g}, {:g}, {:g}, {}]\n".format(ref, x, y, r, s) for ref, (x, y, r, s) in sorted(place.items(), key=lambda kv: _key(kv[0])))
    if re.search(r"(?m)^  placement:\n", txt):
        txt = re.sub(r"(?ms)^  placement:\n(?:    .*\n)*", body, txt)
    else:
        txt = txt.rstrip("\n") + "\n" + body
    with open(path, "w", encoding="utf-8") as f:
        f.write(txt)


def _key(r):
    m = re.match(r"([A-Z]+)(\d+)", r)
    return (m.group(1), int(m.group(2))) if m else (r, 0)


if __name__ == "__main__":
    main()
