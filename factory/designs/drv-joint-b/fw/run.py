# -*- coding: utf-8 -*-
"""第 100 轮：驱动板 B 版固件在 Renode 里跑六个场景，逐一核对，写 out/sim.json。

用法：python3 run.py [--renode /opt/renode/renode] [--no-build]
每个场景：起一台仿真机（STM32G431 + WQ-ENCIF 外设 + 虚拟电机），装入编译好的 fw.elf，
每 10 ms 读一次固件内存里的遥测区（相当于调试器经 SWD 看变量）和虚拟电机的真值。
判据都用物理真值：转速曲线在这里独立积分出位置，与固件读到的计数比。"""
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
CPR = 10000
STEP = 0.01

FIELDS = ["magic", "state", "id", "ctrl", "tick_ms", "cnt", "turns", "angle_cnt", "rpm_x10", "idx", "idx_valid",
          "abs_cnt", "err_count", "status", "frames", "retries"]
SIGNED = {"cnt", "turns", "angle_cnt", "rpm_x10", "idx", "abs_cnt"}
STATE = {0: "启动", 1: "运行", 2: "芯片缺失"}

SCENARIOS = [
    dict(id="boot", name="① 上电", en="Power-up",
         desc="复位芯片、读 ID、写控制寄存器；电机不转。",
         profile=[(0, 0)], dur=0.05, events=[]),
    dict(id="fwd", name="② 正转 600 rpm", en="Forward 600 rpm",
         desc="0.05 s 起 0.1 s 内升到 600 rpm 并保持；看转速读数和位置跟随。",
         profile=[(0, 0), (0.05, 0), (0.15, 600), (0.6, 600)], dur=0.6, events=[]),
    dict(id="rev", name="③ 反转、过零", en="Reverse through zero",
         desc="300 rpm 正转后减速反转到 −300 rpm，位置退回开机点以下，计数变负。",
         profile=[(0, 300), (0.2, 300), (0.4, -300), (0.8, -300)], dur=0.8, events=[]),
    dict(id="index", name="④ Z 相", en="Index pulse",
         desc="开机时电机在 1234 计数处；转过 Z 相后，固件给出相对 Z 的绝对角度。",
         profile=[(0, 0), (0.02, 0), (0.1, 600), (0.5, 600)], dur=0.5, start=1234, events=[]),
    dict(id="err", name="⑤ 芯片报错", en="Chip error",
         desc="600 rpm 运行中，0.2 s 注入一次 A/B 同跳错误；固件记一次并清除，之后照常。",
         profile=[(0, 600)], dur=0.5, events=[(0.2, "InjectError")]),
    dict(id="absent", name="⑥ 芯片不响应", en="Chip absent",
         desc="芯片不响应（读回全 0）：固件停在“芯片缺失”、不报数，每 100 ms 重试；0.35 s 芯片恢复，下一次重试接上。",
         profile=[(0, 300)], dur=0.6, events=[(0.0, "Absent true"), (0.35, "Absent false")]),
]


# ---------------------------------------------------------------- 真值（独立于 Renode 外设的实现）
def rpm_at(prof, t):
    if t <= prof[0][0]:
        return prof[0][1]
    for (t0, r0), (t1, r1) in zip(prof, prof[1:]):
        if t <= t1:
            return r0 + (r1 - r0) * (t - t0) / (t1 - t0)
    return prof[-1][1]


def pos_at(prof, t):
    """开机以来走过的计数（浮点）。"""
    pts = [p[0] for p in prof if 0 < p[0] < t] + [t]
    acc, t0 = 0.0, 0.0
    for t1 in pts:
        acc += (rpm_at(prof, t0) + rpm_at(prof, t1)) / 2 * (t1 - t0) * CPR / 60.0
        t0 = t1
    return acc


