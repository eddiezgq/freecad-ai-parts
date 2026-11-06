# -*- coding: utf-8 -*-
"""跑全部用例：Icarus Verilog 仿真 RTL，与参考模型逐拍比对，并核对 SPI 读回的值。
产物写到 ../out/sim/：每个用例的波形（JSON，网页用）和 summary.json。用法：python3 run.py [--out DIR]"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "model"))
import encif as E  # noqa: E402

SIGS = [("A", "w", 0), ("B", "w", 1), ("Z", "w", 2), ("SCLK", "w", 3), ("CS_N", "w", 4), ("MOSI", "w", 5), ("MISO", "miso", None),
        ("A 滤波后", "fa", None), ("B 滤波后", "fb", None), ("计数", "cnt", None), ("Z 位置", "idx", None), ("丢步", "err", None)]


def vcd_to_wave(path):
    """读 VCD，转成 {信号: [[拍, 值], …]}（只记变化）；时间按 $timescale 换成拍（1 拍 = 20 ns）"""
    ids, t = {}, 0
    out = {}
    with open(path) as f:
        lines = f.read().split("\n")
    scope = []
    text = " ".join(lines)
    ts = text[text.index("$timescale") + 10:text.index("$end", text.index("$timescale"))].strip()
    num = int("".join(c for c in ts if c.isdigit()))
    unit = {"s": 1, "ms": 1e-3, "us": 1e-6, "ns": 1e-9, "ps": 1e-12, "fs": 1e-15}[ts.lstrip("0123456789 ")]
    per = round(20e-9 / (num * unit))                 # 一拍多少个 VCD 时间单位
    for ln in lines:
        p = ln.split()
        if not p:
            continue
        if p[0] == "$scope":
            scope.append(p[2])
        elif p[0] == "$upscope":
            scope.pop()
        elif p[0] == "$var":
            ids.setdefault(p[3], []).append(p[4])
        elif p[0].startswith("#"):
            t = int(p[0][1:]) // per
        elif p[0][0] in "01xz" and len(p) == 1:
            for nm in ids.get(p[0][1:], []):
                out.setdefault(nm, []).append([t, p[0][0]])
        elif p[0][0] == "b":
            for nm in ids.get(p[1], []):
                out.setdefault(nm, []).append([t, p[0][1:]])
    return out


def wave_json(raw, n):
    """按 SIGS 抽信号，时间换成拍（10 ns 一拍的上升沿在 #10、#30…；以输入施加时刻 = 拍号）"""
    res = []
    for name, src, bit in SIGS:
        ev = raw.get(src, [])
        pts, last = [], None
        for t, v in ev:
            k = t
            if bit is not None:
                v = v.rjust(7, "0")[::-1][bit] if v[0] in "01" else "x"
            else:
                v = str(int(v, 2)) if all(c in "01" for c in v) else "x"
                if name in ("计数", "Z 位置"):
                    x = int(v) if v != "x" else 0
                    v = str(x - (1 << 32) if x >= 1 << 31 else x)
            if v != last:
                if pts and pts[-1][0] == k:
                    pts[-1][1] = v
                else:
                    pts.append([k, v])
                last = v
        res.append({"name": name, "bus": bit is None and name in ("计数", "Z 位置"), "pts": pts})
    return {"n": n, "signals": res}


def run_case(name, st, tmp, vvp):
    words = st.w
    with open(os.path.join(tmp, "stim.hex"), "w") as f:
        f.write("\n".join("{:02x}".format(x) for x in words) + "\n")
    subprocess.run(["vvp", "-n", vvp, "+n={}".format(len(words))], cwd=tmp, check=True, capture_output=True)
    rtl = []
    with open(os.path.join(tmp, "trace.txt")) as f:
        for ln in f:
            c, i, s, m = ln.split()
            rtl.append((int(c, 16), int(i, 16), int(s, 16), int(m)))
    ref = E.run(words)
    mism = [k for k in range(len(words)) if rtl[k] != ref[k]]
    return words, rtl, ref, mism, vcd_to_wave(os.path.join(tmp, "wave.vcd"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "out", "sim"))
    a = ap.parse_args()
    tmp = tempfile.mkdtemp(prefix="encif-")
    vvp = os.path.join(tmp, "tb.vvp")
    subprocess.run(["iverilog", "-g2005", "-Wall", "-o", vvp, os.path.join(HERE, "tb.v"), os.path.join(ROOT, "rtl", "wq_encif.v")], check=True)
    os.makedirs(a.out, exist_ok=True)
    summary = {"tool": subprocess.run(["iverilog", "-V"], capture_output=True, text=True).stdout.split("\n")[0].split(" (")[0],
               "cases": []}
    ok = True
    for name, st in E.cases().items():
        words, rtl, ref, mism, raw = run_case(name, st, tmp, vvp)
        c = {"name": name, "cycles": len(words), "match": not mism, "first_mismatch": mism[0] if mism else None,
             "final": {"count": rtl[-1][0] - (1 << 32) if rtl[-1][0] >> 31 else rtl[-1][0], "index": rtl[-1][1], "status": rtl[-1][2]}}
        c["reads"] = [{"at": stt, "addr": ad, "value": E.spi_read_value(words, rtl, stt)} for stt, ad in st.reads]
        if mism:
            k = mism[0]
            c["detail"] = {"rtl": rtl[k], "model": ref[k]}
            ok = False
        fn = "{:02d}.json".format(len(summary["cases"]) + 1)
        with open(os.path.join(a.out, fn), "w", encoding="utf-8") as f:
            json.dump(dict(wave_json(raw, len(words)), case=name), f, ensure_ascii=False, separators=(",", ":"))
        c["wave"] = fn
        summary["cases"].append(c)
        print("{:8s} {:6d} 拍  {}".format(name, len(words), "一致" if not mism else "不一致：第 {} 拍 RTL {} 模型 {}".format(mism[0], *c["detail"].values())))
    summary["pass"] = ok
    with open(os.path.join(a.out, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    shutil.rmtree(tmp, ignore_errors=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
