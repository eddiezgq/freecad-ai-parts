"""色差图（ADR-0106 Q2 第 6 步）：加工完的在制毛坯与零件模型比。

铣：零件形体三角化（FreeCAD tessellate），换到程序坐标（Z0 在零件顶面），按回放的同一套 dexel 网格算成射线区间，
    与加工后的毛坯比（analysis.cam.dexel.compare：毛坯表面点在零件里为过切，在外为残留，距离按到零件表面采样点的最近距离，误差不超过半格）；
    画面按 Z 向射线：每格“毛坯顶面 − 零件顶面”上色（零件这一格没有材料时整根都是残留）。
车：零件模型读出的轮廓（作业的零件数据）就是比对目标，按半径网格比（analysis.cam.replay.lathe_deviation）。
"""

from __future__ import annotations

import numpy as np

from analysis.cam import dexel as DX
from analysis.cam import replay as R
from freecad_addon.fc import cam_objects as CO

TOL = 0.02          # 色差图的公差带（mm）：在 ±TOL 内画绿


def model_triangles(shape, z_shift: float, tol: float = 0.05) -> np.ndarray:
    """FreeCAD 形体 → 三角形 (n, 3, 3)，z 减去 z_shift（换到程序坐标）"""
    pts, faces = shape.tessellate(tol)
    P = np.array([[p.x, p.y, p.z - z_shift] for p in pts], float)
    F = np.array(faces, int)
    return P[F] if len(F) else np.zeros((0, 3, 3))


def mill_deviation(rp: R.Replay, shape, z_top: float, tol: float = TOL) -> dict:
    final = rp.stock_after(len(rp.frames))
    part = DX.Dexel(final.lo, final.hi, final.h)
    tris = model_triangles(shape, z_top)
    for k in range(3):
        part._set_from_triangles(k, tris)
    c = DX.compare(final, part, tol)
    # 画面：Z 向每格的顶面差
    top_s = np.fmax.reduce(np.nan_to_num(final.E[2], nan=-np.inf), -1)
    top_p = np.fmax.reduce(np.nan_to_num(part.E[2], nan=-np.inf), -1)
    bot_s = np.fmin.reduce(np.nan_to_num(final.S[2], nan=np.inf), -1)
    with np.errstate(invalid="ignore"):                          # 没有材料的格：inf − inf，画面里也不画
        cell_dev = np.where(np.isfinite(top_p), top_s - top_p, top_s - bot_s)
    stride = max(1, int(max(final.n[0], final.n[1]) // 160))
    v, t, cells = R.height_mesh(final, stride=stride, cells=True)
    dev = cell_dev[cells[:, 0], cells[:, 1]] if len(cells) else np.zeros(0)
    return {"over_max": c["over_max"], "under_max": c["under_max"], "over": c["over"], "at": c["at"], "tol": tol,
            "h": final.h, "mesh": (v, t, dev)}


def for_job(job, rp: R.Replay, side: str):
    """回放窗口的色差：铣用零件模型；车用零件数据里的轮廓。没有模型时返回 None"""
    if rp.lathe:
        return R.lathe_deviation(rp, tol=TOL)
    if job.Model is None:
        return None
    z_top = CO.to_model(job, side, 0.0, 0.0, 0.0)[2]
    return mill_deviation(rp, job.Model.Shape, z_top)


def checks_for(job, rp: R.Replay, side: str) -> list[dict]:
    """计算并检查时加进检查清单的三维比对结论（铣）：过切 = 错误；残留只报最大值（提示）"""
    if rp.lathe or job.Model is None or not rp.frames:
        return []
    res = for_job(job, rp, side)
    out = []
    if res["over"]:
        x, y, z = res["at"]
        out.append({"line": None, "level": "error",
                    "text": f"三维比对：切进零件模型最多 {res['over_max']:.3f} mm（X{x:.2f} Y{y:.2f} Z{z:.2f} 附近；网格 {res['h']:.2f} mm，误差半格）"})
    if res["under_max"] > TOL:
        out.append({"line": None, "level": "warn",
                    "text": f"三维比对：比零件模型多留最多 {res['under_max']:.3f} mm（网格 {res['h']:.2f} mm；看色差图哪里没铣到）"})
    return out
