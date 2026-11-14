# -*- coding: utf-8 -*-
"""第 159 轮 159f：把固件源码整理成页面用的 out/fw.json，打包 out/ctrl-ls-fw.zip（源码 + fw.elf + 仿真脚本与结果）。
zip 不压缩、时间戳固定，内容一样则字节一样（CI 逐字核对）。先跑 run_sew.py（会编译）。同驱动板 B 版 pack.py 的做法。"""
import json
import os
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
SRC = [("src/main.c", "c", "主程序：开机顺序、主循环"),
       ("src/sew.c", "c", "缝纫状态机：脚踏、起缝加固、停针、剪线、拨线、抬压脚；电磁铁输出"),
       ("src/sew.h", "c", "缝纫状态、面板设置 cfg、遥测区 sw"),
       ("src/motor.c", "c", "主轴电机：16 kHz 磁场定向控制、速度观测器、速度环、停针位置环、对零、找 Z 相、保护"),
       ("src/motor.h", "c", "电机参数、遥测区 mc"),
       ("src/clock.c", "c", "时钟：HSI16 → PLL 170 MHz（同驱动板 B 版）"),
       ("src/clock.h", "c", "时钟接口"),
       ("src/regs.h", "c", "用到的 STM32G431 寄存器（对照 ST 官方 CMSIS 头文件核对）"),
       ("src/startup.c", "c", "启动代码与向量表"),
       ("src/stm32g431.ld", "ld", "链接脚本"),
       ("Makefile", "make", "编译"),
       ("renode/stm32g431.repl", "repl", "Renode 平台描述"),
       ("renode/WqSew.cs", "cs", "TIM1 + 功率模块 + 电机 + 主轴一转负载 + Z 相 + 电磁铁、TIM4 编码器、ADC1/ADC2"),
       ("renode/load_table.txt", "txt", "第 138 轮 G2 一转负载表（gen_load.py 生成）"),
       ("gen_load.py", "py", "生成一转负载表"),
       ("ref_159c.py", "py", "从 159c 的模型多取两个对照量"),
       ("run_sew.py", "py", "四个场景与判据"),
       ("README.md", "md", "说明")]
BIN = ["build/fw.elf", "build/fw.bin"]


def main():
    sim = json.load(open(os.path.join(OUT, "sim_sew.json"), encoding="utf-8"))
    files = []
    for p, lang, note in SRC:
        t = open(os.path.join(HERE, p), encoding="utf-8").read()
        files.append(dict(path=p, lang=lang, note=note, lines=t.count("\n"), text=t))
    doc = dict(round=159, firmware=sim["firmware"], files=files, zip="ctrl-ls-fw.zip", disclaimer=sim["disclaimer"])
    with open(os.path.join(OUT, "fw.json"), "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
        f.write("\n")
    with zipfile.ZipFile(os.path.join(OUT, "ctrl-ls-fw.zip"), "w", zipfile.ZIP_STORED) as z:
        for p in [s[0] for s in SRC] + BIN + ["out/sim_sew.json", "out/ref_159c.json"]:
            zi = zipfile.ZipInfo("ctrl-ls-fw/" + p, date_time=(2026, 11, 13, 0, 0, 0))
            zi.external_attr = 0o644 << 16
            z.writestr(zi, open(os.path.join(HERE, p), "rb").read())
    print("fw.json、ctrl-ls-fw.zip 已写")


if __name__ == "__main__":
    main()
