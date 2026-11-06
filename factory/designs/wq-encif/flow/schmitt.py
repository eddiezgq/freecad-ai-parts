# -*- coding: utf-8 -*-
"""第 93 轮：WQ-ENCIF 输入端施密特触发器的晶体管级仿真（ngspice + SKY130 器件模型）。
6 管 CMOS 施密特触发器 + 输出反相器；与《数字集成电路设计》第 1 章的普通反相器（Wn 0.42、Wp 0.97 μm）对比。
① 反馈管宽度扫描，选回差 ≥ 0.6 V 的最小一档；② 慢三角波输入（准静态）上升 / 下降：上门限 VT+、下门限 VT−；③ 工艺角与温度；
④ 带 ±0.3 V 干扰的慢边沿：数两种输入级的输出翻转次数；⑤ 干净边沿的传播延迟（负载 10 fF）。
用法：python3 schmitt.py --lib $PDK_ROOT/sky130A/libs.tech/combined/sky130.lib.spice --out OUT
      python3 schmitt.py --generic --out OUT   （本机冒烟：通用一级模型，数不能当真）。示例设计，未流片。"""
import argparse
import json
import os
import random
import subprocess
import tempfile

VDD = 1.8
L = 0.15
WN, WP = 0.42, 0.97            # 主通路（与第 1 章反相器同尺寸）
INV = (0.42, 0.97)             # 对比用的普通反相器
OUTINV = (0.42, 0.97)          # 施密特后面的输出反相器
KS = [1, 1.5, 2, 2.5, 3, 4]        # 反馈管宽度 = k × 主通路宽度（SKY130 的 1.8 V 管有最小宽度，从 1 倍 = 0.42 μm 起）
TARGET = 0.6                   # 回差目标（V），大于 ±0.3 V 干扰的峰峰值
CORNERS = [("tt", 27), ("ss", 27), ("ff", 27), ("sf", 27), ("fs", 27), ("tt", -40), ("tt", 125)]
GENERIC = """
.model gn nmos level=1 vto=0.45 kp=270u lambda=0.05 gamma=0.4 cgso=3e-10 cgdo=3e-10 cgbo=1e-10 tox=4e-9
.model gp pmos level=1 vto=-0.45 kp=60u lambda=0.08 gamma=0.4 cgso=3e-10 cgdo=3e-10 cgbo=1e-10 tox=4e-9
.subckt sky130_fd_pr__nfet_01v8 d g s b W=1 L=0.15 nf=1
M1 d g s b gn W={W*1u} L={L*1u}
.ends
.subckt sky130_fd_pr__pfet_01v8 d g s b W=1 L=0.15 nf=1
M1 d g s b gp W={W*1u} L={L*1u}
.ends
"""


def cells(k):
    wfn, wfp = round(k * WN, 3), round(k * WP, 3)
    return wfn, wfp, f"""
.subckt schmitt IN OUT VDD VSS
* 下拉：两只串联 NMOS，中点 X；反馈 NMOS 由输出控制，把 X 往 VDD 拉（推高上门限）
XMN1 X IN VSS VSS sky130_fd_pr__nfet_01v8 W={WN} L={L}
XMN2 OB IN X VSS sky130_fd_pr__nfet_01v8 W={WN} L={L}
XMN3 VDD OB X VSS sky130_fd_pr__nfet_01v8 W={wfn} L={L}
* 上拉：两只串联 PMOS，中点 Y；反馈 PMOS 把 Y 往地拉（压低下门限）
XMP1 Y IN VDD VDD sky130_fd_pr__pfet_01v8 W={WP} L={L}
XMP2 OB IN Y VDD sky130_fd_pr__pfet_01v8 W={WP} L={L}
XMP3 VSS OB Y VDD sky130_fd_pr__pfet_01v8 W={wfp} L={L}
* 输出反相器（整体同相）
XMN4 OUT OB VSS VSS sky130_fd_pr__nfet_01v8 W={OUTINV[0]} L={L}
XMP4 OUT OB VDD VDD sky130_fd_pr__pfet_01v8 W={OUTINV[1]} L={L}
.ends
.subckt inv IN OUT VDD VSS
XMN OUT IN VSS VSS sky130_fd_pr__nfet_01v8 W={INV[0]} L={L}
XMP OUT IN VDD VDD sky130_fd_pr__pfet_01v8 W={INV[1]} L={L}
.ends
"""


def header(a, corner, temp):
    lib = GENERIC if a.generic else '.lib "{}" {}'.format(a.lib, corner)
    return "* WQ-ENCIF 输入级\n{}\n.temp {}\n.option noinit\n".format(lib, temp)


