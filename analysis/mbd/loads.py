"""多体结果 → 疲劳载荷谱（ADR-0097 D7b，补充十九）：从结果取一条载荷时间序列，拼成 analysis/fatigue 的设置并算寿命。"""

from __future__ import annotations

from analysis.mbd.study import series


def fatigue_setup(data: dict, path: str, *, material: str, stress_ref_mpa: float, load_ref: float,
                  surface_factor: float, size_factor: float, miner: str = "haibach", kf: float = 1.0,
                  from_time_s: float = 0.0) -> dict:
    """path：结果里的序列，如 joints.J1.force_n.0（反力 x 分量，N）、motions.m.effort、flex.bar.stress.max_von_mises_mpa；
    stress_ref_mpa / load_ref：危险点在参考载荷下的应力（线弹性比例加载）。这一段时间当一个重复块。"""
    import numpy as np

    y = series(data, path)
    t = np.asarray(data["times_s"], float)
    sel = t >= from_time_s
    return {"material": material, "stress_ref_mpa": stress_ref_mpa, "load_ref": load_ref,
            "load_series": [float(v) for v in y[sel]], "block_seconds": float(t[sel][-1] - t[sel][0]),
            "surface_factor": surface_factor, "size_factor": size_factor, "kf": kf, "miner": miner,
            "source": f"多体动力学结果 {data.get('model', '')} 的 {path}（ADR-0097 D7b）"}


def fatigue(data: dict, path: str, **kw) -> dict:
    from analysis.fatigue import run

    return run(fatigue_setup(data, path, **kw))
