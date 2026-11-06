# -*- coding: utf-8 -*-
"""第 100 轮：驱动板 B 版示例固件（经 SPI1 读 WQ-ENCIF）在 Renode 里的六个场景全过；页面用的源码与仓库一致；
平台描述、固件寄存器地址、B 版原理图引脚三处一致。（重新编译、重跑仿真在 CI“电路板设计（KiCad）”任务里，这里只读产物。）"""
import json
import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
DES = os.path.dirname(HERE)
FW = os.path.join(DES, "drv-joint-b", "fw")
sys.path.insert(0, os.path.join(DES, "tools"))
import drv_joint_b as B  # noqa: E402


def _j(p):
    return json.load(open(os.path.join(FW, "out", p), encoding="utf-8"))


def _t(p):
    return open(os.path.join(FW, p), encoding="utf-8").read()


def test_six_scenarios_pass():
    s = _j("sim.json")
    assert s["all_pass"] and [x["id"] for x in s["scenarios"]] == ["boot", "fwd", "rev", "index", "err", "absent"]
    for sc in s["scenarios"]:
        assert sc["checks"] and all(c["ok"] for c in sc["checks"]), sc["id"]
        n = int(round(max(p[0] for p in sc["profile"]) / s["step_s"])) if sc["id"] != "absent" else None
        assert len(sc["series"]["t"]) == len(sc["series"]["cnt"]) == len(sc["series"]["rpm"])
        assert n is None or len(sc["series"]["t"]) >= n
    fw = s["firmware"]
    assert 0 < fw["flash"] <= 128 * 1024 and fw["ram"] <= 22 * 1024
    assert "不投产" in s["disclaimer"] and "未流片" in s["disclaimer"]
    fin = {x["id"]: x["final"] for x in s["scenarios"]}
    assert fin["boot"]["id"] == 0x454E4331 and fin["boot"]["ctrl"] == 0x31
    assert fin["absent"]["state"] == 1 and fin["err"]["err_count"] == 1


def test_page_sources_match_repo():
    d = _j("fw.json")
    for f in d["files"]:
        assert f["text"] == _t(f["path"]), f["path"]
    with zipfile.ZipFile(os.path.join(FW, "out", d["zip"])) as z:
        names = set(z.namelist())
    assert {"wq-drv-b-fw/build/fw.elf", "wq-drv-b-fw/src/main.c", "wq-drv-b-fw/renode/WqEncif.cs", "wq-drv-b-fw/run.py"} <= names


def test_addresses_and_pins_consistent():
    regs, repl = _t("src/regs.h"), _t("renode/stm32g431.repl")
    for name, addr in (("RCC_BASE", "0x40021000"), ("GPIOA_BASE", "0x48000000"), ("GPIOB_BASE", "0x48000400"), ("SPI1_BASE", "0x40013000")):
        assert re.search(r"#define {} {}u".format(name, addr), regs), name
        assert addr in repl, addr
    # B 版原理图：PA4–PA7 = MCU 第 12–15 脚接芯片 SPI，PB1 = 第 17 脚接芯片复位（STM32G431CBTx LQFP-48）
    mcu = next(p for p in B.PARTS if p["ref"] == "U10")["pins"]
    assert [mcu[k] for k in ("12", "13", "14", "15", "17")] == ["ENC_CS_N", "ENC_SCK", "ENC_MISO", "ENC_MOSI", "ENC_RST_N"]
    drv = _t("src/encif.c")
    assert "PA4 片选" in drv and "PB1 芯片复位" in drv
    assert "gpioPortA: { 4 -> encif@0 }" in _t("run.py") and "gpioPortB: { 1 -> encif@1 }" in _t("run.py")
    # 编码器线数与第 88 轮设计一致：2500 线 ×4
    j3 = next(p for p in B.PARTS if p["ref"] == "J3")
    assert "2500 线" in j3["note"] and "#define CPR 10000" in _t("src/main.c") and "CPR = 10000" in _t("renode/WqEncif.cs")
