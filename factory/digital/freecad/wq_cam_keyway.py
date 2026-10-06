# -*- coding: utf-8 -*-
"""问渠数字工厂 · 键槽铣削 G 代码（CAM 后处理）

输出轴的平键槽在键槽铣床 KEY-01 上用 Ø(键宽) 立铣刀加工：沿槽中心线往复，每层下刀 1 mm，
斜线下刀避免端刃直插。坐标系：X 沿轴线（从轴左端面算起），Y 横向，Z 竖直，Z0 为键槽所在轴段的最高母线。
纯 Python，不依赖 FreeCAD；FreeCAD 的 CAM 工作台也可以生成同样的刀路，这里为了在任何电脑上都能跑
（包括自动测试），用最直接的算法写出来，便于学生读懂每一行。
"""
import math

TOOL_CHANGE = "T1 M06"


def layout_z(segments, idx):
    z = 0.0
    for i, (d, length) in enumerate(segments):
        if i == idx:
            return z, z + length, d
        z += length
    raise ValueError("键槽所在轴段编号超出范围")


def generate(params, rpm=1200, feed=80.0, plunge=40.0, step_down=1.0, safe_z=5.0, item="SH-301", revision=1):
    """返回 (G 代码文本, 信息 dict)。"""
    kw = params["keyway"]
    if not kw:
        raise ValueError("该轴没有键槽")
    z0, z1, d = layout_z(params["segments"], kw["segment"])
    b, t, length = float(kw["b"]), float(kw["t"]), float(kw["L"])
    zc = (z0 + z1) / 2
    xa, xb = zc - (length - b) / 2, zc + (length - b) / 2      # 刀心走的两端
    layers = max(1, math.ceil(t / step_down))
    lines = [
        "%",
        "(WQ {} rev {} 铣键槽 Keyway milling)".format(item, revision),
        "(键宽 {:g} 槽深 {:g} 槽长 {:g} 轴段 Ø{:g}，刀具 Ø{:g} 立铣刀)".format(b, t, length, d, b),
        "G21 G90 G17 G94",
        TOOL_CHANGE,
        "S{} M03".format(rpm),
        "G00 X{:.3f} Y0.000 Z{:.3f}".format(xa, safe_z),
        "G00 Z1.000",
    ]
    cut_len = 0.0
    x = xa
    for i in range(1, layers + 1):
        depth = -min(t, i * step_down)
        other = xb if x == xa else xa
        # 斜线下刀：边走边下到本层深度
        lines.append("G01 X{:.3f} Z{:.3f} F{:.0f}".format(other, depth, plunge))
        cut_len += math.hypot(other - x, step_down)
        x = other
        other = xb if x == xa else xa
        lines.append("G01 X{:.3f} F{:.0f}".format(other, feed))
        cut_len += abs(other - x)
        x = other
    lines += ["G00 Z{:.3f}".format(safe_z), "M05", "G00 X0.000 Y0.000", "M30", "%"]
    est_s = cut_len / feed * 60 * 1.0 + 20          # 切削时间 + 换刀、快移约 20 秒
    info = {"layers": layers, "cut_length_mm": round(cut_len, 1), "est_time_s": round(est_s),
            "tools": [{"tool": "T1", "type": "立铣刀 End mill", "diameter_mm": b}],
            "slot": {"x_from": xa - b / 2, "x_to": xb + b / 2, "width": b, "depth": t, "shaft_d": d}}
    return "\n".join(lines) + "\n", info


def parse(gcode):
    """把 G 代码解析成刀位点 [(x, y, z, 是否快移)]（3D 车间回放刀路用同样的规则）。"""
    pos = {"X": 0.0, "Y": 0.0, "Z": 0.0}
    pts = []
    for raw in gcode.splitlines():
        line = raw.split("(")[0].strip().upper()
        if not line or line == "%":
            continue
        words = line.split()
        g = next((w for w in words if w in ("G00", "G01", "G0", "G1")), None)
        if g is None:
            continue
        for w in words:
            if w[0] in pos:
                pos[w[0]] = float(w[1:])
        pts.append((pos["X"], pos["Y"], pos["Z"], g in ("G00", "G0")))
    return pts