def run(net, tmp):
    p = os.path.join(tmp, "c.spice")
    with open(p, "w") as f:
        f.write(net)
    r = subprocess.run(["ngspice", "-b", p], cwd=tmp, capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        raise RuntimeError(r.stdout[-1500:] + r.stderr[-1500:])
    return r.stdout


def table(path):
    rows = []
    for ln in open(path):
        p = ln.split()
        if p:
            try:
                rows.append([float(x) for x in p])
            except ValueError:
                pass
    return rows


def cross(xs, ys, level, rising):
    for i in range(1, len(xs)):
        a, b = ys[i - 1], ys[i]
        if (rising and a < level <= b) or (not rising and a > level >= b):
            return xs[i - 1] + (level - a) * (xs[i] - xs[i - 1]) / (b - a)
    return None


def dc(a, k, corner, temp, tmp, keep=False):
    """准静态转移曲线：输入用慢三角波（2 μs 升到 VDD、2 μs 降回 0），比直流扫描可靠——双稳态电路的直流扫描不一定沿着上一点的状态走。
    VT+ = 上升段输出越过 VDD/2 时的输入，VT− = 下降段的。"""
    wfn, wfp, sub = cells(k)
    net = header(a, corner, temp) + sub + f"""
VDD vdd 0 {VDD}
VIN in 0 PWL(0 0 2u {VDD} 4u 0)
XS in out vdd 0 schmitt
XI in oi vdd 0 inv
.control
set wr_singlescale
tran 2n 4u
wrdata tri.txt v(in) v(out) v(oi)
.endc
.end
"""
    run(net, tmp)
    rows = table(os.path.join(tmp, "tri.txt"))
    up = [(r[1], r[2], r[3]) for r in rows if r[0] <= 2e-6]
    dn = [(r[1], r[2], r[3]) for r in rows if r[0] > 2e-6]
    vtp = cross([r[0] for r in up], [r[1] for r in up], VDD / 2, True)
    vtn = cross([r[0] for r in dn], [r[1] for r in dn], VDD / 2, False)
    vm = cross([r[0] for r in up], [r[2] for r in up], VDD / 2, False)          # 普通反相器的门限（输出下降过半）
    res = {"k": k, "wfn": wfn, "wfp": wfp, "vt_plus": r4(vtp), "vt_minus": r4(vtn), "hyst": r4(vtp - vtn) if vtp and vtn else None, "inv_vm": r4(vm)}
    if keep:
        st = max(1, len(up) // 180)
        res["curve_up"] = [[r4(r[0]), r4(r[1])] for r in up[::st]]
        res["curve_dn"] = [[r4(r[0]), r4(r[1])] for r in dn[::st]]
        res["curve_inv"] = [[r4(r[0]), r4(r[2])] for r in up[::st]]
    return res


def r4(x):
    return None if x is None else round(x, 4)


def noisy_pwl(seed=93):
    """慢边沿（上升 1.6 μs、下降 1.6 μs）叠加 ±0.3 V 干扰（每 4 ns 一点的随机值，固定种子）"""
    rnd = random.Random(seed)
    pts = []
    t, dt = 0.0, 4e-9
    seg = [(0.4e-6, 0, 0), (1.6e-6, 0, VDD), (0.4e-6, VDD, VDD), (1.6e-6, VDD, 0), (0.4e-6, 0, 0)]
    t0 = 0.0
    for dur, v0, v1 in seg:
        n = int(round(dur / dt))
        for i in range(n):
            base = v0 + (v1 - v0) * i / n
            pts.append((t0 + i * dt, base + rnd.uniform(-0.3, 0.3)))
        t0 += dur
    pts.append((t0, 0.0))
    return pts, t0


def toggles(ts, vs):
    """输出越过 VDD/2 的次数"""
    n, hi = 0, vs[0] > VDD / 2
    for v in vs[1:]:
        h = v > VDD / 2
        if h != hi:
            n += 1
            hi = h
    return n


def noise(a, k, tmp):
    _, _, sub = cells(k)
    pts, tend = noisy_pwl()
    pwl = " ".join("{:.4g} {:.4f}".format(t, v) for t, v in pts)
    net = header(a, "tt", 27) + sub + f"""
VDD vdd 0 {VDD}
VIN in 0 PWL({pwl})
XS in out vdd 0 schmitt
XI in oi vdd 0 inv
CS out 0 10f
CI oi 0 10f
.control
set wr_singlescale
tran 1n {tend:.4g}
wrdata tr.txt v(in) v(out) v(oi)
.endc
.end
"""
    run(net, tmp)
    rows = table(os.path.join(tmp, "tr.txt"))
    ts = [r[0] for r in rows]
    so, io = [r[2] for r in rows], [r[3] for r in rows]
    step = max(1, len(rows) // 1500)
    return {"schmitt_toggles": toggles(ts, so), "inv_toggles": toggles(ts, io), "noise_v": 0.3, "edge_us": 1.6,
            "wave": [[round(r[0] * 1e9, 1), r4(r[1]), r4(r[2]), r4(r[3])] for r in rows[::step]]}


def delay(a, k, corner, temp, tmp):
    _, _, sub = cells(k)
    net = header(a, corner, temp) + sub + f"""
VDD vdd 0 {VDD}
VIN in 0 PULSE(0 {VDD} 1n 50p 50p 5n 10n)
XS in out vdd 0 schmitt
CS out 0 10f
.control
tran 2p 12n
meas tran tplh trig v(in) val=0.9 rise=1 targ v(out) val=0.9 rise=1
meas tran tphl trig v(in) val=0.9 fall=1 targ v(out) val=0.9 fall=1
.endc
.end
"""
    try:
        out = run(net, tmp)
    except RuntimeError as e:                      # 收敛不了就记为空，不让一个点拖垮整次（结果里看得到）
        out = str(e)
    m = {"tplh": None, "tphl": None}
    for ln in out.splitlines():
        p = ln.replace("=", " = ").split()
        if p and p[0] in ("tplh", "tphl") and "=" in p:
            try:
                m[p[0]] = round(float(p[p.index("=") + 1]) * 1e12, 1)     # ps
            except ValueError:
                pass
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lib")
    ap.add_argument("--generic", action="store_true")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    if not a.generic and not (a.lib and os.path.exists(a.lib)):
        raise SystemExit("要 --lib（SKY130 的 sky130.lib.spice）或 --generic")
    os.makedirs(a.out, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="schmitt-")
    sweep = []
    for k in KS:
        try:
            sweep.append(dc(a, k, "tt", 27, tmp))
        except RuntimeError as e:                  # 某一档算不出来就记为空（结果里看得到），不拖垮整次
            print("反馈管 ×{} 没算出来：{}".format(k, str(e)[-300:]))
            sweep.append({"k": k, "wfn": round(k * WN, 3), "wfp": round(k * WP, 3), "vt_plus": None, "vt_minus": None, "hyst": None, "inv_vm": None})
    ok = [s for s in sweep if s["hyst"] and s["hyst"] >= TARGET]
    pick = min(ok, key=lambda s: s["k"]) if ok else max(sweep, key=lambda s: s["hyst"] or 0)
    k = pick["k"]
    nominal = dc(a, k, "tt", 27, tmp, keep=True)
    corners = []
    for c, t in CORNERS:
        r = dc(a, k, c, t, tmp)
        r.update(delay(a, k, c, t, tmp))
        r.update(corner=c, temp=t)
        corners.append(r)
    nz = noise(a, k, tmp)
    ver = subprocess.run(["ngspice", "-v"], capture_output=True, text=True).stdout
    res = {
        "models": "generic（本机冒烟，数不能当真）" if a.generic else "SKY130 sky130_fd_pr（{}）".format(os.path.basename(a.lib)),
        "generic": bool(a.generic), "ngspice": next((ln.strip("* ").strip() for ln in ver.splitlines() if "ngspice-" in ln), ""),
        "image": os.environ.get("WQ_IMAGE", ""), "vdd": VDD, "l_um": L, "target_hyst": TARGET,
        "design": {"wn": WN, "wp": WP, "k": k, "wfn": pick["wfn"], "wfp": pick["wfp"], "out_inv": list(OUTINV), "plain_inv": list(INV)},
        "sweep": sweep, "nominal": nominal, "corners": corners, "noise": nz,
    }
    res["pass"] = bool(nominal["hyst"] and nominal["hyst"] >= TARGET and all(c["hyst"] and c["hyst"] > 0 for c in corners)
                       and nz["schmitt_toggles"] == 2 and nz["inv_toggles"] > 2)
    with open(os.path.join(a.out, "schmitt.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, separators=(",", ":"))
    s = {kk: v for kk, v in res.items() if kk not in ("nominal", "noise")}
    s["nominal"] = {kk: v for kk, v in nominal.items() if not kk.startswith("curve")}
    s["noise"] = {kk: v for kk, v in nz.items() if kk != "wave"}
    print(json.dumps(s, ensure_ascii=False, indent=1))
    return 0 if res["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
