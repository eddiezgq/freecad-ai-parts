# -*- coding: utf-8 -*-
"""WQ-ENCIF 参考模型（逐拍）与测试激励。规则按规格书写（rtl/wq_encif.v 文件头），与 RTL 独立编写，测试逐拍比对。
网页的 JS 行为模型（web/src/lib/encif.js）照同一套规则写，测试用同一组激励核对。示例设计，未流片。"""
from __future__ import annotations

import random

ID = 0x454E4331
M32 = 0xFFFFFFFF
# 激励每拍一个字：位 0 A、1 B、2 Z、3 SCLK、4 CS_N、5 MOSI、6 RST_N
A, B, Z, SCK, CS, MO, RST = (1 << i for i in range(7))


class Encif:
    def __init__(self):
        self.reset()

    def reset(self):
        self.sync = {k: [0, 0] for k in "abzkcm"}
        self.sync["c"] = [1, 1]
        self.f = {"a": 0, "b": 0, "z": 0}
        self.fc = {"a": 0, "b": 0, "z": 0}
        self.p = {"a": 0, "b": 0, "z": 0}
        self.en, self.inv, self.zclr, self.flen = 1, 0, 0, 3
        self.dir, self.err, self.ivld = 1, 0, 0
        self.cnt, self.idx = 0, 0
        self.bits, self.cmd, self.sh = 0, 0, 0
        self.boot, self.armed = 0, 0

    # 寄存器读值（与 SPI 快照同一函数）
    def reg(self, a):
        if a == 0:
            return ID
        if a == 1:
            return self.en | self.inv << 1 | self.zclr << 2 | self.flen << 4
        if a == 2:
            return self.dir | self.err << 1 | self.ivld << 2 | self.f["a"] << 3 | self.f["b"] << 4 | self.f["z"] << 5
        if a == 3:
            return self.cnt
        if a == 4:
            return self.idx
        return 0

    def miso(self):
        sel = not self.sync["c"][1]
        return int(sel and self.bits >= 8 and not (self.cmd >> 7) and (self.sh >> 31) & 1)

    def step(self, w):
        """一个时钟上升沿。w 为本拍输入字；返回沿后的 miso。"""
        if not w & RST:
            self.reset()
            return self.miso()
        s = self.sync
        old = {k: list(v) for k, v in s.items()}           # 沿前的寄存器值（组合逻辑都看它）
        sck_r = not old["k"][1] and old["k"][0]
        sck_f = old["k"][1] and not old["k"][0]
        sel = not old["c"][1]
        mo = old["m"][1]
        f0 = dict(self.f)
        p0 = dict(self.p)
        cnt0, flen0 = self.cnt, self.flen
        # 滤波
        for k in "abz":
            if old[k][1] != f0[k]:
                if self.fc[k] >= flen0:
                    self.f[k], self.fc[k] = old[k][1], 0
                else:
                    self.fc[k] += 1
            else:
                self.fc[k] = 0
        # 解码
        armed0 = self.armed
        da, db = armed0 and f0["a"] ^ p0["a"], armed0 and f0["b"] ^ p0["b"]
        stp = da ^ db
        same = f0["a"] ^ f0["b"]
        fwd = (stp and ((da and same) or (db and not same))) ^ self.inv
        zrise = armed0 and f0["z"] and not p0["z"]
        # SPI
        cmd0, bits0, sh0 = self.cmd, self.bits, self.sh
        wr_done = sel and sck_r and bits0 == 39 and (cmd0 >> 7)
        wdata = ((sh0 << 1) | mo) & M32
        if not sel:
            self.bits, self.cmd, self.sh = 0, 0, 0
        else:
            if sck_r and bits0 < 40:
                self.bits = bits0 + 1
                if bits0 < 8:
                    cn = ((cmd0 << 1) | mo) & 0xFF
                    self.cmd = cn
                    if bits0 == 7:
                        self.sh = 0 if cn >> 7 else self.reg(cn & 0x7F)
                elif cmd0 >> 7:
                    self.sh = wdata
            if sck_f and not (cmd0 >> 7) and 8 < bits0 < 40:
                self.sh = (sh0 << 1) & M32
        # 计数、状态
        en0 = self.en
        self.p = f0
        if self.boot != 3:
            self.boot += 1
        elif not armed0 and all(f0[k] == old[k][1] for k in "abz"):
            self.armed = 1
        if en0 and stp:
            self.cnt = (cnt0 + (1 if fwd else -1)) & M32
            self.dir = int(bool(fwd))
        if en0 and da and db:
            self.err = 1
        if zrise:
            self.idx, self.ivld = cnt0, 1
            if self.zclr and en0:
                self.cnt = 0
        if wr_done:
            a = cmd0 & 0x7F
            if a == 1:
                self.en, self.inv, self.zclr, self.flen = wdata & 1, wdata >> 1 & 1, wdata >> 2 & 1, wdata >> 4 & 0xF
            elif a == 2:
                if wdata >> 1 & 1:
                    self.err = 0
                if wdata >> 2 & 1:
                    self.ivld = 0
            elif a == 3:
                self.cnt = wdata
        # 同步器
        bitsin = {"a": w & A, "b": w & B, "z": w & Z, "k": w & SCK, "c": w & CS, "m": w & MO}
        for k, v in bitsin.items():
            s[k] = [int(bool(v)), old[k][0]]               # [0] 新、[1] 旧，同 RTL 的 {s[0], in}
        return self.miso()


def run(words):
    """逐拍跑一串激励，返回每拍 (cnt, idx, status, miso)。"""
    m = Encif()
    out = []
    for w in words:
        mi = m.step(w)
        out.append((m.cnt, m.idx, m.reg(2), mi))
    return out


