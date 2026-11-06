# -*- coding: utf-8 -*-
"""第 92 轮 E5：编码器接口芯片 WQ-ENCIF。RTL（Icarus Verilog）与参考模型逐拍一致；再按规格书手算的值核对（不只是“两份实现一样”）。
没装 Icarus 时跳过 RTL 那一项。"""
import json
import os
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "wq-encif")
sys.path.insert(0, os.path.join(ROOT, "model"))
import encif as E  # noqa: E402


@pytest.fixture(scope="module")
def sim(tmp_path_factory):
    if not shutil.which("iverilog"):
        pytest.skip("没装 Icarus Verilog")
    out = tmp_path_factory.mktemp("sim")
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tb", "run.py"), "--out", str(out)], capture_output=True, text=True)
    s = json.load(open(out / "summary.json", encoding="utf-8"))
    return r, s, out


def test_rtl_matches_model_every_cycle(sim):
    r, s, _ = sim
    assert r.returncode == 0, r.stdout + r.stderr
    assert s["pass"] and len(s["cases"]) == 9
    assert all(c["match"] for c in s["cases"])
    assert sum(c["cycles"] for c in s["cases"]) > 25000


def test_spec_values(sim):
    """按规格书手算的结果"""
    c = {x["name"]: x for x in sim[1]["cases"]}
    rd = {k: [(r["addr"], r["value"]) for r in v["reads"]] for k, v in c.items()}
    assert c["正反转"]["final"]["count"] == 40 - 15
    assert c["高速"]["final"]["count"] == 64                        # 滤波 0、每 4 拍一个边沿也不丢
    assert c["毛刺"]["final"]["count"] == 4 + 3                     # 毛刺来回各一下，净 0
    assert rd["丢步"] == [(2, 0x1B), (2, 0x19)]                     # 丢步位置 1，写 1 清除
    assert c["丢步"]["final"]["count"] == 5 + 3                     # A、B 同跳不计数
    assert rd["Z相"][0] == (4, 17)                                  # 第二次 Z 锁存 17，同时清零
    assert c["Z相"]["final"]["count"] == -3
    assert rd["溢出"] == [(3, 0x80000002), (3, 0xFFFFFFFE)]          # 32 位回绕
    assert rd["SPI读写"][:4] == [(0, 0x454E4331), (1, 0x31), (1, 0x52), (3, 0x12345678)]
    assert (0x55, 0) in rd["SPI读写"]                                # 没有的地址读 0
    assert rd["SPI读写"][-1] == (3, 0x12345678)                      # 关计数后转动不计
    assert rd["复位"] == [(1, 0x31), (3, 0)]                         # 复位回到默认，计数清零
    assert c["复位"]["final"]["status"] & 0x2 == 0                   # 停在 11 位置复位也不误报丢步


def test_glitch_filter_threshold():
    """滤波长度 N：短于 N+1 拍的毛刺不计，够 N+1 拍的会计（用参考模型；它与 RTL 逐拍一致由上一项保证）"""
    for n in (0, 3, 8):
        for w in range(1, n + 4):
            s = E.Stim()
            s.reset()
            s.write(1, 0x01 | n << 4)
            s.move(2, period=24)
            t0 = len(s.w)
            s.glitch("a", w, after=40)
            cnts = [o[0] for o in E.run(s.w)[t0:]]
            moved = any(x != 2 for x in cnts)
            assert moved == (w >= n + 1), (n, w)


def test_waves_for_web(sim):
    out = sim[2]
    w = json.load(open(out / "01.json", encoding="utf-8"))
    names = [x["name"] for x in w["signals"]]
    assert names[:7] == ["A", "B", "Z", "SCLK", "CS_N", "MOSI", "MISO"] and "计数" in names
    cnt = next(x for x in w["signals"] if x["name"] == "计数")
    assert cnt["pts"][-1][1] == "25"
