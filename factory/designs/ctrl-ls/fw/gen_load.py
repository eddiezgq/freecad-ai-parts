# -*- coding: utf-8 -*-
"""第 159 轮 159f：主轴一转负载表——用第 138 轮 G2 的机构动力学（tools/wqls/dyn.py，不改它）算，和 159c 的伺服复算（gc_sim.py）同一张表。

    python3 gen_load.py        # 写 renode/load_table.txt（Renode 电机模型读它）

每 0.5° 一行：转角 °、惯性部分 N·m（5000 r/min 时的值，随转速平方变）、缝纫阻力 N·m（转着才有）。
gc_sim.load() 的算法：T = 惯性部分 × (ω / ω5000)² + (ω > 1 rad/s 时) 缝纫阻力；剪线那一针在 200°–330° 另加 0.15 N·m（示例）。"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools", "wqls"))


def table():
    import dyn

    R = dyn.Machine().run(N=720)
    t_in = R["T_bar"] + R["T_rod"] + R["T_tk"] + R["T_fd"]
    t_rs = R["T_needle"] + R["T_thread"] + R["T_feed"] + R["T_fric"] + R["T_grav"]
    return float(R["w"]), [(float(p), float(a), float(b)) for p, a, b in zip(R["phi"], t_in, t_rs)]


def main():
    w5, rows = table()
    lines = ["# 第 138 轮 G2 一转负载（gen_load.py 生成，勿手改）：w5000 rad/s，然后每行 转角° 惯性部分 N·m 缝纫阻力 N·m",
             "w5000 {:.6f}".format(w5)] + ["{:.1f} {:.6f} {:.6f}".format(*r) for r in rows]
    with open(os.path.join(HERE, "renode", "load_table.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("load_table.txt：{} 行".format(len(rows)))


if __name__ == "__main__":
    main()
