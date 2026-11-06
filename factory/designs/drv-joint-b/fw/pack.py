# -*- coding: utf-8 -*-
"""第 100 轮：把固件源码整理成页面用的 out/fw.json，打包 out/wq-drv-b-fw.zip（源码 + fw.elf + 仿真脚本）。
zip 不压缩、时间戳固定，内容一样则字节一样（CI 逐字核对）。先跑 run.py（会编译）。"""
import json
import os
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
SRC = [("src/main.c", "c", "主程序：1 kHz 读数、转速、Z 相、错误、芯片缺失"),
       ("src/encif.c", "c", "WQ-ENCIF 驱动：SPI1、片选、复位、40 位帧"),
       ("src/encif.h", "c", "驱动接口与寄存器号"),
       ("src/regs.h", "c", "用到的 STM32G431 寄存器（RM0440）"),
       ("src/startup.c", "c", "启动代码与向量表"),
       ("src/stm32g431.ld", "ld", "链接脚本"),
       ("Makefile", "make", "编译"),
       ("renode/stm32g431.repl", "repl", "Renode 平台描述"),
       ("renode/WqEncif.cs", "cs", "WQ-ENCIF 寄存器级模型 + 虚拟电机"),
       ("run.py", "py", "六个场景与判据"),
       ("README.md", "md", "说明")]
BIN = ["build/fw.elf", "build/fw.bin"]


def main():
    sim = json.load(open(os.path.join(OUT, "sim.json"), encoding="utf-8"))
    files = []
    for p, lang, note in SRC:
        t = open(os.path.join(HERE, p), encoding="utf-8").read()
        files.append(dict(path=p, lang=lang, note=note, lines=t.count("\n"), text=t))
    doc = dict(round=100, firmware=sim["firmware"], files=files, zip="wq-drv-b-fw.zip",
               disclaimer=sim["disclaimer"])
    with open(os.path.join(OUT, "fw.json"), "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
        f.write("\n")
    with zipfile.ZipFile(os.path.join(OUT, "wq-drv-b-fw.zip"), "w", zipfile.ZIP_STORED) as z:
        for p in [s[0] for s in SRC] + BIN + ["out/sim.json"]:
            zi = zipfile.ZipInfo("wq-drv-b-fw/" + p, date_time=(2026, 11, 6, 0, 0, 0))
            zi.external_attr = 0o644 << 16
            z.writestr(zi, open(os.path.join(HERE, p), "rb").read())
    print("fw.json、wq-drv-b-fw.zip 已写")


if __name__ == "__main__":
    main()
