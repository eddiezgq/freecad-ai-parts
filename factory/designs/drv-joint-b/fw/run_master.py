"""第 115 轮：多关节 CAN 主站在环仿真——Renode 里同时跑两台驱动板（同一份固件，节点 1、2），主站程序 master/master.py 每 10 ms 一拍。

用法：python3 run_master.py [--renode /opt/renode/renode] [--no-build] [--only line,fault,lost]
做法：Renode 用控制台模式开着（--console），本脚本像人敲命令一样一拍一拍推进：
  给两台机器发主站这一拍的帧 → emulation RunFor 10 ms（两台机器时间同步）→ 取两台机器这 10 ms 的 CAN 记录和电机模型真值 → 交给主站算下一拍。
两个关节都在水平面里转（没有重力），关节之间的动力学耦合不模拟。写 out/sim_master.json。
"""

import argparse
import json
import math
import os
import re
import select
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "master"))
import master as M  # noqa: E402

P0, P1, T_MOVE = (0.40, 0.15), (0.20, 0.35), 1.5          # 示例
NODES = (1, 2)

SCENARIOS = [
    dict(id="line", name="⑱ 两关节协同：末端走直线", en="Two joints in step: straight-line tool path",
         desc="主站等两个关节都就绪，原地稳住 0.3 s，然后末端沿直线从 (0.40, 0.15) m 走到 (0.20, 0.35) m，用时 1.5 s（梯形速度），"
              "到位稳住 0.3 s 后给两个关节发“停”。每 10 ms 主站做一次逆运动学，给两个关节同时发位置指令。",
         dur=3.2, inject=[]),
    dict(id="fault", name="⑲ 一个关节报警，全部一起停", en="One joint faults, all stop",
         desc="走到一半（1.40 s）关节 2 的输出端编码器线断：关节 2 报故障 5、立即关输出并抱闸；主站收到报警，下一拍（≤ 10 ms）给关节 1 发“停”，关节 1 停住、抱闸、关输出。",
         dur=2.4, inject=[(1.40, 2, "spi3.ssi Broken true")]),
    dict(id="lost", name="⑳ 一个关节掉线，全部一起停", en="One joint drops off the bus, all stop",
         desc="走到一半（1.40 s）关节 2 的 CAN 掉线（收发都断）：关节 2 收不到指令，100 ms 后按通信超时自己停住、保持位置；"
              "主站 300 ms 没收到关节 2 的心跳，判它掉线，给关节 1 发“停”。",
         dur=2.4, inject=[(1.40, 2, "fdcan1 Mute true")]),
]