# ---------------------------------------------------------------- 激励生成
class Stim:
    """按拍生成激励字。编码器相位 0..3 对应 (A,B) = 00,10,11,01；SPI 由主机按 SCLK = clk/10 发。"""

    def __init__(self):
        self.w = []
        self.ab = 0
        self.z = 0
        self.cs = 1
        self.reads = []                                # [(帧开始拍, 地址)]

    def _word(self, a=None, b=None, z=None, sck=0, cs=None, mo=0, rst=1):
        aa, bb = [(0, 0), (1, 0), (1, 1), (0, 1)][self.ab]
        a = aa if a is None else a
        b = bb if b is None else b
        z = self.z if z is None else z
        cs = self.cs if cs is None else cs
        return a * A | b * B | z * Z | sck * SCK | cs * CS | mo * MO | rst * RST

    def idle(self, n=1, **kw):
        for _ in range(n):
            self.w.append(self._word(**kw))

    def reset(self, n=4):
        self.idle(n, rst=0)
        self.idle(2)

    def move(self, steps, period=8):
        d = 1 if steps > 0 else -1
        for _ in range(abs(steps)):
            self.ab = (self.ab + d) % 4
            self.idle(period)

    def glitch(self, which, width, after=20):
        """在 A 或 B 上打一个宽 width 拍的毛刺"""
        aa, bb = [(0, 0), (1, 0), (1, 1), (0, 1)][self.ab]
        kw = {"a": 1 - aa} if which == "a" else {"b": 1 - bb}
        self.idle(width, **kw)
        self.idle(after)

    def both(self, after=20):
        """A、B 同时跳变（丢步）"""
        self.ab = (self.ab + 2) % 4
        self.idle(after)

    def zpulse(self, width=12, after=12):
        self.z = 1
        self.idle(width)
        self.z = 0
        self.idle(after)

    def spi(self, cmd, data=0, half=5):
        """一帧：CS 拉低，8 位命令 + 32 位数据，模式 0（上升沿采样），SCLK 半周期 half 拍。"""
        self.cs = 0
        self.idle(half)
        bits = [(cmd >> (7 - i)) & 1 for i in range(8)] + [(data >> (31 - i)) & 1 for i in range(32)]
        start = len(self.w)
        for b in bits:
            self.idle(half, sck=0, mo=b)
            self.idle(half, sck=1, mo=b)
        self.idle(half, sck=0)
        self.cs = 1
        self.idle(half * 2)
        return start

    def read(self, addr):
        st = self.spi(addr & 0x7F)
        self.reads.append((st, addr & 0x7F))
        return st

    def write(self, addr, data):
        return self.spi(0x80 | (addr & 0x7F), data & M32)


def spi_read_value(words, outs, start, half=5):
    """从逐拍 miso 里按主机的采样时刻（SCLK 上升沿那一拍）取回 32 位读数"""
    v = 0
    for i in range(32):
        t = start + (8 + i) * 2 * half + half          # 第 9+i 个上升沿施加的那一拍；主机采的是它之前一拍的 MISO
        v = (v << 1) | outs[t - 1][3]
    return v


def cases():
    """各用例：名字 → (激励字列表, 读回检查 [(start, 期望值的取法)])"""
    out = {}

    s = Stim(); s.reset(); s.move(40); s.move(-15)
    out["正反转"] = s

    s = Stim(); s.reset(); s.write(1, 0x01)            # 滤波 N=0
    s.move(64, period=4)
    out["高速"] = s

    s = Stim(); s.reset(); s.move(4)
    for wdt in (1, 2, 3, 4, 5, 6):
        s.glitch("a", wdt)
        s.glitch("b", wdt)
    s.write(1, 0x81)                                   # N=8
    s.move(3, period=16)
    for wdt in (6, 8, 9, 10, 12):
        s.glitch("a", wdt)
    out["毛刺"] = s

    s = Stim(); s.reset(); s.move(5); s.both(); s.move(3)
    s.read(2); s.write(2, 0x2); s.read(2)
    out["丢步"] = s

    s = Stim(); s.reset(); s.move(10); s.zpulse(); s.move(7)
    s.write(1, 0x35); s.zpulse(); s.move(-3); s.read(4); s.read(2)
    out["Z相"] = s

    s = Stim(); s.reset(); s.write(3, 0x7FFFFFFE); s.move(4); s.read(3); s.write(3, 0x00000001); s.move(-3)
    s.read(3)
    out["溢出"] = s

    s = Stim(); s.reset()
    s.read(0); s.read(1); s.write(1, 0x52); s.read(1); s.write(3, 0x12345678); s.read(3)
    s.move(2); s.read(3); s.read(2); s.read(4); s.read(0x55); s.write(1, 0x33); s.read(1)
    s.write(1, 0x30); s.move(5); s.read(3)                # 关计数：不变
    out["SPI读写"] = s

    s = Stim(); s.reset(); s.write(1, 0x13); s.write(3, 99); s.move(6); s.reset(); s.read(1); s.read(3)
    out["复位"] = s

    rnd = random.Random(92)
    s = Stim(); s.reset(); s.write(1, 0x21)
    for _ in range(300):
        r = rnd.random()
        if r < 0.7:
            s.move(rnd.choice([-1, 1]) * rnd.randint(1, 6), period=rnd.randint(4, 12))
        elif r < 0.85:
            s.glitch(rnd.choice("ab"), rnd.randint(1, 3), after=rnd.randint(4, 10))
        elif r < 0.93:
            s.zpulse(width=rnd.randint(4, 10), after=rnd.randint(4, 10))
        else:
            s.read(rnd.choice([2, 3, 4]))
    out["随机"] = s
    return out
