# -*- coding: utf-8 -*-
"""第 102 轮：驱动板 B 版固件的电机控制与 CAN，在 Renode 里跑场景（第 102 轮六个、第 107 轮四个、第 110 轮四个），逐一核对，写 out/sim_motor.json。

用法：python3 run_motor.py [--renode /opt/renode/renode] [--no-build]
每个场景起一台仿真机：STM32G431（真固件 fw.elf）+ WQ-ENCIF + TIM1/ADC1/FDCAN1 + 电机、减速器、摆臂（renode/WqDrive.cs）。
仿真 CAN 主站按时间表发指令（运行中每 50 ms 发一次，保持通信）、按时间表注入故障；
按采样表读电机真值（tim1 Truth）和固件内存里的电机控制遥测区 mc；最后取 CAN 总线记录。判据都对物理真值。"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
ELF = os.path.join(HERE, "build", "fw.elf")
CPR, P, GEAR = 10000, 5, 100

MCF = [("magic", "I"), ("state", "I"), ("mode", "I"), ("fault", "I"), ("align_off", "i"), ("isr", "I"), ("id", "f"), ("iq", "f"),
       ("id_ref", "f"), ("iq_ref", "f"), ("vd", "f"), ("vq", "f"), ("speed_rpm", "f"), ("speed_ref", "f"), ("pos_cnt", "i"),
       ("pos_ref_cnt", "i"), ("vbus", "f"), ("imax", "f"), ("moe", "I"), ("can_rx", "I"), ("can_tx", "I"), ("fault_val", "f"),
       # 第 107 轮
       ("abs_mdeg", "i"), ("home_cnt", "i"), ("home_mdeg", "i"), ("homed", "I"), ("mismatch_mdeg", "i"), ("ssi_bad", "I"),
       ("hold", "I"), ("hold_keep", "I"),
       # 第 110 轮
       ("brake_cmd", "I"), ("brake_ok", "I"), ("pend", "I")]
STATE = {0: "初始化（对零）", 1: "就绪", 2: "运行", 3: "故障"}
FAULT = {0: "无", 1: "过流", 2: "欠压", 3: "编码器", 4: "通信超时", 5: "输出端编码器", 6: "减速器 / 编码器不一致"}
MODE = {0: "停", 1: "速度", 2: "位置", 3: "清故障", 4: "力矩"}

# 参数表：来源“零件库”“第 88 轮”“示例”
PARAMS = [
    ("母线电压", "48", "V", "第 88 轮驱动板设计"),
    ("力矩常数 Kt", "0.15", "N·m/A", "第 88 轮示例电机"),
    ("额定力矩", "1.27", "N·m", "第 88 轮示例电机（额定电流 ≈ 8.5 A）"),
    ("极对数", "5", "", "示例"),
    ("相电阻", "0.12", "Ω", "示例"),
    ("相电感", "0.2", "mH", "示例（电气时间常数 L/R = 1.67 ms）"),
    ("转子惯量", "4.86×10⁻⁵", "kg·m²", "示例：取零件库同功率等级安川 SGM7J-04A 的值"),
    ("减速比", "100", "", "零件库：Harmonic Drive CSF-17-100"),
    ("减速器额定力矩", "24", "N·m", "零件库：Harmonic Drive CSF-17-100"),
    ("摆臂", "1 kg @ 0.3 m（重力矩最大 2.94 N·m）", "", "示例"),
    ("摩擦（电机侧）", "粘滞 1×10⁻⁵ N·m·s/rad、库仑 0.01 N·m", "", "示例"),
    ("采样电阻 × 放大", "2 mΩ × 20 = 40 mV/A，零点 1.65 V", "", "第 88 轮驱动板设计"),
    ("母线分压", "6.8 / 108.8", "", "第 88 轮驱动板设计"),
    ("死区", "200", "ns", "第 88 轮驱动板设计"),
    ("编码器", "2500 线 ×4 = 10000 计数/转", "", "第 88 轮示例编码器"),
    ("PWM / 电流环", "20 kHz", "", "本轮固件"),
    ("电流环带宽", "1 kHz（Kp = L·ωc，Ki = R·ωc）", "", "本轮固件"),
    ("速度环带宽", "100 Hz（Kp = J·ωs/Kt，Ki = Kp·ωs/4）", "", "本轮固件"),
    ("位置环", "Kp = ωs/4 ≈ 157 /s，梯形轨迹 1500 rpm、3000 rad/s²", "", "本轮固件"),
    ("过流 / 欠压阈值", "25 A / 36 V", "", "本轮固件"),
    ("输出端绝对值编码器", "SSI 17 位单圈（131 072 计数/圈）、1.33 MHz、1 kHz 读", "", "示例（第 107 轮；电路是第 88 轮的 J4 + RS-485）"),
    ("双编码器互检阈值", "0.5°、连续 10 ms", "", "示例（第 107 轮）"),
    ("抱闸", "失电制动，线圈 24 V / 0.42 A、时间常数 25 ms；静摩擦 2.0 N·m、动摩擦 1.6 N·m（电机侧）", "", "示例（第 110 轮）"),
    ("抱闸驱动", "母线 PWM 20 kHz：松闸先 100% 50 ms，再保持平均 24 V；松开、抱住各按 60 ms 算", "", "示例（第 110 轮）"),
]


def cmd(mode, target=0):
    d = struct.pack("<Bi", mode, int(target))
    return d.hex().upper()


# 场景：dur 时长；sample [(起, 止, 步长)]；events [(t, 动作)]，动作是监视器命令，或 ("cmd", 模式, 目标, 保持)
SCENARIOS = [
    dict(id="boot", name="① 上电对零", en="Power-up & alignment",
         desc="开机时转子停在电角度约 100° 处（关节 0.2°）。固件量电流零点、在 d 轴通 3 A 把转子拉到电角度 0°、记下编码器偏移，CAN 报“就绪”。",
         pre=["tim1 StartJoint 0.2"], dur=0.45, sample=[(0, 0.45, 0.005)], events=[]),
    dict(id="cur", name="② 电流环阶跃", en="Current-loop step",
         desc="转子堵住（堵转试验），CAN 发力矩指令 q 轴 2 A，看电流响应：上升时间、超调。"
              "（第 110 轮起：指令 0.44 s 发出，固件先在原地稳住、松闸，60 ms 后 0.50 s 加电流。）",
         pre=[], dur=0.52, sample=[(0.45, 0.4995, 0.005), (0.4995, 0.506, 0.0001), (0.506, 0.52, 0.002)],
         events=[(0.44, "tim1 LockRotor true"), (0.44, ("cmd", 4, 2000, True)), (0.51, ("cmd", 0, 0, False))]),
    dict(id="spd", name="③ 速度环", en="Speed loop",
         desc="CAN 发速度指令：电机 1500 rpm（关节 15 rpm）。看起转和稳态误差。（第 110 轮起：指令 0.39 s 发出，先松闸 60 ms，0.45 s 起转。）",
         pre=[], dur=0.95, sample=[(0.4, 0.95, 0.005)], events=[(0.39, ("cmd", 1, 1500, True))]),
    dict(id="pos", name="④ 位置环：转 90°", en="Position move 90°",
         desc="CAN 发位置指令：关节转到 90°（电机 25 圈）。梯形轨迹 + 位置环 + 速度环；到 90° 时摆臂水平，重力矩最大。",
         pre=[], dur=1.9, sample=[(0.4, 1.9, 0.01)], events=[(0.45, ("cmd", 2, 90000, True))]),
    dict(id="hold", name="⑤ 重力下保持、加负载", en="Hold under gravity, add payload",
         desc="摆臂停在 90°（水平）后，1.9 s 时末端突然多挂 0.5 kg（输出端多 1.47 N·m），看位置偏多少、多久回来、电流多了多少。",
         pre=[], dur=2.45, sample=[(0.4, 1.88, 0.01), (1.88, 2.05, 0.002), (2.05, 2.45, 0.01)],
         events=[(0.45, ("cmd", 2, 90000, True)), (1.9, "tim1 ExtraMass 0.5")]),
    dict(id="prot", name="⑥ 保护", en="Protection",
         desc="600 rpm 运行中依次注入：A–B 相间短路 → 过流；清故障再转；编码器芯片不响应 → 编码器故障；芯片恢复、清故障、重新对零；"
              "只发一次指令后不再发 → 通信超时（第 107 轮起减速停住、保持不断电）；清故障后母线掉到 30 V → 欠压（停住后关输出）。",
         pre=[], dur=1.85, sample=[(0.4, 1.85, 0.005)],
         events=[(0.45, ("cmd", 1, 600, True)), (0.6, "tim1 ShortAB true"), (0.62, "tim1 ShortAB false"),
                 (0.62, ("cmd", 0, 0, False)), (0.65, ("cmd", 3, 0, False)), (0.7, ("cmd", 1, 600, True)),
                 (0.85, "spi1.encif Absent true"), (0.9, "spi1.encif Absent false"), (0.9, ("cmd", 0, 0, False)),
                 (1.05, ("cmd", 3, 0, False)), (1.45, ("cmd", 1, 600, False)), (1.65, ("cmd", 3, 0, False)),
                 (1.7, "tim1 SetVbus 30")]),
    # 第 107 轮：输出端绝对值编码器、互检、受控停车
    dict(id="abs", name="⑦ 开机读绝对位置", en="Absolute position at power-up",
         desc="这个关节在水平面里转（像 SCARA 机器人第一轴，没有重力矩），开机时停在 37.5°。固件对零后读输出端绝对值编码器回原点，"
              "CAN 直接报 37.5°；指令 90° 只走 52.5°。（第 102 轮的固件会把这里当 0°、走 90° 到 127.5°。）",
         pre=["tim1 StartJoint 37.5", "tim1 ExtraMass -1"], dur=1.3, sample=[(0.3, 1.3, 0.01)], events=[(0.45, ("cmd", 2, 90000, True))]),
    dict(id="ssi", name="⑧ 输出端编码器线断", en="Absolute encoder cable broken",
         desc="300 rpm 运行中 0.6 s 输出端编码器的线断了（读回全 1）：连续 5 帧读坏 → 故障 5、立即关输出。",
         pre=[], dur=0.75, sample=[(0.4, 0.75, 0.002)], events=[(0.45, ("cmd", 1, 300, True)), (0.6, "spi3.ssi Broken true")]),
    dict(id="slip", name="⑨ 减速器打滑", en="Gearbox slip",
         desc="关节转到 20° 停住后，0.9 s 时减速器打滑：输出轴相对电机轴突然错开 2°（电机侧编码器看不到，输出端编码器看得到）"
              "→ 两个编码器差 2° 超过 0.5°、连续 10 ms → 故障 6、立即关输出。",
         pre=[], dur=1.05, sample=[(0.4, 1.05, 0.002)], events=[(0.45, ("cmd", 2, 20000, True)), (0.9, "tim1 Slip 2")]),
    dict(id="stop", name="⑩ 受控停车", en="Controlled stop",
         desc="摆臂停在 90°（水平）后，1.6 s 起主站不再发指令：约 100 ms 后报通信超时，固件减速停住、保持位置不断电，摆臂不落；"
              "2.6 s 母线掉到 30 V：保持不住，停住、抱闸，抱住后关输出——摆臂不落（第 107 轮板上没有抱闸，这里摆臂落到 75°；第 110 轮加了抱闸）。",
         pre=[], dur=3.0, sample=[(0.4, 3.0, 0.01)], events=[(0.45, ("cmd", 2, 90000, True)), (1.6, ("cmd", 2, 90000, False)),
                                                             (2.6, "tim1 SetVbus 30")]),
    # 第 110 轮：抱闸
    dict(id="brk_boot", name="⑪ 上电抱着、先稳住再松闸", en="Brake at power-up, hold before release",
         desc="开机时摆臂停在 60°（有重力）。上电抱闸抱着；对零时松闸（d 轴电流把转子定住），对零完先抱闸、抱住后关输出，摆臂不动。"
              "0.45 s 指令 90°：固件先开输出、位置环停在原地，再松闸，60 ms 后才走轨迹——松闸那一下摆臂不掉。",
         pre=["tim1 StartJoint 60"], dur=1.4, sample=[(0.0, 0.3, 0.01), (0.3, 0.6, 0.005), (0.6, 1.4, 0.01)],
         events=[(0.45, ("cmd", 2, 90000, True))]),
    dict(id="brk_uv", name="⑫ 欠压：停住、抱闸、关输出", en="Undervoltage: stop, brake, power off",
         desc="摆臂停在 90°（水平，重力矩最大）后，1.7 s 母线掉到 30 V：报欠压，停住、抱闸，抱住后才关输出——摆臂不落。",
         pre=[], dur=2.8, sample=[(0.4, 1.68, 0.01), (1.68, 1.9, 0.005), (1.9, 2.8, 0.02)],
         events=[(0.45, ("cmd", 2, 90000, True)), (1.7, "tim1 SetVbus 30")]),
    dict(id="brk_ssi", name="⑬ 危险故障：关输出同时抱闸", en="Dangerous fault: power off and brake at once",
         desc="摆臂停在 90° 后，1.7 s 输出端编码器线断：故障 5 立即关输出、同时抱闸。线圈电流要几十毫秒才降到释放值，摆臂先落一点再被抱住。",
         pre=[], dur=2.8, sample=[(0.4, 1.68, 0.01), (1.68, 1.72, 0.001), (1.72, 1.9, 0.005), (1.9, 2.8, 0.02)],
         events=[(0.45, ("cmd", 2, 90000, True)), (1.7, "spi3.ssi Broken true")]),
    dict(id="brk_stop", name="⑭ “停”：停住、抱闸、关输出", en="Stop command: stop, brake, power off",
         desc="摆臂停在 90° 后，1.7 s 主站发“停”：固件停住、抱闸，抱住后关输出、回到就绪——摆臂不落（第 102 轮的固件收到“停”立即关输出）。",
         pre=[], dur=2.8, sample=[(0.4, 1.68, 0.01), (1.68, 1.9, 0.005), (1.9, 2.8, 0.02)],
         events=[(0.45, ("cmd", 2, 90000, True)), (1.7, ("cmd", 0, 0, False))]),
]


# ---------------------------------------------------------------- 跑 Renode
def timeline(sc):
    ts = set()
    for a, b, h in sc["sample"]:
        n = int(round((b - a) / h))
        for k in range(n + 1):
            ts.add(round(a + k * h, 7))
    ev = []
    keep = None
    for t, a in sorted(sc["events"], key=lambda x: x[0]):
        ev.append((t, a))
    # 保持通信：运行中的指令每 50 ms 再发一次，直到下一条指令
    out = []
    evs = sorted(ev, key=lambda x: x[0])
    for i, (t, a) in enumerate(evs):
        out.append((t, a))
        if isinstance(a, tuple) and a[3]:
            nxt = next((u for u, b in evs[i + 1:] if isinstance(b, tuple)), sc["dur"])
            k = 1
            while t + 0.05 * k < nxt - 1e-9:
                out.append((round(t + 0.05 * k, 7), ("cmd", a[1], a[2], False)))
                k += 1
    for t, _ in out:
        ts.add(round(t, 7))
    ts.add(round(sc["dur"], 7))
    return sorted(ts), sorted(out, key=lambda x: x[0])


def resc(sc, mc_addr):
    fw = HERE.replace("\\", "/")
    L = ["using sysbus", 'emulation SetGlobalQuantum "0.00001"', 'mach create "drv-joint-b"',
         "include @{}/renode/WqEncif.cs".format(fw), "include @{}/renode/WqDrive.cs".format(fw),
         "machine LoadPlatformDescription @{}/renode/stm32g431.repl".format(fw),
         'machine LoadPlatformDescriptionFromString "encif: SPI.WqEncif @ spi1"',
         'machine LoadPlatformDescriptionFromString "gpioPortA: { 4 -> encif@0 }"',
         'machine LoadPlatformDescriptionFromString "gpioPortB: { 1 -> encif@1 }"',
         "cpu PerformanceInMips 170", "logLevel 3"] + sc["pre"] + ['spi1.encif UseMotor "tim1"', "sysbus LoadELF @{}/build/fw.elf".format(fw)]
    ts, ev = timeline(sc)
    samp = set()
    for a, b, h in sc["sample"]:
        n = int(round((b - a) / h))
        samp |= {round(a + k * h, 7) for k in range(n + 1)}
    now = 0.0
    for t in ts:
        if t > now + 1e-9:
            L.append('emulation RunFor "{:.7f}"'.format(t - now))
            now = t
        for te, a in ev:
            if abs(te - t) < 1e-9:
                if isinstance(a, tuple):
                    L.append('fdcan1 HostSend 0x201 "{}"'.format(cmd(a[1], a[2])))
                else:
                    L.append(a)
        if t in samp:
            L.append("tim1 Truth")
            L.append("sysbus ReadBytes 0x{:08X} {}".format(mc_addr, 4 * len(MCF)))
    L += ["fdcan1 HostLog", "quit"]
    return "\n".join(L) + "\n"


def parse(text):
    rows, frames = [], []
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
            v = struct.unpack("<" + "".join(t for _, t in MCF), bytes(buf))
            rows.append(dict(t=float(f[0]), id=float(f[1]), iq=float(f[2]), rpm=float(f[3]), joint=float(f[4]), ia=float(f[5]),
                             ib=float(f[6]), moe=int(f[7]), vbus=float(f[8]), mcnt=float(f[9]), off=float(f[10]), the=float(f[11]), iqi=float(f[12]),
                             bi=float(f[13]), bopen=int(f[14]),
                             mc=dict(zip([n for n, _ in MCF], v))))
            i = j
        elif ln.startswith("F "):
            _, t, d, cid, data = (ln.split() + [""])[:5]
            frames.append(dict(t=float(t), dir=d, id=int(cid, 16), data=data))
        i += 1
    return rows, frames


def run_one(renode, sc, addr):
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "s.resc")
        open(p, "w", encoding="utf-8").write(resc(sc, addr))
        r = subprocess.run([renode, "--disable-xwt", "--plain", "--console", "-e", "include @" + p],
                           capture_output=True, text=True, timeout=900)
    rows, frames = parse(r.stdout)
    if not rows or abs(rows[-1]["t"] - sc["dur"]) > 1e-6:
        sys.stderr.write(r.stdout[-3000:] + r.stderr[-2000:])
        raise SystemExit("场景 {} 输出不全".format(sc["id"]))
    return rows, frames


# ---------------------------------------------------------------- CAN 帧解释
def decode(f):
    b = bytes.fromhex(f["data"]) if f["data"] else b""
    i16 = lambda k: struct.unpack_from("<h", b, k)[0]  # noqa: E731
    if f["id"] == 0x201 and len(b) >= 5:
        m, tg = b[0], struct.unpack_from("<i", b, 1)[0]
        unit = {1: "{} rpm".format(tg), 2: "关节 {:.3f}°".format(tg / 1000), 4: "q 轴 {:.3f} A".format(tg / 1000)}.get(m, "")
        return "指令：{} {}".format(MODE.get(m, m), unit).strip()
    if f["id"] == 0x181 and len(b) == 8:
        return "状态：{}，故障 {}，关节 {:.2f}°，电机 {} rpm，iq {:.2f} A".format(STATE.get(b[0], b[0]), FAULT.get(b[1], b[1]), i16(2) / 100, i16(4), i16(6) / 100)
    if f["id"] == 0x081 and len(b) >= 3:
        return "报警：{}（{:.2f}）".format(FAULT.get(b[0], b[0]), i16(1) / 100)
    if f["id"] == 0x701 and len(b) >= 3:
        return "心跳：{}，母线 {:.1f} V{}".format(STATE.get(b[0], b[0]), struct.unpack_from("<H", b, 1)[0] / 10,
                                             "，抱闸{}".format("松开" if b[3] else "抱住") if len(b) >= 4 else "")
    return ""


# ---------------------------------------------------------------- 判据
def check(sc, rows, frames):
    C = []

    def add(name, ok, detail=""):
        C.append(dict(name=name, ok=bool(ok), detail=detail))

    def at(t):
        return min(rows, key=lambda r: abs(r["t"] - t))

    tx = [f for f in frames if f["dir"] == "tx"]
    st = [f for f in tx if f["id"] == 0x181]
    em = [f for f in tx if f["id"] == 0x081]
    last = rows[-1]
    sid = sc["id"]
    if sid == "boot":
        rd = [f for f in st if bytes.fromhex(f["data"])[0] == 1]
        add("对零完成、CAN 状态帧报“就绪”", rd and rd[0]["t"] <= 0.4 and last["mc"]["state"] == 1,
            "{:.3f} s 起报就绪".format(rd[0]["t"]) if rd else "没报")
        m = last["mc"]
        efw = ((m["pos_cnt"] - m["align_off"]) % (CPR // P)) / (CPR // P) * 360
        d = (efw - last["the"] + 180) % 360 - 180
        add("对零准确：固件算的电角度与真实电角度差 ≤ 2°（电角度）", abs(d) <= 2, "差 {:.2f}°".format(d))
        hb = [f for f in tx if f["id"] == 0x701]
        v = struct.unpack_from("<H", bytes.fromhex(hb[-1]["data"]), 1)[0] / 10 if hb else 0
        add("心跳帧 10 Hz、母线读数 48 V（±0.5 V）", len(hb) >= 4 and abs(v - 48) <= 0.5, "{} 帧，{:.1f} V".format(len(hb), v))
        add("对零后关管、电流为零", m["moe"] == 0 and abs(last["iq"]) < 0.05 and abs(last["id"]) < 0.05,
            "id {:.3f} A、iq {:.3f} A".format(last["id"], last["iq"]))
    if sid == "cur":
        t0 = 0.5
        step = [r for r in rows if t0 <= r["t"] <= 0.506]
        iq = [(r["t"] - t0, r["iq"]) for r in step]
        t10 = next((t for t, v in iq if v >= 0.2), None)
        t90 = next((t for t, v in iq if v >= 1.8), None)
        rise = (t90 - t10) * 1000 if t10 is not None and t90 is not None else 99
        pk = max(v for _, v in iq)
        add("上升时间（10 %→90 %）≤ 1 ms", rise <= 1.0, "{:.2f} ms".format(rise))
        add("超调 ≤ 10 %", pk <= 2.2, "峰值 {:.3f} A（{:.1f} %）".format(pk, (pk / 2 - 1) * 100))
        e = at(0.505)["iq"]
        add("5 ms 时稳态误差 ≤ 2 %", abs(e - 2) <= 0.04, "{:.3f} A".format(e))
        add("堵转：转子没动", max(abs(r["rpm"]) for r in rows if r["t"] >= 0.45) < 0.01, "")
    if sid == "spd":
        ss = [r for r in rows if r["t"] >= 0.65]
        e = max(abs(r["rpm"] - 1500) for r in ss)
        add("稳态（0.65 s 起）转速误差 ≤ 1 %（15 rpm）", e <= 15, "最大误差 {:.2f} rpm".format(e))
        t90 = next((r["t"] for r in rows if r["rpm"] >= 1350), None)
        add("起转：到 90 %（1350 rpm）用时 ≤ 50 ms（从松闸完、0.45 s 起算）", t90 is not None and t90 - 0.45 <= 0.05,
            "{:.1f} ms".format((t90 - 0.45) * 1000) if t90 else "没到")
        fe = max(abs(r["mc"]["speed_rpm"] - r["rpm"]) for r in ss)
        add("固件的转速估计与真值差 ≤ 1 %", fe <= 15, "最大差 {:.2f} rpm".format(fe))
        s2 = [f for f in st if f["t"] >= 0.65]
        cs = [struct.unpack_from("<h", bytes.fromhex(f["data"]), 4)[0] for f in s2]
        add("CAN 状态帧报的转速 ≈ 1500 rpm", cs and max(abs(x - 1500) for x in cs) <= 15, "{}–{} rpm".format(min(cs), max(cs)) if cs else "")
    if sid in ("pos", "hold"):
        pre = [r for r in rows if r["t"] <= (1.58 if sid == "hold" else 9)]
        ov = max(r["joint"] for r in pre) - 90
        reach = next((r["t"] for r in rows if abs(r["joint"] - 90) <= 0.05), None)
    if sid == "pos":
        add("到位误差 ≤ 0.05°", abs(last["joint"] - 90) <= 0.05, "{:.4f}°".format(last["joint"] - 90))
        add("超调 ≤ 2°", ov <= 2, "{:.3f}°".format(max(ov, 0)))
        add("走完 90°（进 ±0.05°）用时", reach is not None, "{:.2f} s（指令在 0.45 s）".format(reach - 0.45) if reach else "没到")
        s2 = [f for f in st if f["t"] >= 1.8]
        ca = struct.unpack_from("<h", bytes.fromhex(s2[-1]["data"]), 2)[0] / 100 if s2 else 0
        add("CAN 状态帧报的关节角与真值差 ≤ 0.02°", s2 and abs(ca - at(s2[-1]["t"])["joint"]) <= 0.02, "{:.2f}°".format(ca))
    if sid == "hold":
        b = at(1.88)
        add("加负载前：保持在 90°（≤ 0.05°）", abs(b["joint"] - 90) <= 0.05, "{:.4f}°".format(b["joint"] - 90))
        aft = [r for r in rows if r["t"] >= 1.9]
        dev = max(abs(r["joint"] - 90) for r in aft)
        add("加 0.5 kg 后最大偏差（记录）", True, "{:.4f}°".format(dev))
        back = next((r["t"] for r in aft if r["t"] > 1.91 and all(abs(x["joint"] - 90) <= 0.05 for x in aft if x["t"] >= r["t"])), None)
        add("0.3 s 内回到 ±0.05° 并一直保持", back is not None and back - 1.9 <= 0.3,
            "{:.0f} ms".format((back - 1.9) * 1000) if back else "没回来")
        add("结束时误差 ≤ 0.05°", abs(last["joint"] - 90) <= 0.05, "{:.4f}°".format(last["joint"] - 90))

        # 停着时位置环在 ±1 计数间来回微动（编码器量化），电流跟着抖：用电机仿真里 ∫iq dt 求一段时间的精确平均
        def mean_iq(t0, t1):
            a, b = at(t0), at(t1)
            return (b["iqi"] - a["iqi"]) / (b["t"] - a["t"])
        m0, m1 = mean_iq(1.65, 1.88), mean_iq(2.2, 2.45)
        w0 = [r["iq"] for r in rows if 1.65 <= r["t"] <= 1.88]
        add("加负载前平均电流 ≈ 重力矩 2.94 N·m ÷ 100 ÷ Kt = 0.196 A（±25 %）", 0.147 <= m0 <= 0.245,
            "{:.3f} A（停着时位置环在 ±1 计数间微动，电流在 {:.2f}～{:.2f} A 间抖）".format(m0, min(w0), max(w0)))
        add("q 轴平均电流随负载增加（多扛 1.47 N·m ÷ 100 ÷ Kt ≈ 0.098 A，±25 %）", 0.073 <= m1 - m0 <= 0.123,
            "{:.3f} → {:.3f} A".format(m0, m1))
    if sid == "prot":
        def em_after(t, code):
            return next((f for f in em if f["t"] >= t and bytes.fromhex(f["data"])[0] == code), None)

        def state_at(t):
            return at(t)["mc"]["state"]
        offs = sorted({round(r["off"], 7) for r in rows if r["off"] >= 0.6})
        dt = (offs[0] - 0.6) * 1e6 if offs else 1e9
        add("过流：短路后 1 个 PWM 周期（50 µs）内关管", dt <= 50, "{:.1f} µs".format(dt))
        e1 = em_after(0.6, 1)
        add("过流：CAN 报警 0x081 故障码 1", e1 is not None, decode(e1) if e1 else "")
        add("清故障后能再转（0.8 s 运行、600 rpm）", state_at(0.8) == 2 and abs(at(0.8)["rpm"] - 600) <= 6, "{:.1f} rpm".format(at(0.8)["rpm"]))
        e3 = em_after(0.85, 3)
        add("编码器芯片不响应：停机、CAN 报警故障码 3", e3 is not None and e3["t"] - 0.85 <= 0.005 and at(0.86)["moe"] == 0,
            "{:.1f} ms 后报".format((e3["t"] - 0.85) * 1000) if e3 else "")
        add("芯片恢复、清故障后重新对零，回到就绪", state_at(1.42) == 1, STATE[state_at(1.42)])
        e4 = em_after(1.45, 4)
        add("只发一次指令：约 100 ms 后报通信超时（故障码 4）", e4 is not None and 0.09 <= e4["t"] - 1.45 <= 0.12,
            "{:.0f} ms".format((e4["t"] - 1.45) * 1000) if e4 else "")
        e2 = em_after(1.7, 2)
        add("母线掉到 30 V：10 ms 内报欠压（故障码 2）", e2 is not None and e2["t"] - 1.7 <= 0.01,
            decode(e2) if e2 else "")
        add("结束时停在故障、关管", last["mc"]["state"] == 3 and last["moe"] == 0, FAULT[last["mc"]["fault"]])
        add("通信超时后受控停车：输出没关（第 107 轮）", at(1.6)["moe"] == 1 and at(1.6)["mc"]["hold"] == 1,
            "1.6 s：输出 {}，保持 {}".format(at(1.6)["moe"], at(1.6)["mc"]["hold"]))
    if sid == "abs":
        r = at(0.44)
        fw = struct.unpack_from("<h", bytes.fromhex([f for f in st if f["t"] <= 0.44][-1]["data"]), 2)[0] / 100
        add("对零后 CAN 报的关节角 = 真实角度（≤ 0.01°；开机 37.5°，对零时转子被拉动不到 0.4°）",
            abs(fw - r["joint"]) <= 0.011 and abs(r["joint"] - 37.5) < 0.4, "报 {:.2f}°，真实 {:.4f}°".format(fw, r["joint"]))
        add("回原点了", r["mc"]["homed"] == 1, "原点 {:.3f}°".format(r["mc"]["home_mdeg"] / 1000))
        add("指令 90°：到位误差 ≤ 0.05°", abs(last["joint"] - 90) <= 0.05, "{:.4f}°".format(last["joint"] - 90))
        mx = max(r["joint"] for r in rows)
        add("没有按 0° 去走 90°（最大 < 92°）", mx < 92, "最大 {:.3f}°".format(mx))
    if sid == "ssi":
        e5 = next((f for f in em if bytes.fromhex(f["data"])[0] == 5), None)
        add("线断后 10 ms 内报故障 5（输出端编码器）", e5 is not None and e5["t"] - 0.6 <= 0.010,
            "{:.1f} ms".format((e5["t"] - 0.6) * 1000) if e5 else "没报")
        add("立即关输出", at(0.62)["moe"] == 0, "")
    if sid == "slip":
        b = at(0.89)
        add("打滑前停在 20°、两编码器一致（≤ 0.05°）", abs(b["joint"] - 20) <= 0.05 and abs(b["mc"]["mismatch_mdeg"]) <= 50,
            "{:.4f}°，差 {:.3f}°".format(b["joint"], b["mc"]["mismatch_mdeg"] / 1000))
        e6 = next((f for f in em if bytes.fromhex(f["data"])[0] == 6), None)
        v = struct.unpack_from("<h", bytes.fromhex(e6["data"]), 1)[0] / 100 if e6 else 0
        add("打滑 2° 后 15 ms 内报故障 6、报的差 ≈ −2°", e6 is not None and e6["t"] - 0.9 <= 0.015 and abs(v + 2) <= 0.1,
            "{:.1f} ms，差 {:.2f}°".format((e6["t"] - 0.9) * 1000, v) if e6 else "没报")
        add("立即关输出", at(0.93)["moe"] == 0, "")
    if sid == "stop":
        e4 = next((f for f in em if bytes.fromhex(f["data"])[0] == 4), None)
        add("约 100 ms 后报通信超时（故障 4）", e4 is not None and 0.09 <= e4["t"] - 1.6 <= 0.12, "{:.0f} ms".format((e4["t"] - 1.6) * 1000) if e4 else "")
        w = [r for r in rows if 1.75 <= r["t"] <= 2.59]
        dev = max(abs(r["joint"] - 90) for r in w)
        add("通信超时后保持在 90°、输出不断（偏差 ≤ 0.05°）", dev <= 0.05 and all(r["moe"] == 1 for r in w), "最大偏差 {:.4f}°".format(dev))
        e2 = next((f for f in em if f["t"] >= 2.6), None)
        add("欠压：报警，停住、抱闸后关输出（第 110 轮）", e2 is not None and at(2.75)["moe"] == 0 and at(2.75)["bopen"] == 0,
            decode(e2) if e2 else "没报")
        w2 = [r for r in rows if r["t"] >= 2.75]
        add("有抱闸：关输出后摆臂不落（第 107 轮没有抱闸时落到 75°）", min(r["joint"] for r in w2) >= 89.9,
            "3.0 s 时 {:.3f}°".format(last["joint"]))
    if sid == "brk_boot":
        r0 = at(0.0)
        add("上电时抱闸抱着（线圈没电）", r0["bopen"] == 0 and abs(r0["joint"] - 60) < 0.01, "{:.3f}°".format(r0["joint"]))
        w = [r for r in rows if 0.38 <= r["t"] <= 0.45]
        add("对零完：抱闸抱住、输出关着，摆臂不动（0.38–0.45 s 变化 ≤ 0.01°；对零时转子被拉动约 0.25°）",
            all(r["moe"] == 0 and r["bopen"] == 0 for r in w) and max(r["joint"] for r in w) - min(r["joint"] for r in w) <= 0.01,
            "{:.4f}°～{:.4f}°".format(min(r["joint"] for r in w), max(r["joint"] for r in w)))
        j0 = at(0.45)["joint"]
        rel = next((r["t"] for r in rows if r["t"] >= 0.45 and r["bopen"] == 1), None)
        add("指令后先开输出、再松闸", rel is not None and at(rel)["moe"] == 1, "{:.1f} ms 后松开".format((rel - 0.45) * 1000) if rel else "没松")
        w = [r for r in rows if 0.45 <= r["t"] <= 0.505]
        dev = max(abs(r["joint"] - j0) for r in w)
        w1 = [r for r in w if r["t"] >= 0.455]          # 0.45 s 那一点还是就绪时的旧指令
        add("松闸前后摆臂不掉（≤ 0.05°），60 ms 内不走轨迹", dev <= 0.05 and all(abs(r["mc"]["pos_ref_cnt"] - w1[0]["mc"]["pos_ref_cnt"]) <= 1 for r in w1),
            "最大偏差 {:.4f}°".format(dev))
        add("指令 90°：到位误差 ≤ 0.05°", abs(last["joint"] - 90) <= 0.05, "{:.4f}°".format(last["joint"] - 90))
        hb = [bytes.fromhex(f["data"]) for f in tx if f["id"] == 0x701]
        add("心跳帧报抱闸：就绪时 0（抱住）、运行时 1（松开）", len(hb) >= 5 and hb[3][3] == 0 and hb[-1][3] == 1,
            "、".join(str(b[3]) for b in hb))
    if sid in ("brk_uv", "brk_ssi", "brk_stop"):
        b = at(1.68)
        add("事件前停在 90°（≤ 0.05°）、抱闸松开", abs(b["joint"] - 90) <= 0.05 and b["bopen"] == 1, "{:.4f}°".format(b["joint"]))
        aft = [r for r in rows if r["t"] >= 1.7]
        off_t = next((r["t"] for r in aft if r["moe"] == 0), None)
        shut_t = next((r["t"] for r in aft if r["bopen"] == 0), None)
        late = [r for r in rows if r["t"] >= 1.9]
    if sid == "brk_uv":
        e2 = next((f for f in em if f["t"] >= 1.7 and bytes.fromhex(f["data"])[0] == 2), None)
        add("10 ms 内报欠压（故障 2）", e2 is not None and e2["t"] - 1.7 <= 0.01, decode(e2) if e2 else "没报")
        add("先抱住、后关输出（抱住时输出还开着）", shut_t is not None and off_t is not None and shut_t < off_t,
            "{:.0f} ms 抱住，{:.0f} ms 关输出".format((shut_t - 1.7) * 1000, (off_t - 1.7) * 1000) if shut_t and off_t else "")
        dev = max(abs(r["joint"] - 90) for r in aft)
        add("摆臂不落：之后一直在 90° ± 0.1°", dev <= 0.1, "最大偏差 {:.4f}°".format(dev))
        add("结束时故障、关输出、抱着", last["mc"]["state"] == 3 and last["moe"] == 0 and last["bopen"] == 0, FAULT[last["mc"]["fault"]])
    if sid == "brk_ssi":
        e5 = next((f for f in em if f["t"] >= 1.7 and bytes.fromhex(f["data"])[0] == 5), None)
        add("10 ms 内报故障 5、立即关输出", e5 is not None and e5["t"] - 1.7 <= 0.01 and off_t is not None and off_t - (e5["t"] if e5 else 0) <= 0.002,
            "{:.1f} ms 报警".format((e5["t"] - 1.7) * 1000) if e5 else "没报")
        drop = 90 - min(r["joint"] for r in aft)
        add("抱闸抱住前摆臂落下一点（≤ 2°）", drop <= 2.0, "落了 {:.3f}°，{:.0f} ms 抱住".format(drop, (shut_t - 1.7) * 1000) if shut_t else "没抱住")
        sp = max(r["joint"] for r in late) - min(r["joint"] for r in late)
        add("抱住后不再动（1.9 s 起变化 ≤ 0.01°）", sp <= 0.01, "{:.4f}°".format(sp))
    if sid == "brk_stop":
        add("收到“停”：先抱住、后关输出", shut_t is not None and off_t is not None and shut_t < off_t,
            "{:.0f} ms 抱住，{:.0f} ms 关输出".format((shut_t - 1.7) * 1000, (off_t - 1.7) * 1000) if shut_t and off_t else "")
        dev = max(abs(r["joint"] - 90) for r in aft)
        add("摆臂不落：之后一直在 90° ± 0.1°", dev <= 0.1, "最大偏差 {:.4f}°".format(dev))
        add("回到就绪、没报故障", last["mc"]["state"] == 1 and last["mc"]["fault"] == 0 and last["moe"] == 0, STATE[last["mc"]["state"]])
    return C


# ---------------------------------------------------------------- 主程序
def symbol(name):
    for ln in subprocess.run(["arm-none-eabi-nm", ELF], capture_output=True, text=True, check=True).stdout.splitlines():
        a, _, n = ln.split()
        if n == name:
            return int(a, 16)
    raise SystemExit("找不到符号 " + name)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--renode", default=os.environ.get("RENODE") or shutil.which("renode") or "/opt/renode/renode")
    ap.add_argument("--no-build", action="store_true")
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    if not a.no_build:
        subprocess.run(["make", "-s", "-C", HERE], check=True, capture_output=True)
    addr = symbol("mc")
    res = []
    for sc in SCENARIOS:
        if a.only and sc["id"] not in a.only.split(","):
            continue
        rows, frames = run_one(a.renode, sc, addr)
        checks = check(sc, rows, frames)
        S = dict(t=[round(r["t"], 5) for r in rows],
                 iq=[round(r["iq"], 4) for r in rows], iq_ref=[round(r["mc"]["iq_ref"], 4) for r in rows],
                 id=[round(r["id"], 4) for r in rows],
                 rpm=[round(r["rpm"], 2) for r in rows], rpm_ref=[round(r["mc"]["speed_ref"], 2) for r in rows],
                 rpm_fw=[round(r["mc"]["speed_rpm"], 2) for r in rows],
                 joint=[round(r["joint"], 5) for r in rows],
                 joint_ref=[round(r["mc"]["pos_ref_cnt"] * 360.0 / CPR / GEAR, 5) for r in rows],
                 state=[r["mc"]["state"] for r in rows], moe=[r["moe"] for r in rows],
                 brake=[r["bopen"] for r in rows], brake_i=[round(r["bi"], 4) for r in rows],
                 ia=[round(r["ia"], 3) for r in rows], ib=[round(r["ib"], 3) for r in rows])
        fr = [dict(t=round(f["t"], 6), dir=f["dir"], id="0x{:03X}".format(f["id"]), data=f["data"], text=decode(f)) for f in frames]
        res.append(dict(id=sc["id"], name=sc["name"], en=sc["en"], desc=sc["desc"],
                        events=[[t, list(e) if isinstance(e, tuple) else e] for t, e in sc["events"]],
                        checks=checks, series=S, frames=fr, passed=all(c["ok"] for c in checks)))
        print("{} {}：{}".format("✓" if res[-1]["passed"] else "✗", sc["name"],
                                "；".join(("" if c["ok"] else "✗ ") + c["name"] + (" " + c["detail"] if c["detail"] else "") for c in checks)))
    if a.only:
        return 0
    size = subprocess.run(["arm-none-eabi-size", ELF], capture_output=True, text=True, check=True).stdout.splitlines()[1].split()
    out = dict(round=110, title="驱动板 B 版示例固件：FOC 三环 + CAN + 保护 + 输出端编码器 + 抱闸，Renode 仿真",
               firmware=dict(text=int(size[0]), data=int(size[1]), bss=int(size[2]), flash=int(size[0]) + int(size[1]),
                             ram=int(size[1]) + int(size[2])),
               mc_addr="0x{:08X}".format(addr), params=[dict(name=n, value=v, unit=u, source=s) for n, v, u, s in PARAMS],
               scenarios=res, all_pass=all(s["passed"] for s in res),
               disclaimer="示例固件，仿真验证；电机参数零件库没有的是示例值；芯片 WQ-ENCIF 未流片、B 版不投产。")
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "sim_motor.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print("全部通过" if out["all_pass"] else "有场景没通过")
    return 0 if out["all_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
