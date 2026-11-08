# -*- coding: utf-8 -*-
"""第 100、102 轮：把固件源码整理成页面用的 out/fw.json，打包 out/wq-drv-b-fw.zip（源码 + fw.elf + 仿真脚本）。
zip 不压缩、时间戳固定，内容一样则字节一样（CI 逐字核对）。先跑 run.py（会编译）。"""
import json
import os
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
SRC = [("src/main.c", "c", "主程序：编码器管理、状态机、指令、保护、CAN 发送"),
       ("src/motor.c", "c", "电机控制：20 kHz FOC 电流环、速度环、位置环与轨迹、对零（第 102 轮）"),
       ("src/motor.h", "c", "电机参数、控制遥测区 mc（第 102 轮）"),
       ("src/can_proto.h", "c", "CAN 协议：帧 ID、格式、状态、故障码（第 102 轮）"),
       ("src/can.c", "c", "FDCAN1 驱动：初始化、发送、接收中断（第 102 轮）"),
       ("src/can.h", "c", "CAN 接口"),
       ("src/clock.c", "c", "时钟：HSI16 → PLL 170 MHz（第 102 轮）"),
       ("src/clock.h", "c", "时钟接口"),
       ("src/ssi.c", "c", "输出端绝对值编码器 SSI 驱动：SPI3、帧解析（第 107 轮）"),
       ("src/ssi.h", "c", "SSI 接口"),
       ("src/brake.c", "c", "抱闸：TIM4 CH1（PB6）PWM、过励与保持（第 110 轮）；线圈电流检测 PB0、断线 / 过流 / 抱不住（第 114 轮）"),
       ("src/brake.h", "c", "抱闸接口与时间参数（第 110 轮）"),
       ("src/encif.c", "c", "WQ-ENCIF 驱动：SPI1、片选、复位、40 位帧（第 100 轮）"),
       ("src/encif.h", "c", "驱动接口与寄存器号"),
       ("src/regs.h", "c", "用到的 STM32G431 寄存器（对照 ST 官方 CMSIS 头文件核对）"),
       ("src/startup.c", "c", "启动代码与向量表"),
       ("src/stm32g431.ld", "ld", "链接脚本"),
       ("Makefile", "make", "编译"),
       ("renode/stm32g431.repl", "repl", "Renode 平台描述"),
       ("renode/WqEncif.cs", "cs", "WQ-ENCIF 寄存器级模型 + 虚拟电机（第 100 轮）"),
       ("renode/WqDrive.cs", "cs", "TIM1 + 逆变桥 + 电机 + 减速器 + 负载、ADC1、FDCAN1 与仿真主站（第 102 轮）、SSI 编码器（第 107 轮）、TIM4 + 抱闸（第 110 轮）"),
       ("run.py", "py", "编码器六个场景与判据（第 100 轮）"),
       ("run_motor.py", "py", "电机控制与 CAN 十七个场景与判据（第 102、107、110、114 轮）"),
       ("master/master.py", "py", "多关节 CAN 主站：两关节水平臂走直线、报警 / 掉线全停（第 115 轮）"),
       ("run_master.py", "py", "主站在环仿真：Renode 两台驱动板一拍一拍推进、三个场景与判据（第 115 轮）"),
       ("README.md", "md", "说明")]
BIN = ["build/fw.elf", "build/fw.bin"]


def main():
    sim = json.load(open(os.path.join(OUT, "sim.json"), encoding="utf-8"))
    files = []
    for p, lang, note in SRC:
        t = open(os.path.join(HERE, p), encoding="utf-8").read()
        files.append(dict(path=p, lang=lang, note=note, lines=t.count("\n"), text=t))
    sm = json.load(open(os.path.join(OUT, "sim_motor.json"), encoding="utf-8"))
    doc = dict(round=115, firmware=sm["firmware"], files=files, zip="wq-drv-b-fw.zip",
               disclaimer=sim["disclaimer"])
    with open(os.path.join(OUT, "fw.json"), "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
        f.write("\n")
    with zipfile.ZipFile(os.path.join(OUT, "wq-drv-b-fw.zip"), "w", zipfile.ZIP_STORED) as z:
        for p in [s[0] for s in SRC] + BIN + ["out/sim.json", "out/sim_motor.json", "out/sim_master.json"]:
            zi = zipfile.ZipInfo("wq-drv-b-fw/" + p, date_time=(2026, 11, 6, 0, 0, 0))
            zi.external_attr = 0o644 << 16
            z.writestr(zi, open(os.path.join(HERE, p), "rb").read())
    print("fw.json、wq-drv-b-fw.zip 已写")


if __name__ == "__main__":
    main()
