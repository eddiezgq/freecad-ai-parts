# -*- coding: utf-8 -*-
"""第 159 轮 159f：从 159c 的主轴伺服复算（第 138 轮 tools/wqls/gc_sim.py 的模型，力矩上限 3.0 N·m，与 ctrl_ls_sim.py 相同）
多取两个对照量，写 out/ref_159c.json，给 run_sew.py 对照用（run_sew 不直接调 gc_sim：要 numpy、matplotlib）：
  剪线那一针、主轴在 200°–330° 时的平均转速；松脚踏后减到 300 r/min（+5 %）的时间。其余对照量直接读 159c 的仿真结果.json。

    python3 ref_159c.py"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools", "wqls"))


def main():
    import gc_sim

    gc_sim.T_PEAK = 3.0                       # 159c：本控制器能给的力矩上限（ctrl_ls_sim.py 同样改这一个数）
    t_trim = 0.62 + 60 / 300 * 1.0
    lg = gc_sim.simulate(gc_sim.cycle(), f_s=40.0, ff=0.0, stop_at=(t_trim, 70.0), t_end=t_trim + 0.25, trim_window=(0.62, t_trim))
    t, rpm, ang = lg[:, 0], lg[:, 1], lg[:, 3]
    m = (t >= 0.62) & (t <= t_trim) & (ang >= 200) & (ang <= 330)
    dec = float(t[(t > 0.5) & (rpm <= 315)][0] - 0.5)
    out = dict(source="tools/wqls/gc_sim.py（第 138 轮），力矩上限 3.0 N·m（159c）", trim_rpm_mean=round(float(rpm[m].mean()), 2),
               trim_rpm_min=round(float(rpm[m].min()), 2), t_decel_300_s=round(dec, 4))
    with open(os.path.join(HERE, "out", "ref_159c.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print(out)


if __name__ == "__main__":
    main()
