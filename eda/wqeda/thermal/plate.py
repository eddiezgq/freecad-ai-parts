# -*- coding: utf-8 -*-
"""板子温升（第 111 轮 P4）：把板子当成一块平板，用 CalculiX 算稳态温度。

网格：规则的六面体（DC3D8），每格 dx × dx，厚度方向一格；每格有自己的面内、厚度方向导热系数（按这一格的铜占比折算）。
热源：器件损耗按焊盘面积分到格子顶面（面热流）。两面对流换热：系数 h、环境温度 Ta。四周板边绝热。

单位制（与数字工厂热分析 cae/thermal.py 相同）：mm、mW、℃；导热系数 W/(m·K) = mW/(mm·K)（数不变），
换热系数 W/(m²·K) × 10⁻³ → mW/(mm²·K)，功率 W × 10³ → mW。

本模块只生成输入文本、整理结果，纯计算；调 CalculiX 在 ccx.py（外部程序，GPL，只作工具），不联网、不调 AI。"""

from __future__ import annotations

import os

SOLVER = os.environ.get("WQ_CCX_SOLVER", "ITERATIVE CHOLESKY")


def node_id(i, j, k, nx, ny):
    return 1 + i + (nx + 1) * (j + (ny + 1) * k)


def deck(nx, ny, dx, t, k_cells, q_cells, h, ta):
    """nx × ny 格，格宽 dx mm，板厚 t mm。
    k_cells[(i, j)] = (面内 k, 厚度方向 k) W/(m·K)；q_cells[(i, j)] = 这一格顶面的发热功率 W；h W/(m²·K)；ta ℃"""
    out = ["*HEADING", "WenQuest Electronics board plate thermal (round 111)", "*NODE, NSET=NALL"]
    for k in range(2):
        for j in range(ny + 1):
            for i in range(nx + 1):
                out.append("{},{:.6g},{:.6g},{:.6g}".format(node_id(i, j, k, nx, ny), i * dx, j * dx, k * t))
    mats = {}
    elems = {}
    for j in range(ny):
        for i in range(nx):
            kk = k_cells[(i, j)]
            key = (round(kk[0], 3), round(kk[1], 4))
            mats.setdefault(key, "M{}".format(len(mats) + 1))
            elems.setdefault(key, []).append((i, j))

    def eid(i, j):
        return 1 + i + nx * j

    out.append("*ELEMENT, TYPE=DC3D8, ELSET=EALL")
    for j in range(ny):
        for i in range(nx):
            n = [
                node_id(i, j, 0, nx, ny),
                node_id(i + 1, j, 0, nx, ny),
                node_id(i + 1, j + 1, 0, nx, ny),
                node_id(i, j + 1, 0, nx, ny),
            ]
            m = [
                node_id(i, j, 1, nx, ny),
                node_id(i + 1, j, 1, nx, ny),
                node_id(i + 1, j + 1, 1, nx, ny),
                node_id(i, j + 1, 1, nx, ny),
            ]
            out.append("{},{}".format(eid(i, j), ",".join(map(str, n + m))))
    for key, name in mats.items():
        out.append("*ELSET, ELSET=E{}".format(name))
        ids = [eid(i, j) for i, j in elems[key]]
        out += [",".join(map(str, ids[a : a + 12])) for a in range(0, len(ids), 12)]
        out.append("*MATERIAL, NAME={}".format(name))
        out.append("*CONDUCTIVITY, TYPE=ORTHO")
        out.append("{:.6g},{:.6g},{:.6g}".format(key[0], key[0], key[1]))
        out.append("*SOLID SECTION, ELSET=E{}, MATERIAL={}".format(name, name))
    # 求解器照数字工厂（cae/solve.py、cae/thermal.py）：用迭代法；缺省的直接法在 CI 机器上会卡住
    out += ["*STEP", "*HEAT TRANSFER, STEADY STATE, SOLVER={}".format(SOLVER), "1.,1."]
    hh = h * 1e-3
    out.append("*FILM")
    for j in range(ny):
        for i in range(nx):
            out.append("{},F1,{:.6g},{:.6g}".format(eid(i, j), ta, hh))  # 底面
            out.append("{},F2,{:.6g},{:.6g}".format(eid(i, j), ta, hh))  # 顶面
    if q_cells:
        out.append("*DFLUX")
        for (i, j), p in sorted(q_cells.items()):
            if p > 0:
                out.append("{},S2,{:.9g}".format(eid(i, j), p * 1e3 / (dx * dx)))
    out += ["*NODE FILE", "NT", "*END STEP"]
    return "\n".join(out) + "\n"


def cell_temps(nt, nx, ny):
    """每格顶面四个节点的平均温度 {(i, j): ℃}"""
    out = {}
    for j in range(ny):
        for i in range(nx):
            ids = [
                node_id(i, j, 1, nx, ny),
                node_id(i + 1, j, 1, nx, ny),
                node_id(i + 1, j + 1, 1, nx, ny),
                node_id(i, j + 1, 1, nx, ny),
            ]
            out[(i, j)] = sum(nt[n] for n in ids) / 4
    return out
