# -*- coding: utf-8 -*-
"""问渠数字工厂 · 阶梯轴零件图（SVG）

按参数画主视图（外形、各段直径与长度、键槽、倒角）和标题栏（物料、版本、设计者、日期）。
纯 Python，不依赖 FreeCAD 的 TechDraw，发布宏和自动测试都能用；以后可换成 TechDraw 导出的 PDF。
"""
import datetime as dt
from xml.sax.saxutils import escape


def svg(params, item="SH-301", title="输出轴 Output shaft", revision=1, author="", material="45 钢 调质"):
    segs = params["segments"]
    total = sum(length for _, length in segs)
    dmax = max(d for d, _ in segs)
    s = 3.0                                # 比例：1 mm → 3 px
    W, H = 900, 520
    x0 = (W - total * s) / 2
    yc = 190
    out = ['<svg xmlns="http://www.w3.org/2000/svg" width="{}" height="{}" viewBox="0 0 {} {}" '
           'font-family="Noto Sans SC, sans-serif" font-size="12">'.format(W, H, W, H),
           '<rect x="5" y="5" width="{}" height="{}" fill="#fff" stroke="#000" stroke-width="1.5"/>'.format(W - 10, H - 10)]
    # 中心线
    out.append('<line x1="{:.1f}" y1="{}" x2="{:.1f}" y2="{}" stroke="#000" stroke-dasharray="12 3 2 3" stroke-width="0.6"/>'.format(
        x0 - 15, yc, x0 + total * s + 15, yc))
    z = 0.0
    for i, (d, length) in enumerate(segs):
        xa, xb = x0 + z * s, x0 + (z + length) * s
        r = d / 2 * s
        out.append('<rect x="{:.1f}" y="{:.1f}" width="{:.1f}" height="{:.1f}" fill="none" stroke="#000" stroke-width="1.4"/>'.format(
            xa, yc - r, xb - xa, 2 * r))
        # 直径标注
        out.append('<text x="{:.1f}" y="{:.1f}" text-anchor="middle">Ø{:g}</text>'.format((xa + xb) / 2, yc + 4, d))
        # 长度标注（下方）
        yd = yc + dmax / 2 * s + 30
        out.append('<line x1="{:.1f}" y1="{:.1f}" x2="{:.1f}" y2="{:.1f}" stroke="#000" stroke-width="0.6" '
                   'marker-start="url(#a)" marker-end="url(#a)"/>'.format(xa, yd, xb, yd))
        out.append('<text x="{:.1f}" y="{:.1f}" text-anchor="middle">{:g}</text>'.format((xa + xb) / 2, yd - 4, length))
        z += length
    # 总长
    yd = yc + dmax / 2 * s + 60
    out.append('<line x1="{:.1f}" y1="{:.1f}" x2="{:.1f}" y2="{:.1f}" stroke="#000" stroke-width="0.6"/>'.format(x0, yd, x0 + total * s, yd))
    out.append('<text x="{:.1f}" y="{:.1f}" text-anchor="middle">总长 {:g}</text>'.format(x0 + total * s / 2, yd - 4, total))
    kw = params.get("keyway")
    if kw:
        z = sum(length for _, length in segs[:kw["segment"]])
        d, length = segs[kw["segment"]]
        zc = z + length / 2
        xa, xb = x0 + (zc - kw["L"] / 2) * s, x0 + (zc + kw["L"] / 2) * s
        top = yc - d / 2 * s
        out.append('<rect x="{:.1f}" y="{:.1f}" width="{:.1f}" height="{:.1f}" rx="{:.1f}" fill="#ddd" stroke="#000" stroke-width="1"/>'.format(
            xa, top, xb - xa, kw["t"] * s, min(kw["t"] * s, kw["b"] * s / 2) / 2))
        out.append('<text x="{:.1f}" y="{:.1f}" text-anchor="middle">键槽 {:g}×{:g} 深 {:g}（GB/T 1095）</text>'.format(
            (xa + xb) / 2, top - 10, kw["L"], kw["b"], kw["t"]))
    out.append('<defs><marker id="a" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">'
               '<path d="M0 2 L10 5 L0 8 z"/></marker></defs>')
    out.append('<text x="30" y="40" font-size="13">技术要求：1. 调质 217–255 HB；2. 轴承位 Ø35 k6、齿轮位 Ø40 k6 磨削，Ra 0.8；'
               '3. 未注倒角 C{:g}。</text>'.format(params.get("chamfer", 1)))
    # 标题栏
    bx, by, bw, bh = W - 420, H - 110, 410, 100
    out.append('<rect x="{}" y="{}" width="{}" height="{}" fill="none" stroke="#000" stroke-width="1.2"/>'.format(bx, by, bw, bh))
    rows = [("名称", title), ("物料", item), ("版本", "rev {}".format(revision)), ("材料", material),
            ("设计", author or "—"), ("日期", dt.date.today().isoformat()), ("单位", "问渠减速器厂"), ("比例", "1:1（图面缩放）")]
    for i, (k, v) in enumerate(rows):
        cx, cy = bx + (i % 2) * bw / 2, by + (i // 2) * bh / 4
        out.append('<rect x="{:.0f}" y="{:.0f}" width="{:.0f}" height="{:.0f}" fill="none" stroke="#000" stroke-width="0.5"/>'.format(
            cx, cy, bw / 2, bh / 4))
        out.append('<text x="{:.0f}" y="{:.0f}">{}：{}</text>'.format(cx + 6, cy + 17, escape(k), escape(str(v))))
    out.append("</svg>")
    return "\n".join(out)