# ---------------------------------------------------------------- 跑 Renode
def resc(sc, tlm_addr):
    fw = HERE.replace("\\", "/")
    L = ["using sysbus", 'emulation SetGlobalQuantum "0.00001"', 'mach create "drv-joint-b"',
         "include @{}/renode/WqEncif.cs".format(fw), "include @{}/renode/WqDrive.cs".format(fw),
         "machine LoadPlatformDescription @{}/renode/stm32g431.repl".format(fw),
         'machine LoadPlatformDescriptionFromString "encif: SPI.WqEncif @ spi1"',
         'machine LoadPlatformDescriptionFromString "gpioPortA: { 4 -> encif@0 }"',
         'machine LoadPlatformDescriptionFromString "gpioPortB: { 1 -> encif@1 }"', "cpu PerformanceInMips 170",
         'spi1.encif Profile "{}"'.format(",".join("{}:{}".format(t, r) for t, r in sc["profile"])),
         "logLevel 3"]
    if sc.get("start"):
        L.append("spi1.encif StartPos {}".format(sc["start"]))
    L.append("sysbus LoadELF @{}/build/fw.elf".format(fw))
    ev = sorted(sc["events"])
    n = int(round(sc["dur"] / STEP))
    for k in range(n + 1):
        t = k * STEP
        while ev and ev[0][0] <= t + 1e-9:
            L.append("spi1.encif " + ev.pop(0)[1])
        if k:
            L.append('emulation RunFor "{:.2f}"'.format(STEP))
        L.append("spi1.encif Truth")
        L.append("sysbus ReadBytes 0x{:08X} {}".format(tlm_addr, 4 * len(FIELDS)))
    L.append("quit")
    return "\n".join(L) + "\n"


def parse(text):
    rows = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        ln = lines[i].strip()
        if ln.startswith("T "):
            _, t, pos, rpm, absp, base = ln.split()
            j = i + 1
            while not lines[j].strip().startswith("["):
                j += 1
            buf = []
            j += 1
            while not lines[j].strip().startswith("]"):
                buf += [int(x, 16) for x in re.findall(r"0x[0-9A-Fa-f]+", lines[j])]
                j += 1
            vals = struct.unpack("<" + "".join("i" if f in SIGNED else "I" for f in FIELDS), bytes(buf))
            rows.append(dict(t=float(t), truth_pos=float(pos), truth_rpm=float(rpm), base=int(base), tl=dict(zip(FIELDS, vals))))
            i = j
        i += 1
    return rows


def run_one(renode, sc, tlm_addr):
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "s.resc")
        open(p, "w", encoding="utf-8").write(resc(sc, tlm_addr))
        r = subprocess.run([renode, "--disable-xwt", "--plain", "--console", "-e", "include @" + p],
                           capture_output=True, text=True, timeout=600)
    rows = parse(r.stdout)
    if len(rows) != int(round(sc["dur"] / STEP)) + 1:
        sys.stderr.write(r.stdout[-3000:] + r.stderr[-2000:])
        raise SystemExit("场景 {} 输出不全".format(sc["id"]))
    return rows


