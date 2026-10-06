# -*- coding: utf-8 -*-
"""由 data.py 生成《工厂设计.md》的表格部分，保证文档和导入的数据一致。运行：py -m factory.make_docs"""
import os

from factory import data as D

OUT = os.path.join(os.path.dirname(__file__), "..", "工厂设计.md")
KIND_CN = {"raw": "原材料", "buy": "外购件", "make": "自制零件", "sub": "部件", "fg": "成品"}


def std_cost():
    rate = {c: v[3] for c, v in D.ITEMS.items() if v[3]}
    per_min = {ws: sum(c) / 60 for ws, (_, c) in D.WORKSTATIONS.items()}
    res = {}

    def cost(code):
        if code in rate:
            return rate[code]
        if code in res:
            return res[code][0]
        routing, lines = D.BOMS[code]
        mat = sum(cost(c) * q for c, q in lines)
        op = sum(per_min[D.OPERATIONS[o]] * m for o, m in D.ROUTINGS[routing])
        mins = sum(m for _, m in D.ROUTINGS[routing])
        res[code] = (mat + op, mat, op, mins)
        return mat + op

    for code in D.BOMS:
        cost(code)
    return res


def workstation_load():
    """每台 WQR-105 在各工作中心的分钟数（按 BOM 用量展开），及单班日产能。"""
    load = {ws: 0.0 for ws in D.WORKSTATIONS}

    def walk(code, qty):
        if code not in D.BOMS:
            return
        routing, lines = D.BOMS[code]
        for op, mins in D.ROUTINGS[routing]:
            load[D.OPERATIONS[op]] += mins * qty
        for c, q in lines:
            walk(c, qty * q)

    walk("WQR-105", 1)
    rows = []
    for ws, mins in load.items():
        cap = D.WORKSTATIONS[ws][0]
        eff_cap = 1 if ws.startswith("热处理") else cap   # 分钟数已按炉分摊
        per_day = 480 * eff_cap / mins if mins else float("inf")
        rows.append((ws, mins, cap, per_day))
    return sorted(rows, key=lambda r: r[3])


def tree(code, depth=0, qty=1, out=None):
    out = [] if out is None else out
    name = D.ITEMS[code][0].split(" ")[0]
    q = "" if depth == 0 else " ×{:g}".format(qty)
    out.append("{}{} {}{}".format("    " * depth, code, name, q))
    if code in D.BOMS:
        for c, qn in D.BOMS[code][1]:
            if c in D.BOMS or D.ITEMS[c][1] == "raw":
                tree(c, depth + 1, qn, out)
        buys = [(c, qn) for c, qn in D.BOMS[code][1] if c not in D.BOMS and D.ITEMS[c][1] == "buy"]
        if buys:
            out.append("{}外购件：{}".format("    " * (depth + 1),
                                          "、".join("{} ×{:g}".format(c, qn) for c, qn in buys)))
    return out


