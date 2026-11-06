# -*- coding: utf-8 -*-
"""整理“芯片设计”页要的东西：out/design.json（规格、引脚、寄存器表、Verilog 原文、仿真与版图结论）和下载包 out/wq-encif.zip（不压缩、日期固定，逐字可复现）。
用法：python3 tools/pack.py（在仿真 tb/run.py 之后；版图产物 out/layout/ 有就一起打包）"""
import hashlib
import json
import os
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "out")

PINS = [
    ("clk", "输入", "时钟 50 MHz"), ("rst_n", "输入", "复位，低有效"),
    ("enc_a", "输入", "编码器 A 相"), ("enc_b", "输入", "编码器 B 相"), ("enc_z", "输入", "编码器 Z 相（每转一个）"),
    ("sclk", "输入", "SPI 时钟（≤ 5 MHz，即时钟的 1/10）"), ("cs_n", "输入", "SPI 片选，低有效"), ("mosi", "输入", "SPI 主机发、芯片收"),
    ("miso", "输出", "SPI 芯片发、主机收"),
]
REGS = [
    {"addr": "0x00", "name": "ID", "access": "只读", "reset": "0x454E4331", "bits": [["31:0", "芯片标识 “ENC1”"]]},
    {"addr": "0x01", "name": "CTRL", "access": "读写", "reset": "0x00000031", "bits": [["0", "计数使能"], ["1", "方向取反"], ["2", "Z 相上升沿清零计数"], ["7:4", "滤波长度 N（0–15）：输入要连续 N+1 拍与当前不同才认"]]},
    {"addr": "0x02", "name": "STATUS", "access": "读 / 写 1 清除", "reset": "0x00000001", "bits": [["0", "最近方向（1 = 正转）"], ["1", "丢步：A、B 同时跳变（粘住，写 1 清除）"], ["2", "已锁存 Z 位置（粘住，写 1 清除）"], ["3", "A（滤波后）"], ["4", "B（滤波后）"], ["5", "Z（滤波后）"]]},
    {"addr": "0x03", "name": "COUNT", "access": "读写", "reset": "0x00000000", "bits": [["31:0", "32 位有符号计数（4 倍频：每个边沿 ±1）；写入 = 置数"]]},
    {"addr": "0x04", "name": "INDEX", "access": "只读", "reset": "0x00000000", "bits": [["31:0", "Z 相上升沿那一拍的计数"]]},
]
BLOCKS = [
    {"key": "sync", "name": "同步器", "desc": "每路输入过两级触发器，避免外部信号和芯片时钟不同步造成亚稳态"},
    {"key": "filter", "name": "数字滤波", "desc": "输入与当前值不同、并且连续 N+1 拍都不同才改：短于 N+1 拍（N=3 时 80 ns）的毛刺被滤掉"},
    {"key": "decode", "name": "4 倍频解码", "desc": "A、B 每个边沿都计一步：A 超前 B 为正转 +1；A、B 同时跳变说明漏了边沿，报“丢步”"},
    {"key": "count", "name": "计数与 Z 锁存", "desc": "32 位计数；Z 相上升沿把当时的计数存进 INDEX（可选同时清零），用来找零位"},
    {"key": "spi", "name": "SPI 从机", "desc": "模式 0：8 位命令（最高位 1 = 写，低 7 位地址）+ 32 位数据，高位先出；读的值在命令收齐那一拍取快照，读计数不会读到一半变了的数"},
]
FILES = ["rtl/wq_encif.v", "tb/tb.v", "tb/run.py", "model/encif.py", "flow/config.json", "flow/run.sh", "flow/collect.py", "flow/render.py",
         "flow/schmitt.py", "tools/pack.py"]
LAYOUT = ["wq_encif.gds", "wq_encif.nl.v", "wq_encif.def", "wq_encif.sdc", "metrics.json", "result.json", "layout.json"]


def j(p):
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None


def main():
    rtl = open(os.path.join(ROOT, "rtl", "wq_encif.v"), encoding="utf-8").read()
    sim = j(os.path.join(OUT, "sim", "summary.json"))
    lay = j(os.path.join(OUT, "layout", "result.json"))
    img = j(os.path.join(OUT, "layout", "layout.json"))
    sch = j(os.path.join(OUT, "transistor", "schmitt.json"))
    d = {"name": "WQ-ENCIF 编码器接口芯片", "name_en": "WQ-ENCIF incremental encoder interface", "rev": "示例 A",
         "disclaimer": "示例设计，未流片，未经硅验证", "clock_mhz": 50, "pdk": "SKY130（开源工艺库，130 nm）",
         "pins": [{"name": a, "dir": b, "desc": c} for a, b, c in PINS], "regs": REGS, "blocks": BLOCKS,
         "rtl": rtl, "rtl_lines": rtl.count("\n"),
         "sim": sim, "layout": lay, "images": img,
         "transistor": None if not sch else {"pass": sch["pass"], "design": sch["design"], "hyst": sch["nominal"]["hyst"],
                                             "generic": sch["generic"], "file": "transistor/schmitt.json"},
         "files": {f: hashlib.sha256(open(os.path.join(ROOT, f), "rb").read()).hexdigest()[:16] for f in FILES}}
    with open(os.path.join(OUT, "design.json"), "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    zp = os.path.join(OUT, "wq-encif.zip")
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_STORED) as z:
        def add(src, arc):
            zi = zipfile.ZipInfo(arc, date_time=(2026, 11, 5, 0, 0, 0))
            zi.external_attr = 0o644 << 16
            z.writestr(zi, open(src, "rb").read())
        for f in FILES:
            add(os.path.join(ROOT, f), "wq-encif/" + f)
        add(os.path.join(OUT, "sim", "summary.json"), "wq-encif/out/sim/summary.json")
        for f in LAYOUT:
            p = os.path.join(OUT, "layout", f)
            if os.path.exists(p):
                add(p, "wq-encif/out/layout/" + f)
        p = os.path.join(OUT, "transistor", "schmitt.json")
        if os.path.exists(p):
            add(p, "wq-encif/out/transistor/schmitt.json")
    print("design.json，下载包", os.path.getsize(zp), "字节")


if __name__ == "__main__":
    main()