# ---------------------------------------------------------------- 判据
def check(sc, rows):
    prof, start = sc["profile"], sc.get("start", 0)
    C = []

    def add(name, ok, detail):
        C.append(dict(name=name, ok=bool(ok), detail=detail))

    base = rows[-1]["base"]           # 芯片复位释放那一刻电机的绝对位置（计数）：芯片从这里开始数

    def truth_cnt(tk):
        return math.floor(start + pos_at(prof, tk / 1000.0) + 1e-9) - base

    def tol(tick):                    # 绝对角度比对用：允许 100 µs 的走动 + 1 计数
        return 1 + abs(rpm_at(prof, tick / 1000.0)) / 60.0 * CPR * 1e-4

    def track(rs):
        """固件每 1 ms 读一次：读数应等于最近 1.1 ms 内某一时刻的真实位置（±1 计数）。"""
        worst = 0.0
        for r in rs:
            t = r["t"]
            w = [truth_cnt(1000 * (t - 0.0011 * i / 20)) for i in range(21)]
            c = r["tl"]["cnt"]
            e = 0 if min(w) - 1 <= c <= max(w) + 1 else min(abs(c - min(w)), abs(c - max(w))) - 1
            worst = max(worst, e)
        return worst <= 0, worst

    last = rows[-1]["tl"]
    run = [r for r in rows if r["tl"]["state"] == 1 and r["tl"]["tick_ms"] > 0]
    sid = sc["id"]
    if sid == "boot":
        add("芯片 ID = ENC1（0x454E4331）", last["id"] == 0x454E4331, "0x{:08X}".format(last["id"]))
        add("控制寄存器回读 0x31（使能、滤波 3）", last["ctrl"] == 0x31, "0x{:02X}".format(last["ctrl"]))
        add("状态：运行", last["state"] == 1, STATE[last["state"]])
        add("电机不转：计数 0、转速 0", last["cnt"] == 0 and last["rpm_x10"] == 0, "{} / {}".format(last["cnt"], last["rpm_x10"] / 10))
    if sid in ("fwd", "rev", "index", "err"):
        ok, w = track(run)
        add("位置跟随：每 10 ms 看一次，计数等于最近 1 ms 内的真实位置（±1 计数）", ok, "超出 {:.1f} 计数".format(max(w, 0)))
    if sid == "fwd":
        hold = [r["tl"]["rpm_x10"] / 10 for r in rows if r["t"] >= 0.25]
        e = max(abs(x - 600) for x in hold)
        add("匀速段转速读数误差 ≤ 1%（600 rpm）", e <= 6, "最大误差 {:.1f} rpm".format(e))
    if sid == "rev":
        a = [r["tl"]["rpm_x10"] / 10 for r in rows if 0.05 <= r["t"] <= 0.2]
        b = [r["tl"]["rpm_x10"] / 10 for r in rows if r["t"] >= 0.45]
        add("正转段 ≈ +300 rpm、反转段 ≈ −300 rpm（≤ 1%）",
            max(abs(x - 300) for x in a) <= 3 and max(abs(x + 300) for x in b) <= 3,
            "{:.1f} / {:.1f}".format(min(a), max(b)))
        mn = min(r["tl"]["cnt"] for r in rows)
        add("退回开机点以下：计数为负、圈数为负", mn < 0 and last["turns"] < 0, "最小计数 {}，圈数 {}".format(mn, last["turns"]))
    if sid == "index":
        z = CPR - base                # 第一个 Z 在绝对位置 10000；之后每转一次再锁存，相差整圈
        d = (last["idx"] - z) % CPR
        add("Z 相锁存值 ≡ 走到 Z 的计数（{} − {} = {}，每转加 {}）".format(CPR, base, z, CPR),
            last["idx_valid"] == 1 and min(d, CPR - d) <= 1, str(last["idx"]))
        worst = 0
        for r in rows:
            tl = r["tl"]
            if tl["idx_valid"]:
                t = r["t"]                # 同位置跟随：等于最近 1.1 ms 内某一时刻的真实绝对角度（±1 计数）
                w = [math.floor(start + pos_at(prof, t - 0.0011 * i / 20) + 1e-9) for i in range(21)]
                lo, hi = min(w) - 1, max(w) + 1
                mid = (lo + hi) / 2
                x = tl["abs_cnt"] + CPR * round((mid - tl["abs_cnt"]) / CPR)   # 绝对角度展开到真值附近那一圈
                worst = max(worst, 0 if lo <= x <= hi else min(abs(x - lo), abs(x - hi)))
        add("绝对角度（相对 Z）等于最近 1 ms 内的真实角度（±1 计数）", worst <= 0, "超出 {:.1f} 计数".format(max(worst, 0)))
        pre = [r["tl"]["abs_cnt"] for r in run if not r["tl"]["idx_valid"]]
        add("没见到 Z 之前不给绝对角度（−1）", pre and all(x == -1 for x in pre), "{} 个采样".format(len(pre)))
    if sid == "err":
        add("错误记了一次", last["err_count"] == 1, str(last["err_count"]))
        add("错误位已清除", not (last["status"] & 2), "状态 0x{:02X}".format(last["status"]))
        after = [r["tl"]["rpm_x10"] / 10 for r in rows if r["t"] >= 0.25]
        add("之后转速照常（600 rpm ≤ 1%）", max(abs(x - 600) for x in after) <= 6, "{:.1f}–{:.1f}".format(min(after), max(after)))
    if sid == "absent":
        miss = [r["tl"] for r in rows if r["t"] < 0.35]
        add("芯片不响应时停在“芯片缺失”", all(x["state"] == 2 for x in miss[1:]), STATE[miss[-1]["state"]])
        add("缺失期间不报数（计数、转速都是 0）", all(x["cnt"] == 0 and x["rpm_x10"] == 0 for x in miss), "")
        add("每 100 ms 重试（到 0.35 s 共 3 次）", miss[-1]["retries"] == 3, str(miss[-1]["retries"]))
        rec = [r for r in rows if r["tl"]["state"] == 1]
        add("芯片恢复后下一次重试（0.4 s）接上", rec and abs(rec[0]["t"] - 0.40) < 0.011 and last["id"] == 0x454E4331,
            "{:.2f} s".format(rec[0]["t"]) if rec else "未接上")
        rt = [r["tl"]["rpm_x10"] / 10 for r in rows if r["t"] >= 0.45]
        add("接上后转速 300 rpm（≤ 1%）", rt and max(abs(x - 300) for x in rt) <= 3, "{:.1f}".format(rt[-1]) if rt else "")
    return C