class Renode:
    """开着的 Renode 控制台：发命令、读到指定的结束标记为止。"""

    def __init__(self, exe):
        self.p = subprocess.Popen([exe, "--disable-xwt", "--plain", "--console"], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.buf = ""

    def send(self, *lines):
        self.p.stdin.write(("\n".join(lines) + "\n").encode())
        self.p.stdin.flush()

    def read_until(self, token, count=1, timeout=300):
        t0 = time.time()
        while self.buf.count(token) < count:
            r, _, _ = select.select([self.p.stdout], [], [], 1)
            if r:
                chunk = os.read(self.p.stdout.fileno(), 1 << 16)
                if not chunk:
                    raise SystemExit("Renode 退出了：" + self.buf[-2000:])
                self.buf += chunk.decode("utf-8", "replace")
            if time.time() - t0 > timeout:
                raise SystemExit("Renode 没回应：" + self.buf[-2000:])
        out, self.buf = self.buf, ""
        return out

    def close(self):
        try:
            self.send("quit")
            self.p.wait(timeout=30)
        except Exception:
            self.p.kill()


def setup(rn, th0):
    fw = HERE.replace("\\", "/")
    L = ["using sysbus", 'emulation SetGlobalQuantum "0.00001"',
         "include @{}/renode/WqEncif.cs".format(fw), "include @{}/renode/WqDrive.cs".format(fw)]
    for n, a in zip(NODES, th0):
        L += ['mach create "j{}"'.format(n),
              "machine LoadPlatformDescription @{}/renode/stm32g431.repl".format(fw),
              'machine LoadPlatformDescriptionFromString "encif: SPI.WqEncif @ spi1"',
              'machine LoadPlatformDescriptionFromString "gpioPortA: { 4 -> encif@0 }"',
              'machine LoadPlatformDescriptionFromString "gpioPortB: { 1 -> encif@1 }"',
              "cpu PerformanceInMips 170", "logLevel 3",
              "tim1 ExtraMass -1", "tim1 StartJoint {:.6f}".format(a),          # 水平面里转：没有重力
              'spi1.encif UseMotor "tim1"', "sysbus LoadELF @{}/build/fw-node{}.elf".format(fw, n)]
    rn.send(*L)
    rn.send('mach set "j1"', "fdcan1 HostLog")
    rn.read_until("CAN>>", timeout=600)


FRAME = re.compile(r"F (\S+) (rx|tx) ([0-9A-F]{3}) ([0-9A-F]*)")


def run(rn_exe, sc):
    th0 = M.ik(*P0)
    rn = Renode(rn_exe)
    try:
        setup(rn, th0)
        ms = M.Master(P0, P1, T_MOVE, NODES)
        rows, frames, pending = [], [], []
        steps = int(round(sc["dur"] / M.PERIOD))
        for k in range(steps):
            t = round(k * M.PERIOD, 4)
            L = []
            for n in NODES:
                L.append('mach set "j{}"'.format(n))
                L += ['fdcan1 HostSend 0x{:03X} "{}"'.format(fid, d.hex().upper()) for fid, d in pending if fid & 0x7F == n]
                L += [a for ti, ni, a in sc["inject"] if ni == n and abs(ti - t) < 1e-9]
            L.append('emulation RunFor "{:.4f}"'.format(M.PERIOD))
            for n in NODES:
                L += ['mach set "j{}"'.format(n), "tim1 Truth", "fdcan1 HostLog"]
            rn.send(*L)
            out = rn.read_until("CAN>>", count=len(NODES))
            truth = [ln.split() for ln in out.splitlines() if ln.strip().startswith("M ")]
            got = []
            for m in FRAME.finditer(out):
                f = dict(t=float(m.group(1)), dir=m.group(2), id=int(m.group(3), 16), data=m.group(4))
                frames.append(f)
                if f["dir"] == "tx":
                    got.append((f["t"], f["id"], bytes.fromhex(f["data"])))
            got.sort()
            tn = round(t + M.PERIOD, 4)
            r = dict(t=tn)
            for n, f in zip(NODES, truth):
                r["j{}".format(n)] = float(f[5])
                r["rpm{}".format(n)] = float(f[4])
                r["moe{}".format(n)] = int(f[8])
                r["brk{}".format(n)] = int(f[15])
            pending = ms.step(tn, got)
            for n in NODES:
                jt = ms.j[n]
                r["ref{}".format(n)] = jt.cmd
                r["st{}".format(n)] = jt.state
            r["x"], r["y"] = M.fk(r["j1"], r["j2"])
            r["xr"], r["yr"] = ms.target if ms.target else (None, None)
            r["phase"] = ms.phase
            r["sent"] = [(fid, d.hex().upper()) for fid, d in pending]
            rows.append(r)
        return rows, frames, ms.events
    finally:
        rn.close()


def dist_to_line(x, y):
    (x0, y0), (x1, y1) = P0, P1
    dx, dy = x1 - x0, y1 - y0
    return abs(dy * (x - x0) - dx * (y - y0)) / math.hypot(dx, dy)


def check(sc, rows, frames, events):
    C = []

    def add(name, ok, detail=""):
        C.append(dict(name=name, ok=bool(ok), detail=detail))

    sid = sc["id"]
    last = rows[-1]
    em = [f for f in frames if f["dir"] == "tx" and f["id"] & 0x780 == M.ID_EMCY]
    stop_sent = [(r["t"], fid) for r in rows for fid, d in r["sent"] if d.startswith("00")]
    t_ready = next((e[0] for e in events if "就绪" in e[1]), None)
    add("两个关节都就绪后主站才开始（≤ 0.5 s）", t_ready is not None and t_ready <= 0.5, "{:.2f} s".format(t_ready) if t_ready else "没等到")
    if sid == "line":
        mv = [r for r in rows if r["phase"] in ("走直线", "到位稳住")]
        dev = max(dist_to_line(r["x"], r["y"]) for r in mv) * 1000
        add("路径偏离直线 ≤ 0.5 mm", dev <= 0.5, "{:.3f} mm".format(dev))
        end = next(r for r in rows if r["phase"] == "完成")
        err = math.hypot(end["x"] - P1[0], end["y"] - P1[1]) * 1000
        add("终点误差 ≤ 0.2 mm", err <= 0.2, "{:.3f} mm".format(err))
        th0, th1 = M.ik(*P0), M.ik(*P1)
        st = [next(r["t"] for r in rows if abs(r["j{}".format(n)] - th0[i]) > 0.01) for i, n in enumerate(NODES)]
        ar = [next(r["t"] for r in rows if abs(r["j{}".format(n)] - th1[i]) <= 0.01) for i, n in enumerate(NODES)]
        add("两关节同时开始（相差 ≤ 20 ms）", abs(st[0] - st[1]) <= 0.02, "{:.0f} ms".format(abs(st[0] - st[1]) * 1000))
        add("两关节同时到位（相差 ≤ 20 ms）", abs(ar[0] - ar[1]) <= 0.02, "{:.2f} s、{:.2f} s".format(*ar))
        add("完成后两个关节都停住、抱闸、关输出", all(last["moe{}".format(n)] == 0 and last["brk{}".format(n)] == 0 for n in NODES), "")
    if sid == "fault":
        e = next((f for f in em if f["t"] >= 1.40), None)
        add("关节 2 报故障 5（输出端编码器）", e is not None and e["id"] == M.ID_EMCY + 2 and e["data"][:2] == "05",
            "{:.1f} ms".format((e["t"] - 1.40) * 1000) if e else "没报")
        s1 = next((t for t, fid in stop_sent if fid == M.ID_CMD + 1), None)
        add("主站 ≤ 10 ms 给关节 1 发“停”", e is not None and s1 is not None and s1 - e["t"] <= 0.0100001,
            "报警后 {:.1f} ms".format((s1 - e["t"]) * 1000) if e and s1 else "")
        add("两个关节都停住、关输出、抱住", all(last["moe{}".format(n)] == 0 and last["brk{}".format(n)] == 0 for n in NODES), "")
        tail = [r for r in rows if r["t"] >= last["t"] - 0.3]
        sp = max(math.hypot(r["x"] - tail[0]["x"], r["y"] - tail[0]["y"]) for r in tail) * 1000
        add("停下以后末端不动（最后 0.3 s ≤ 0.05 mm）", sp <= 0.05, "{:.4f} mm".format(sp))
    if sid == "lost":
        s1 = next((t for t, fid in stop_sent if fid == M.ID_CMD + 1), None)
        add("主站判关节 2 掉线，给关节 1 发“停”（掉线后 ≤ 0.4 s）", s1 is not None and s1 - 1.40 <= 0.4,
            "掉线后 {:.0f} ms".format((s1 - 1.40) * 1000) if s1 else "没发")
        add("关节 1 停住、抱闸、关输出", last["moe1"] == 0 and last["brk1"] == 0, "")
        tail = [r for r in rows if r["t"] >= last["t"] - 0.3]
        sp2 = max(abs(r["j2"] - tail[0]["j2"]) for r in tail)
        add("关节 2 按通信超时自己停住、保持（输出开着，最后 0.3 s ≤ 0.01°）", last["moe2"] == 1 and sp2 <= 0.01, "{:.4f}°".format(sp2))
    return C


def build():
    for n in NODES:
        subprocess.run(["make", "-s", "build/fw-node{}.elf".format(n)], cwd=HERE, check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--renode", default="renode")
    ap.add_argument("--no-build", action="store_true")
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    if not a.no_build:
        build()
    only = set(filter(None, a.only.split(",")))
    out = dict(round=115, title="多关节 CAN 主站：两块驱动板 B 版带一台水平两关节机械臂，Renode 主站在环仿真",
               arm=dict(l1=M.L1, l2=M.L2, p0=P0, p1=P1, t_move=T_MOVE, period=M.PERIOD,
                        heart_timeout=M.HEART_TIMEOUT, track_max=M.TRACK_MAX, note="尺寸、速度、阈值都是示例；关节间动力学耦合不模拟"),
               scenarios=[])
    ok_all = True
    for sc in SCENARIOS:
        if only and sc["id"] not in only:
            continue
        rows, frames, events = run(a.renode, sc)
        C = check(sc, rows, frames, events)
        ok = all(c["ok"] for c in C)
        ok_all &= ok
        print(("✓ " if ok else "✗ ") + sc["name"] + "：" + "；".join(("" if c["ok"] else "✗ ") + c["name"] + " " + c["detail"] for c in C))
        keep = [f for f in frames if not (f["id"] & 0x780 in (M.ID_STATUS, M.ID_CMD) and f["data"][:2] == "02")]
        ser = {k: [(round(r[k], 6) if isinstance(r[k], float) else r[k]) for r in rows]
               for k in ("t", "j1", "j2", "ref1", "ref2", "x", "y", "xr", "yr", "moe1", "moe2", "brk1", "brk2", "st1", "st2", "phase")}
        out["scenarios"].append(dict(id=sc["id"], name=sc["name"], en=sc["en"], desc=sc["desc"], inject=sc["inject"],
                                     checks=C, ok=ok, events=events, series=ser, frames=keep[:400]))
    if not only:
        os.makedirs(os.path.join(HERE, "out"), exist_ok=True)
        with open(os.path.join(HERE, "out", "sim_master.json"), "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
            f.write("\n")
    print("全部通过" if ok_all else "有不通过的")
    sys.exit(0 if ok_all else 1)


if __name__ == "__main__":
    main()
