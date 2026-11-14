# -*- coding: utf-8 -*-
"""第 159 轮 159f：平缝机控制器 CTRL-LS 的固件在 Renode 里缝一段，三个场景逐一核对，写 out/sim_sew.json。

用法：python3 run_sew.py [--renode /opt/renode/renode] [--no-build] [--only cycle,seam,jam]
每个场景起一台仿真机：STM32G431（真固件 fw.elf）+ TIM1 / 功率模块 / 电机 / 主轴一转负载（renode/WqSew.cs）+ TIM4 编码器 + ADC1、ADC2。
按时间表踩脚踏（监视器命令 tim1 Pedal，脚踏板霍尔电压）、注入故障；按采样表读电机真值（tim1 Truth）和固件内存里的遥测区 mc、sw；
最后取电磁铁动作记录（tim1 SolLog）。判据都对物理真值；和 159c 的主轴伺服复算（docs/设计/WQ-LS/GC/控制器仿真/仿真结果.json）对照。"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
OUT = os.path.join(HERE, "out")
ELF = os.path.join(HERE, "build", "fw.elf")
REF = os.path.join(ROOT, "docs", "设计", "WQ-LS", "GC", "控制器仿真", "仿真结果.json")

MCF = [("magic", "I"), ("state", "I"), ("mode", "I"), ("fault", "I"), ("isr", "I"), ("ms", "I"), ("align_off", "i"), ("pos_cnt", "i"),
       ("z_cnt", "i"), ("z_seen", "I"), ("angle_x100", "i"), ("id", "f"), ("iq", "f"), ("id_ref", "f"), ("iq_ref", "f"), ("vd", "f"),
       ("vq", "f"), ("speed_rpm", "f"), ("speed_ref", "f"), ("speed_tgt", "f"), ("acc_ref", "f"), ("stop_x100", "i"),
       ("pos_err_deg", "f"), ("vbus", "f"), ("pedal_v", "f"), ("imax", "f"), ("moe", "I"), ("fault_val", "f"), ("stall_ms", "I")]
SWF = [("magic", "I"), ("state", "I"), ("stitches", "I"), ("seam_stitches", "I"), ("sol", "I"), ("pedal", "I"), ("pedal_rpm", "f"),
       ("trims", "I"), ("t_state_ms", "I")]
CFG = ["magic", "bt_fwd", "bt_rev", "bt_rpm", "trim_rpm", "up_x100", "down_x100", "trim_on_x100", "trim_off_x100", "wipe_ms", "foot_max_ms"]
MSTATE = {0: "初始化", 1: "对零", 2: "找 Z 相", 3: "就绪", 4: "故障"}
SWSTATE = {0: "开机", 1: "待机", 2: "起缝加固·正", 3: "起缝加固·倒", 4: "缝纫", 5: "停针中", 6: "下针位", 7: "剪线", 8: "拨线",
           9: "抬压脚", 10: "故障"}
FAULT = {0: "无", 1: "过流", 2: "欠压", 3: "堵转"}
SOL = ["剪线", "拨线", "倒缝", "抬压脚"]

# 参数表：出处“设计描述”“159c”“第 138 轮”“示例”
PARAMS = [
    ("母线电压", "390", "V", "159b 计算书：校正输出"),
    ("功率模块", "STGIPS14K60T，PWM 16 kHz、死区 1 µs、SD 低有效", "", "设计描述 ipm_inverter；规格书"),
    ("力矩常数 Kt", "0.496", "N·m/A", "159c：5000 r/min 线反电势峰值 ≤ 300 V 推出"),
    ("力矩上限", "3.0 N·m（相电流 6.05 A）", "", "159c"),
    ("转动惯量", "转子 4×10⁻⁴ + 机头负载 1.24×10⁻⁴ kg·m²", "", "第 138 轮 G2、159c"),
    ("极对数", "4", "", "示例（第 138 轮电机未选型）"),
    ("相电阻、相电感", "1.2 Ω、4 mH", "", "示例（第 138 轮电机未选型）"),
    ("主轴负载", "G2 一转负载表：惯性部分 ×（转速 / 5000）² + 缝纫阻力；剪线一针 200°–330° 另加 0.15 N·m", "", "第 138 轮 G2（dyn.py），与 159c 同一张表"),
    ("电流采样", "下桥 25 mΩ + 片内运放 8 倍，V = 1.65 − 0.1875 × i", "", "设计描述 low_side_sense"),
    ("过流阈值", "7.5", "A", "设计描述 low_side_sense.i_trip"),
    ("编码器", "2500 线 ×4 = 10 000 计数/转；Z 相在针杆最高点（主轴 0°）", "", "设计描述 sensor_inputs；Z 相位置是示例"),
    ("电流环", "16 kHz，带宽 1 kHz（Kp = L·ωc，Ki = R·ωc）", "", "沿用驱动板 B 版做法"),
    ("速度环", "2 kHz 计算，带宽 40 Hz（Kp = J·ωs/Kt，积分时间 4/ωs）+ 加速度前馈 J·a", "", "159c 推荐值"),
    ("加减速", "0 → 5000 r/min 0.1 s；5000 → 300 r/min 0.12 s", "", "159c 工作周期"),
    ("停针", "位置环 Kp = ωs/4，限速 300 r/min；上针位 70°、下针位 180°", "", "159c；第 138 轮（下针位 = 针杆最低点，G2 机构）"),
    ("剪线", "300 r/min 转一针，剪线电磁铁 200°–330° 吸合", "", "159c、第 138 轮"),
    ("起缝加固", "正 4 针、倒 4 针，1800 r/min", "", "示例（面板可改）"),
    ("脚踏板", "霍尔 0.5–4.5 V：后踩 < 0.9 V、回中 0.9–1.4 V、前踩 1.4 → 4.2 V 对应 200 → 5000 r/min", "", "示例（按脚踏板标定）"),
    ("拨线、抬压脚", "拨线 50 ms；抬压脚最长 10 s", "", "示例"),
    ("堵转保护", "电流顶到上限、转速 < 30 r/min 连续 200 ms", "", "示例"),
]

T0 = 1.3      # 开机就绪以后才踩脚踏（对零 0.3 s + 找 Z 相 + 停上针位，约 1 s）

# 场景：dur 时长；sample [(起, 止, 步长)]；events [(t, 监视器命令 或 ("cfg", 字段, 值))]
SCENARIOS = [
    dict(id="cycle", name="① 与 159c 同一个工作周期", en="Same work cycle as 159c",
         desc="面板设成不加固。脚踏一下踩到底：0.1 s 起到 5000 r/min，缝 0.5 s；直接后踩：0.12 s 减到 300 r/min，转一针剪线，停上针位 70°，"
              "然后拨线、抬压脚。和 159c 的复算（第 138 轮 gc_sim.py 的模型）对照起动时间、松脚踏到停稳、停针误差、剪线时序、相电流。",
         pre=["tim1 StartAngle 123"], cfg=[("bt_fwd", 0), ("bt_rev", 0)], dur=T0 + 1.3,
         sample=[(0.0, T0 - 0.05, 0.01), (T0 - 0.05, T0 + 1.3, 0.001)],
         events=[(T0, "tim1 Pedal 4.2"), (T0 + 0.5, "tim1 Pedal 0.6")]),
    dict(id="seam", name="② 缝一段：起缝加固、半踩、停下针位、剪线、抬压脚", en="Sew a seam",
         desc="默认设置（起缝加固正 4 针、倒 4 针）。脚踏踩一半（霍尔 2.8 V，约 2600 r/min）：先 1800 r/min 正缝 4 针、倒缝电磁铁吸合倒缝 4 针，"
              "再按脚踏转速缝；回中：停下针位 180°（针在布里）；后踩：剪线、停上针位、拨线、抬压脚；松开后踩：压脚放下。",
         pre=["tim1 StartAngle 250"], cfg=[], dur=T0 + 2.1,
         sample=[(0.0, T0 - 0.05, 0.01), (T0 - 0.05, T0 + 2.1, 0.001)],
         events=[(T0, "tim1 Pedal 2.8"), (T0 + 1.0, "tim1 Pedal 1.2"), (T0 + 1.4, "tim1 Pedal 0.6"), (T0 + 1.95, "tim1 Pedal 1.2")]),
    dict(id="jam", name="③ 针卡住：过流保护", en="Needle jammed: overcurrent trip",
         desc="以约 2600 r/min 缝纫中，针卡住、主轴瞬间卡死：反电势一下子没了，电流环来不及收，相电流冲过 7.5 A → 本周期（62.5 µs）就关输出"
              "（MOE 关、功率模块 SD 拉低），报过流，电磁铁全部释放。",
         pre=["tim1 StartAngle 40"], cfg=[("bt_fwd", 0), ("bt_rev", 0)], dur=T0 + 0.5,
         sample=[(0.0, T0 - 0.05, 0.01), (T0 - 0.05, T0 + 0.5, 0.001)],
         events=[(T0, "tim1 Pedal 2.8"), (T0 + 0.3, "tim1 Jam true")]),
    dict(id="stall", name="④ 阻力太大转不动：堵转保护", en="Too much load: stall protection",
         desc="以约 2600 r/min 缝纫中，阻力突然大到 4 N·m（布太厚、线卡住；比电机最大力矩 3.0 N·m 还大）：主轴减速停下，"
              "速度环把电流顶到上限 6.05 A（不到过流阈值），转速 < 30 r/min、连续 200 ms → 报堵转，关输出，电磁铁全部释放。",
         pre=["tim1 StartAngle 300"], cfg=[("bt_fwd", 0), ("bt_rev", 0)], dur=T0 + 1.0,
         sample=[(0.0, T0 - 0.05, 0.01), (T0 - 0.05, T0 + 1.0, 0.001)],
         events=[(T0, "tim1 Pedal 2.8"), (T0 + 0.3, "tim1 ExtraLoad 4.0")]),
]


def sym(name):
    for ln in subprocess.run(["arm-none-eabi-nm", ELF], capture_output=True, text=True, check=True).stdout.splitlines():
        a, _, n = ln.split()
        if n == name:
            return int(a, 16)
    raise SystemExit("找不到符号 " + name)


def resc(sc, A):
    fw = HERE.replace("\\", "/")
    L = ["using sysbus", 'emulation SetGlobalQuantum "0.00001"', 'mach create "ctrl-ls"',
         "include @{}/renode/WqSew.cs".format(fw), "machine LoadPlatformDescription @{}/renode/stm32g431.repl".format(fw),
         "cpu PerformanceInMips 170", "logLevel 3", "tim1 LoadTable @{}/renode/load_table.txt".format(fw)] + sc["pre"] + \
        ["sysbus LoadELF @{}/build/fw.elf".format(fw)]
    samp = set()
    for a, b, h in sc["sample"]:
        n = int(round((b - a) / h))
        samp |= {round(a + k * h, 7) for k in range(n + 1)}
    ev = list(sc["events"])
    # 面板设置：启动代码把 cfg 从 Flash 复制到内存之后再改（0.01 s，电机还在量零点）
    for k, v in sc["cfg"]:
        ev.append((0.01, "sysbus WriteDoubleWord 0x{:08X} {}".format(A["cfg"] + 4 * CFG.index(k), v)))
    ts = sorted(samp | {round(t, 7) for t, _ in ev} | {round(sc["dur"], 7)})
    span = A["sw"] + 4 * len(SWF) - A["mc"]
    now = 0.0
    for t in ts:
        if t > now + 1e-9:
            L.append('emulation RunFor "{:.7f}"'.format(t - now))
            now = t
        for te, a in ev:
            if abs(te - t) < 1e-9:
                L.append(a)
        if t in samp:
            L.append("tim1 Truth")
            L.append("sysbus ReadBytes 0x{:08X} {}".format(A["mc"], span))
    L += ["tim1 SolLog", "quit"]
    return "\n".join(L) + "\n"


def parse(text, A):
    rows, sols = [], []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        ln = lines[i].strip()
        if ln.startswith("M "):
            f = ln.split()[1:]
            j = i + 1
            while not lines[j].strip().startswith("["):
                j += 1
            buf = []
            j += 1
            while not lines[j].strip().startswith("]"):
                buf += [int(x, 16) for x in re.findall(r"0x[0-9A-Fa-f]+", lines[j])]
                j += 1
            b = bytes(buf)
            mc = dict(zip([n for n, _ in MCF], struct.unpack_from("<" + "".join(t for _, t in MCF), b, 0)))
            sw = dict(zip([n for n, _ in SWF], struct.unpack_from("<" + "".join(t for _, t in SWF), b, A["sw"] - A["mc"])))
            rows.append(dict(t=float(f[0]), rpm=float(f[1]), ang=float(f[2]), id=float(f[3]), iq=float(f[4]), ia=float(f[5]),
                             ib=float(f[6]), ic=float(f[7]), on=int(f[8]), vbus=float(f[9]), tm=float(f[10]), tl=float(f[11]),
                             sol=int(f[12]), pedal=float(f[13]), revs=float(f[14]), mc=mc, sw=sw))
            i = j
        elif ln.startswith("S "):
            _, t, k, on, ang = ln.split()
            sols.append(dict(t=float(t), k=int(k), on=int(on), ang=float(ang)))
        i += 1
    return rows, sols


def run_one(renode, sc, A):
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "s.resc")
        with open(p, "w", encoding="utf-8") as f:
            f.write(resc(sc, A))
        r = subprocess.run([renode, "--disable-xwt", "--plain", "--console", "-e", "include @" + p],
                           capture_output=True, text=True, timeout=3600)
    rows, sols = parse(r.stdout, A)
    if not rows or abs(rows[-1]["t"] - sc["dur"]) > 1e-6:
        sys.stderr.write(r.stdout[-3000:] + r.stderr[-2000:])
        raise SystemExit("场景 {} 输出不全".format(sc["id"]))
    return rows, sols


# ---------------------------------------------------------------- 判据
def adiff(a, b):
    return (a - b + 180) % 360 - 180


def pulses(sols, k):
    """电磁铁 k 的每次吸合：[(吸合时刻, 吸合转角, 释放时刻, 释放转角)]"""
    out, on = [], None
    for s in sols:
        if s["k"] != k:
            continue
        if s["on"]:
            on = s
        elif on:
            out.append((on["t"], on["ang"], s["t"], s["ang"]))
            on = None
    if on:
        out.append((on["t"], on["ang"], None, None))
    return out


def settle_after(rows, t0, tol=5.0, hold=0.02):
    """t0 之后第一次转速 < tol r/min 并保持 hold 秒的时刻。159c 用 1 r/min；固件停针保持时主轴有 ±3 r/min、±0.05° 的细小抖动
    （编码器量化 + 死区），1 r/min 判不出停稳，这里用 5 r/min——减速到停的最后几毫秒里转速从 5 降到 1 r/min，对时间的影响不到 1 ms"""
    rr = [r for r in rows if r["t"] >= t0]
    for i, r in enumerate(rr):
        if abs(r["rpm"]) < tol:
            win = [x for x in rr[i:] if x["t"] <= r["t"] + hold]
            if win[-1]["t"] >= r["t"] + hold - 1e-9 and all(abs(x["rpm"]) < tol for x in win):
                return r["t"]
    return None


def check(sc, rows, sols, ref, r2):
    C = []

    def add(name, ok, detail="", vs=""):
        C.append(dict(name=name, ok=bool(ok), detail=detail, vs=vs))

    ready = next((r["t"] for r in rows if r["mc"]["state"] == 3), None)
    add("开机：对零、找到 Z 相、停上针位，踩脚踏前已就绪", ready is not None and ready < T0,
        "{:.3f} s 就绪，停在 {:.2f}°".format(ready, next(r["ang"] for r in rows if r["t"] >= ready)) if ready else "没就绪")
    ipk = max(max(abs(r["ia"]), abs(r["ib"]), abs(r["ic"])) for r in rows if r["t"] >= T0)
    sid = sc["id"]
    if sid == "cycle":
        s = ref["servo"]
        t98 = next((r["t"] for r in rows if r["t"] >= T0 and r["rpm"] >= 0.98 * 5000), None)
        tr = t98 - T0 if t98 else 99
        add("起动到 5000 r/min（98 %）：与 159c 相差 ≤ 10 %", abs(tr / s["t_reach_5000_s"] - 1) <= 0.10,
            "{:.4f} s".format(tr), "159c {:.4f} s，相差 {:+.1f} %".format(s["t_reach_5000_s"], (tr / s["t_reach_5000_s"] - 1) * 100))
        ss = [r["rpm"] for r in rows if T0 + 0.25 <= r["t"] <= T0 + 0.5]
        rip = (max(ss) - min(ss)) / 2 / 5000 * 100
        add("5000 r/min 稳速：转速波动（±%，二倍频由一转负载引起）≤ 3 %", rip <= 3.0, "±{:.2f} %".format(rip),
            "159c 用的模型（速度环 40 Hz、不加负载前馈）±1.47 %")
        td = next((r["t"] for r in rows if r["t"] > T0 + 0.5 and r["rpm"] <= 315), None)
        td = td - (T0 + 0.5) if td else 99
        add("后踩后减到剪线转速（300 r/min +5 %）：与 159c 相差 ≤ 10 %", abs(td / r2["t_decel_300_s"] - 1) <= 0.10, "{:.4f} s".format(td),
            "159c {:.4f} s，相差 {:+.1f} %".format(r2["t_decel_300_s"], (td / r2["t_decel_300_s"] - 1) * 100))
        st = settle_after(rows, T0 + 0.5 + 0.12)
        tf = st - (T0 + 0.5) if st else 99
        # 剪完那一针再停上针位：要转多少度取决于减速完时主轴在哪个角度，两边最多差一圈（300 r/min 一圈 0.2 s）
        add("松脚踏（后踩）到停稳：与 159c 相差不超过剪线转速下的一圈（0.2 s）", abs(tf - s["t_from_release_s"]) <= 0.2,
            "{:.4f} s".format(tf), "159c {:.4f} s，相差 {:+.3f} s".format(s["t_from_release_s"], tf - s["t_from_release_s"]))
        e = adiff(rows[-1]["ang"], 70.0)
        add("停针误差（上针位 70°）≤ 1°", abs(e) <= 1.0, "{:+.3f}°".format(e), "159c {:+.3f}°".format(s["stop_error_deg"]))
        tp = pulses(sols, 0)
        ok = len(tp) == 1 and tp[0][2] is not None and 200 <= tp[0][1] <= 202 and 330 <= tp[0][3] <= 332
        add("剪线电磁铁吸合一次，在 200°–330° 窗口里（固件每 1 ms 看一次角度，300 r/min 时晚 ≤ 1.8°，容差 2°）", ok,
            "；".join("{:.3f} s {:.1f}° 吸合 → {:.3f} s {:.1f}° 释放".format(a, b, c or 0, d or 0) for a, b, c, d in tp))
        if tp:
            rr = [r for r in rows if tp[0][0] <= r["t"] <= tp[0][2]]
            sp = sum(r["rpm"] for r in rr) / max(1, len(rr))
            add("剪线时（电磁铁吸合期间）平均转速：与 159c 相差 ≤ 5 %", abs(sp / r2["trim_rpm_mean"] - 1) <= 0.05, "{:.1f} r/min".format(sp),
                "159c {:.1f} r/min（剪线动刀 0.15 N·m 加上缝纫阻力，速度环把转速拉低一点）".format(r2["trim_rpm_mean"]))
        add("相电流峰值低于过流阈值 7.5 A", ipk < 7.5, "{:.2f} A".format(ipk), "159c {:.2f} A".format(s["i_phase_peak_a"]))
        seq = [(s_["t"], SOL[s_["k"]], s_["on"]) for s_ in sols]
        names = [n + ("吸合" if o else "释放") for _, n, o in seq]
        add("停稳以后才拨线、再抬压脚", names[:4] == ["剪线吸合", "剪线释放", "拨线吸合", "拨线释放"] and "抬压脚吸合" in names
            and st is not None and next(t for t, n, o in seq if n == "拨线" and o) >= st, " → ".join(names))
    if sid == "seam":
        bt = pulses(sols, 2)
        st_rev = [r for r in rows if r["sw"]["state"] in (2, 3)]
        bt_rpm = [r["rpm"] for r in st_rev if r["t"] > st_rev[0]["t"] + 0.05] if st_rev else [0]
        n4 = next((r["revs"] for r in rows if r["sw"]["state"] == 3), 0) - next(r["revs"] for r in rows if r["t"] >= T0)
        add("起缝加固：倒缝电磁铁在第 4 针后吸合、第 8 针后释放（过针杆最高点后 ≤ 12°：固件每 1 ms 看一次，1800 r/min 时 1 ms 转 10.8°）",
            len(bt) == 1 and bt[0][2] is not None and 0 <= bt[0][1] <= 12 and 0 <= bt[0][3] <= 12 and 3 < n4 < 5,
            "；".join("{:.3f} s {:.1f}° 吸合 → {:.3f} s {:.1f}° 释放".format(a, b, c or 0, d or 0) for a, b, c, d in bt))
        add("起缝加固转速 1800 r/min（±3 %）", abs(sum(bt_rpm) / len(bt_rpm) / 1800 - 1) <= 0.03,
            "{:.0f} r/min".format(sum(bt_rpm) / len(bt_rpm)))
        ss = [r["rpm"] for r in rows if T0 + 0.7 <= r["t"] <= T0 + 1.0]
        want = 200 + (2.8 - 1.4) / (4.2 - 1.4) * 4800
        m = sum(ss) / len(ss)
        add("半踩：转速跟脚踏（{:.0f} r/min，平均 ±1 %）".format(want), abs(m / want - 1) <= 0.01,
            "平均 {:.0f} r/min，波动 ±{:.2f} %".format(m, (max(ss) - min(ss)) / 2 / want * 100))
        dn = [r for r in rows if r["sw"]["state"] == 6]
        e = adiff(dn[-1]["ang"], 180.0) if dn else 99
        add("回中：停下针位 180°（≤ 1°）", dn and abs(e) <= 1.0,
            "{:.3f} s 停稳，{:+.3f}°".format(dn[0]["t"], e) if dn else "没停下针位")
        tp = pulses(sols, 0)
        add("后踩：剪线电磁铁在 200°–330° 吸合一次", len(tp) == 1 and tp[0][2] is not None and 200 <= tp[0][1] <= 202 and 330 <= tp[0][3] <= 332,
            "；".join("{:.3f} s {:.1f}° 吸合 → {:.3f} s {:.1f}° 释放".format(a, b, c or 0, d or 0) for a, b, c, d in tp))
        e2 = adiff(rows[-1]["ang"], 70.0)
        add("剪线后停上针位 70°（≤ 1°）", abs(e2) <= 1.0, "{:+.3f}°".format(e2))
        names = [SOL[s_["k"]] + ("吸合" if s_["on"] else "释放") for s_ in sols]
        add("顺序：倒缝 → 剪线 → 拨线 → 抬压脚；松开后踩压脚放下",
            names == ["倒缝吸合", "倒缝释放", "剪线吸合", "剪线释放", "拨线吸合", "拨线释放", "抬压脚吸合", "抬压脚释放"], " → ".join(names))
        fo = pulses(sols, 3)
        add("压脚在松开后踩后 ≤ 2 ms 放下", fo and fo[0][2] is not None and 0 <= fo[0][2] - (T0 + 1.95) <= 0.002,
            "{:.1f} ms".format((fo[0][2] - (T0 + 1.95)) * 1000) if fo and fo[0][2] else "")
        n = rows[-1]["sw"]["seam_stitches"]
        add("这条缝的针数与主轴真实转过的圈数一致", n == int(rows[-1]["revs"]) - int(next(r["revs"] for r in rows if r["t"] >= T0)),
            "固件数 {} 针".format(n))
        add("相电流峰值低于过流阈值 7.5 A", ipk < 7.5, "{:.2f} A".format(ipk))
    if sid == "jam":
        aft = [r for r in rows if r["t"] >= T0 + 0.3]
        off = next((r for r in aft if r["on"] == 0), None)
        m = rows[-1]["mc"]
        add("报过流：卡住后 5 ms 内关输出（功率模块 SD 拉低），关断那一刻测到的相电流超过 7.5 A",
            off is not None and off["t"] - (T0 + 0.3) <= 0.005 and m["fault"] == 1 and m["fault_val"] > 7.5,
            "{:.0f} ms 内，故障：{}，关断时测到 {:.2f} A".format((off["t"] - T0 - 0.3) * 1000, FAULT[m["fault"]], m["fault_val"]) if off else "没关")
        add("关输出后电流降到 0、电磁铁全部释放", abs(rows[-1]["iq"]) < 0.01 and rows[-1]["sol"] == 0 and rows[-1]["sw"]["state"] == 10,
            "iq {:.3f} A，缝纫状态：{}".format(rows[-1]["iq"], SWSTATE[rows[-1]["sw"]["state"]]))
    if sid == "stall":
        aft = [r for r in rows if r["t"] >= T0 + 0.3]
        stop = next((r for r in aft if abs(r["rpm"]) < 30), None)
        off = next((r for r in aft if r["on"] == 0), None)
        m = rows[-1]["mc"]
        add("报堵转：转速降到 30 r/min 以下后 200 ms（±5 ms）关输出", stop and off and abs(off["t"] - stop["t"] - 0.2) <= 0.005 and m["fault"] == 3,
            "{:.0f} ms 降到 30 r/min 以下，再过 {:.0f} ms 关输出，故障：{}".format((stop["t"] - T0 - 0.3) * 1000, (off["t"] - stop["t"]) * 1000,
                                                                     FAULT[m["fault"]]) if stop and off else "没关")
        add("堵着期间电流顶在上限、没有过流（< 7.5 A）", ipk < 7.5, "相电流峰值 {:.2f} A".format(ipk))
        add("关输出后电流降到 0、电磁铁全部释放", abs(rows[-1]["iq"]) < 0.01 and rows[-1]["sol"] == 0 and rows[-1]["sw"]["state"] == 10,
            "iq {:.3f} A，缝纫状态：{}".format(rows[-1]["iq"], SWSTATE[rows[-1]["sw"]["state"]]))
    return C


# ---------------------------------------------------------------- 主程序
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--renode", default=os.environ.get("RENODE") or shutil.which("renode") or "/opt/renode/renode")
    ap.add_argument("--no-build", action="store_true")
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    if not a.no_build:
        subprocess.run(["make", "-s", "-C", HERE], check=True, capture_output=True)
    A = {k: sym(k) for k in ("mc", "sw", "cfg")}
    with open(REF, encoding="utf-8") as f:
        ref = json.load(f)
    with open(os.path.join(OUT, "ref_159c.json"), encoding="utf-8") as f:
        r2 = json.load(f)
    res = []
    for sc in SCENARIOS:
        if a.only and sc["id"] not in a.only.split(","):
            continue
        rows, sols = run_one(a.renode, sc, A)
        checks = check(sc, rows, sols, ref, r2)
        rr = [r for r in rows if r["t"] >= T0 - 0.05]
        S = dict(t=[round(r["t"], 4) for r in rr], rpm=[round(r["rpm"], 1) for r in rr], rpm_ref=[round(r["mc"]["speed_ref"], 1) for r in rr],
                 ang=[round(r["ang"], 2) for r in rr], iq=[round(r["iq"], 3) for r in rr], tm=[round(r["tm"], 3) for r in rr],
                 tl=[round(r["tl"], 3) for r in rr], sol=[r["sol"] for r in rr], pedal=[round(r["pedal"], 2) for r in rr],
                 state=[r["sw"]["state"] for r in rr], on=[r["on"] for r in rr],
                 ipk=[round(max(abs(r["ia"]), abs(r["ib"]), abs(r["ic"])), 3) for r in rr])
        boot = [r for r in rows if r["t"] < T0]
        B = dict(t=[round(r["t"], 3) for r in boot], rpm=[round(r["rpm"], 1) for r in boot], ang=[round(r["ang"], 2) for r in boot],
                 state=[r["mc"]["state"] for r in boot])
        res.append(dict(id=sc["id"], name=sc["name"], en=sc["en"], desc=sc["desc"], events=[[t, e] for t, e in sc["events"]],
                        cfg=[[k, v] for k, v in sc["cfg"]], checks=checks, series=S, boot=B,
                        solenoids=[dict(t=round(s["t"], 6), name=SOL[s["k"]], on=s["on"], ang=round(s["ang"], 2)) for s in sols],
                        passed=all(c["ok"] for c in checks)))
        print("{} {}：{}".format("✓" if res[-1]["passed"] else "✗", sc["name"],
                                "；".join(("" if c["ok"] else "✗ ") + c["name"] + (" " + c["detail"] if c["detail"] else "") for c in checks)))
    if a.only:
        return 0
    size = subprocess.run(["arm-none-eabi-size", ELF], capture_output=True, text=True, check=True).stdout.splitlines()[1].split()
    out = dict(round=159, title="平缝机控制器 CTRL-LS 示例固件：磁场定向控制 + 缝纫状态机，Renode 里接第 138 轮 G2 一转负载缝一段",
               firmware=dict(text=int(size[0]), data=int(size[1]), bss=int(size[2]), flash=int(size[0]) + int(size[1]),
                             ram=int(size[1]) + int(size[2])),
               addr={k: "0x{:08X}".format(v) for k, v in A.items()}, t0=T0,
               params=[dict(name=n, value=v, unit=u, source=s) for n, v, u, s in PARAMS],
               states=SWSTATE, scenarios=res, all_pass=all(s["passed"] for s in res),
               disclaimer="示例固件，仿真验证；电机未选型，极对数、电阻、电感是示例值；不能直接用于产品。")
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "sim_sew.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print("全部通过" if out["all_pass"] else "有场景没通过")
    return 0 if out["all_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