def build():
    L = []
    a = L.append
    a("# 问渠虚拟工厂设计：二级圆柱齿轮减速器 WQR-105")
    a("")
    a("虚拟工厂只生产一种产品：二级展开式圆柱齿轮减速器，传动比 {:.1f}，输入 {} r/min，输出约 {:.1f} r/min。"
      "它把机械设计（齿轮、轴、箱体）、机械制造（工艺路线、工作中心、质量检验）和生产管理（BOM、MRP、工单、采购、库存、成本）连成一条线。".format(
          D.ratio(), D.INPUT_SPEED_RPM, D.INPUT_SPEED_RPM / D.ratio()))
    a("")
    a("本文的表格由 `factory/data.py` 自动生成；要改工厂，改 data.py 后运行 `py -m factory.make_docs` 重新生成本文，再运行 `py seed.py` 导入。所有供应商和客户都是虚构的示例单位，单价是教学用的示意数值（美元）。")
    a("")
    a("## 传动设计")
    a("")
    a("| 级 | 小齿轮 | 大齿轮 | 模数 m | 齿数 z₁ / z₂ | 传动比 | 中心距 a (mm) |")
    a("| --- | --- | --- | --- | --- | --- | --- |")
    for i, (p, g) in enumerate(D.STAGES, start=1):
        m, z1, z2 = D.GEARS[p]["m"], D.GEARS[p]["z"], D.GEARS[g]["z"]
        a("| 第{}级 | {} | {} | {} | {} / {} | {:.2f} | {:g} |".format(i, p, g, m, z1, z2, z2 / z1, D.center_distance(m, z1, z2)))
    a("")
    a("齿轮均为标准渐开线直齿轮，压力角 20°。公法线长度 W_k = m·cos α·[π(k − 0.5) + z·inv α]，是齿轮检验的主要尺寸之一：")
    a("")
    a("| 齿轮 | m | z | 跨齿数 k | 公法线名义值 (mm) |")
    a("| --- | --- | --- | --- | --- |")
    for code, g in D.GEARS.items():
        k, w = D.base_tangent_length(g["m"], g["z"])
        a("| {} | {} | {} | {} | {:.3f} |".format(code, g["m"], g["z"], k, w))
    a("")
    a("## 产品结构")
    a("")
    a("```")
    L.extend(tree("WQR-105"))
    a("```")
    a("")
    a("输出轴 SH-301 就是 FreeCAD 入门包里 `wq_shaft.py` 的默认阶梯轴（Ø30–Ø35–Ø40–Ø35–Ø30，Ø40 段开 12×5 键槽）。")
    a("")
    a("## 物料清单")
    a("")
    a("| 代号 | 名称 | 类别 | 单位 | 单价 (USD) | 供应商 | 检验模板 |")
    a("| --- | --- | --- | --- | --- | --- | --- |")
    for code, (name, kind, uom, price, sup, qit, note) in D.ITEMS.items():
        a("| {} | {} | {} | {} | {} | {} | {} |".format(
            code, name, KIND_CN[kind], uom, "{:.2f}".format(price) if price else "（按 BOM 计算）",
            D.SUPPLIERS[sup]["name"] if sup else "自制", qit or ""))
    a("")
    a("## 工作中心")
    a("")
    a("单班 8 小时（08:00–12:00、13:00–17:00），周末和美国主要节假日休息。")
    a("")
    a("| 工作中心 | 台数/容量 | 折旧 | 人工 | 能耗 | 合计 (USD/小时) |")
    a("| --- | --- | --- | --- | --- | --- |")
    for ws, (cap, c) in D.WORKSTATIONS.items():
        a("| {} | {} | {} | {} | {} | {} |".format(ws, cap, c[0], c[1], c[2], sum(c)))
    a("")
    a("热处理炉一炉装 20 件，工艺路线里热处理的分钟数是分摊到每件的炉时。")
    a("")
    a("## 工艺路线")
    a("")
    for rname, ops in D.ROUTINGS.items():
        users = [p for p, (r, _) in D.BOMS.items() if r == rname]
        a("**{}**（用于 {}）：".format(rname, "、".join(users)))
        a("")
        a(" → ".join("{} {} 分钟".format(o.split(" ")[0], m) for o, m in ops))
        a("")
    gated = [c for c in D.BOMS if D.ITEMS[c][5]]
    a("质检门：{} 这几种有检验模板的物料，其“零件检验”或“出厂检验”工序要求先提交质量检验单，工序卡才能完成；其余物料的检验工序只记工时。".format("、".join(gated)))
    a("")
    a("## 每台产品占用的工作中心时间（找瓶颈）")
    a("")
    a("把每台减速器所有零件、部件和总装的工序时间按工作中心加总，再按单班 8 小时和台数折算日产能。日产能最低的就是瓶颈。")
    a("")
    a("| 工作中心 | 每台占用 (分钟) | 台数/容量 | 单班日产能 (台) |")
    a("| --- | --- | --- | --- |")
    for ws, mins, cap, per_day in workstation_load():
        a("| {} | {:g} | {} | {:.1f} |".format(ws, mins, cap, per_day))
    a("")
    a("热处理炉按一炉 20 件计，实际瓶颈要结合装炉批量和节拍来分析，这正好是课堂讨论题。")
    a("")
    a("## 质量检验方案")
    a("")
    for tname, params in D.inspection_templates().items():
        users = [c for c, v in D.ITEMS.items() if v[5] == tname]
        a("**{}**（{}）".format(tname, "、".join(users)))
        a("")
        a("| 检验项目 | 合格标准 |")
        a("| --- | --- |")
        for p in params:
            a("| {} | {} |".format(p["parameter"], "{:g} – {:g}".format(p["min"], p["max"]) if p["numeric"] else p["value"]))
        a("")
    a("外购的轴承、铸件、锻坯收货前必须检验；成品发货前必须做出厂检验；成品按序列号管理（WQR105-00001 起），可追溯到每台的检验记录。")
    a("")
    a("## 供应商与客户")
    a("")
    a("| 供应商 | 供应内容 | 采购提前期 (天) |")
    a("| --- | --- | --- |")
    content = {}
    for code, v in D.ITEMS.items():
        if v[4]:
            content.setdefault(v[4], []).append(code)
    for key, s in D.SUPPLIERS.items():
        a("| {} | {} | {} |".format(s["name"], "、".join(content.get(key, [])), s["lead"]))
    a("")
    a("客户：{}。成品售价 {:,.0f} 美元/台。".format("；".join(D.CUSTOMERS), D.FG_SELLING_PRICE))
    a("")
    a("## 标准成本（导入后 ERPNext 算出的 BOM 成本应与此接近）")
    a("")
    a("| 代号 | 名称 | 材料及下层 (USD) | 本级工序 (USD) | 本级工时 (分钟) | 合计 (USD) |")
    a("| --- | --- | --- | --- | --- | --- |")
    for code, (tot, mat, op, mins) in std_cost().items():
        a("| {} | {} | {:.2f} | {:.2f} | {} | {:.2f} |".format(code, D.ITEMS[code][0].split(" ")[0], mat, op, mins, tot))
    a("")
    return "\n".join(L)


if __name__ == "__main__":
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(build())
    print("已生成", os.path.abspath(OUT))