# ---------------------------------------------------------------- 主程序
def build():
    subprocess.run(["make", "-s", "-C", HERE], check=True, capture_output=True)


def size():
    o = subprocess.run(["arm-none-eabi-size", ELF], capture_output=True, text=True, check=True).stdout.splitlines()[1].split()
    return dict(text=int(o[0]), data=int(o[1]), bss=int(o[2]), flash=int(o[0]) + int(o[1]), ram=int(o[1]) + int(o[2]))


def symbol(name):
    for ln in subprocess.run(["arm-none-eabi-nm", ELF], capture_output=True, text=True, check=True).stdout.splitlines():
        a, _, n = ln.split()
        if n == name:
            return int(a, 16)
    raise SystemExit("找不到符号 " + name)


def renode_version(renode):
    r = subprocess.run([renode, "--version"], capture_output=True, text=True, timeout=120)
    m = re.search(r"Renode v?([0-9.]+)", r.stdout)
    return m.group(1) if m else "?"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--renode", default=os.environ.get("RENODE") or shutil.which("renode") or "/opt/renode/renode")
    ap.add_argument("--no-build", action="store_true")
    a = ap.parse_args()
    if not a.no_build:
        build()
    addr = symbol("tlm")
    res = []
    for sc in SCENARIOS:
        rows = run_one(a.renode, sc, addr)
        checks = check(sc, rows)
        series = dict(t=[round(r["t"], 3) for r in rows],
                      truth_rpm=[round(r["truth_rpm"], 1) for r in rows],
                      rpm=[r["tl"]["rpm_x10"] / 10 for r in rows],
                      truth_cnt=[math.floor(sc.get("start", 0) + r["truth_pos"] + 1e-9) - r["base"] for r in rows],
                      cnt=[r["tl"]["cnt"] for r in rows],
                      abs_cnt=[r["tl"]["abs_cnt"] for r in rows],
                      state=[r["tl"]["state"] for r in rows])
        res.append(dict(id=sc["id"], name=sc["name"], en=sc["en"], desc=sc["desc"],
                        profile=[list(p) for p in sc["profile"]], start=sc.get("start", 0),
                        events=[list(e) for e in sc["events"]], checks=checks, series=series,
                        final={k: v for k, v in rows[-1]["tl"].items() if k != "magic"},
                        passed=all(c["ok"] for c in checks)))
        print("{} {}：{}".format("✓" if res[-1]["passed"] else "✗", sc["name"],
                                "；".join(("" if c["ok"] else "✗ ") + c["name"] + (" " + c["detail"] if c["detail"] else "")
                                         for c in checks)))
    out = dict(round=100, title="驱动板 B 版示例固件：经 SPI1 读 WQ-ENCIF，Renode 仿真",
               renode=renode_version(a.renode), cpu="STM32G431CB（Cortex-M4F，HSI16 16 MHz）",
               cpr=CPR, step_s=STEP, firmware=size(), tlm_addr="0x{:08X}".format(addr), tlm_fields=FIELDS,
               scenarios=res, all_pass=all(s["passed"] for s in res),
               disclaimer="示例固件，仿真验证；芯片 WQ-ENCIF 未流片、B 版不投产。")
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "sim.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print("全部通过" if out["all_pass"] else "有场景没通过")
    return 0 if out["all_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
