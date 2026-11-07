# -*- coding: utf-8 -*-
"""关节驱动板 DRV-JOINT：从设计描述（drv_joint.py）生成 KiCad 工程和全部产物（第 88 轮，电子 E4）。

    python3 build.py              # 全部重新生成（原理图、PCB 自动布线、导出、可制造性检查）
    python3 build.py --no-route   # 不重新布线：沿用仓库里的 PCB，只重新导出与检查

要：KiCad 7.0.11（kicad-cli 和 pcbnew Python 模块）、Java、xvfb-run（无界面机器）、Freerouting 1.9.0 的 jar（环境变量 FREEROUTING_JAR）。
产物写到 ../drv-joint/：kicad/（KiCad 工程，可以用 KiCad 打开继续改）、out/（网页和工厂用的产物）。
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
ROOT = os.path.dirname(HERE)
PROJ = os.path.join(ROOT, "drv-joint")
KDIR = os.path.join(PROJ, "kicad")
OUT = os.path.join(PROJ, "out")
MODELS = os.path.join(ROOT, "3dmodels")
NAME = "drv-joint"
DATE = "2026-11-05"

import drv_joint as D  # noqa: E402
import sch  # noqa: E402

LAYERS_SVG = [("F_Cu", "F.Cu,Edge.Cuts", "顶层铜"), ("In1_Cu", "In1.Cu,Edge.Cuts", "内层 1（地平面）"), ("In2_Cu", "In2.Cu,Edge.Cuts", "内层 2"),
              ("B_Cu", "B.Cu,Edge.Cuts", "底层铜"), ("F_Silk", "F.SilkS,F.Fab,Edge.Cuts", "顶面丝印与装配"),
              ("B_Silk", "B.SilkS,B.Fab,Edge.Cuts", "底面丝印与装配")]
# 母线、电机线走宽线；半桥中点 SW 的大电流走铺铜（drv_joint.POURS），布线器只给它连驱动、自举电容这些细支路
CLASSES = {"Power": (2.5, 0.3, ["VBUS", "MOT_A", "MOT_B", "MOT_C"], ["F.Cu", "B.Cu"]),
           "Branch": (0.5, 0.3, ["SW_A", "SW_B", "SW_C"], ["F.Cu", "B.Cu"]),
           "Supply": (0.25, 0.15, ["+12V", "+5V", "+3V3", "SW12", "VB_A", "VB_B", "VB_C"], ["F.Cu", "In2.Cu", "B.Cu"]),
           "Ground": (0.25, 0.15, ["GND"])}
SEVERITY = {"silk_overlap": "warning", "silk_over_copper": "warning", "silk_edge_clearance": "warning", "text_height": "warning",
            "text_thickness": "warning", "lib_footprint_issues": "ignore", "lib_footprint_mismatch": "ignore", "footprint_type_mismatch": "ignore"}


def env():
    e = dict(os.environ)
    e["KICAD6_3DMODEL_DIR"] = MODELS
    e["KICAD7_3DMODEL_DIR"] = MODELS
    return e


def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, env=env(), **kw)
    if r.returncode != 0:
        raise RuntimeError("{} 失败：{}{}".format(" ".join(cmd[:4]), r.stdout[-1500:], r.stderr[-1500:]))
    return r


# ------------------------------------------------------------------ 原理图
def schematic():
    os.makedirs(KDIR, exist_ok=True)
    D.SHEET_NOTES = SHEET_NOTES
    if any(p["lib"].startswith("wq:") for p in D.PARTS):          # 工程自带符号库（B 版的 WQ-ENCIF）随工程走
        shutil.copy(os.path.join(ROOT, "libs", "wq.kicad_sym"), os.path.join(KDIR, "wq.kicad_sym"))
        with open(os.path.join(KDIR, "sym-lib-table"), "w", encoding="utf-8") as f:
            f.write('(sym_lib_table\n  (lib (name "wq")(type "KiCad")(uri "${KIPRJMOD}/wq.kicad_sym")(options "")(descr "问渠：编码器接口芯片 WQ-ENCIF"))\n)\n')
    return sch.write(D, KDIR, NAME)


SHEET_NOTES = {
    "power": "48 V 从 J1 进；母线电容 C1 470 μF / 63 V（例题 3）；R1、R2、R3 分压给 MCU 测母线电压（48 V → 3.0 V）。示例设计，未经硬件验证。",
    "aux": "U1 LMR16006Y 把 48 V 降到 12 V（栅极驱动用），U2、U3 线性稳压出 5 V（编码器、CAN）和 3.3 V（MCU、采样放大）。L1 22 μH、反馈 147 k / 10 k 的算法见设计说明。",
    "bridge": "三个半桥，每相上下两个 MOSFET（示例选型 BSC040N08NS5，80 V）；C11–C13 每相就近吸收开关电流。",
    "gate": "每相一片半桥驱动 IR2101S：上管靠自举（D、C 1 μF）供电；栅极电阻 10 Ω（例题 2）；死区由 MCU 定时器给。",
    "sense": "相线上串 2 mΩ 采样电阻（R21–R23），INA240A1 放大 20 倍：40 mV/A，零点 1.65 V，量程 ±41 A（例题 1）。J2 接电机三相。",
    "mcu": "STM32G431（示例选型）：TIM1 三相互补 PWM、ADC 采三相电流与母线电压、TIM3 编码器、SPI1 读 SSI、FDCAN1；8 MHz 晶振；TP1–TP5 是烧录口和电源测试点。",
    "io": "J3 增量编码器 A/B/Z 经 1 kΩ / 220 pF 滤波（例题 4）进 MCU；J4 输出端绝对值编码器 SSI（两片 RS-485 收发）；J5 CAN（MCP2562，120 Ω 终端）。",
}


# ------------------------------------------------------------------ PCB
def pcb_build(jar):
    import pcbnew

    import pcb
    path = os.path.join(KDIR, NAME + ".kicad_pcb")
    board, nets = pcb.build(D, D.PLACEMENT, path, D.HOLES)
    w, h = D.BOARD_MM
    z = pcb.add_zone(board, nets["GND"], pcbnew.In1_Cu, w, h)
    z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
    for net, layer, pts in getattr(D, "POURS", []):
        pcb.add_pour(board, nets[net], layer, pts)
    work = os.path.join(PROJ, ".route")
    os.makedirs(work, exist_ok=True)
    keep = [(lay, pts) for _, lay, pts in getattr(D, "POURS", [])]
    keep += _tie_keepouts(board)
    ntr, nvia = pcb.autoroute(board, work, jar, CLASSES, passes=50, keepouts=keep)
    board.BuildConnectivity()
    pcb.fill_zones(board)
    pcbnew.SaveBoard(path, board)
    _project_settings()
    return ntr, nvia


def _tie_keepouts(board):
    """网络连接点两个焊盘之间那段铜（不属于任何网络）：布线器不知道它，走线别压上去——在 DSN 里设成小禁布区"""
    import pcbnew
    out = []
    for fp in board.GetFootprints():
        if not fp.GetReference().startswith("NT"):
            continue
        a, b = [p.GetPosition() for p in sorted(fp.Pads(), key=lambda p: p.GetNumber())]
        ax, ay, bx, by = (pcbnew.ToMM(v) - 100 for v in (a.x, a.y, b.x, b.y))
        L = ((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5
        ux, uy = (bx - ax) / L, (by - ay) / L
        sx, sy = ax + ux * 0.3, ay + uy * 0.3             # 两端各让出 0.3 mm 给焊盘接线
        ex, ey = bx - ux * 0.3, by - uy * 0.3
        nx, ny = -uy * 0.4, ux * 0.4                      # 宽 0.8 mm，不往里缩
        out.append(("F.Cu", [(sx + nx, sy + ny), (ex + nx, ey + ny), (ex - nx, ey - ny), (sx - nx, sy - ny)], 0.0))
    return out


def _project_settings():
    """工程文件里写线宽类别和规则严重程度（丝印类问题不影响电气和制造，降为警告）"""
    pro = os.path.join(KDIR, NAME + ".kicad_pro")
    with open(pro, encoding="utf-8") as f:
        d = json.load(f)
    ds = d.setdefault("board", {}).setdefault("design_settings", {})
    ds.setdefault("rule_severities", {}).update(SEVERITY)
    ns = d.setdefault("net_settings", {})
    base = (ns.get("classes") or [{}])[0]
    classes = [base]
    pats = []
    for name, (w, c, members, *_) in CLASSES.items():
        if name == "Ground":
            continue
        cl = dict(base)
        cl.update({"name": name, "track_width": w, "clearance": c})
        classes.append(cl)
        pats += [{"netclass": name, "pattern": m} for m in members]
    ns["classes"] = classes
    ns["netclass_patterns"] = pats
    d.setdefault("meta", {})["filename"] = NAME + ".kicad_pro"
    with open(pro, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")


# ------------------------------------------------------------------ 导出
def _norm_text(path, pats):
    with open(path, encoding="utf-8", errors="replace") as f:
        t = f.read()
    for a, b in pats:
        t = re.sub(a, b, t)
    with open(path, "w", encoding="utf-8") as f:
        f.write(t)


def exports():
    sch_root = os.path.join(KDIR, NAME + ".kicad_sch")
    pcbf = os.path.join(KDIR, NAME + ".kicad_pcb")
    os.makedirs(os.path.join(PROJ, ".route"), exist_ok=True)       # 中间文件（不入库；CI 里一开始没有）
    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    os.makedirs(os.path.join(OUT, "schematic"))
    os.makedirs(os.path.join(OUT, "pcb"))
    # 原理图：每页 SVG
    run(["kicad-cli", "sch", "export", "svg", "-o", os.path.join(OUT, "schematic"), sch_root])
    SVGDATE = [(r"(<title>SVG Image created as [^<]*?) date [^<]*</title>", r"\1 date {}</title>".format(DATE))]
    for fn in os.listdir(os.path.join(OUT, "schematic")):
        _norm_text(os.path.join(OUT, "schematic", fn), SVGDATE)
    # 网表（检查原理图连接用）
    net = os.path.join(PROJ, ".route", "sch.net")
    run(["kicad-cli", "sch", "export", "netlist", "-o", net, sch_root])
    # PCB 各层 SVG
    for key, layers, _ in LAYERS_SVG:
        run(["kicad-cli", "pcb", "export", "svg", "--exclude-drawing-sheet", "--page-size-mode", "2", "-l", layers,
             "-o", os.path.join(OUT, "pcb", key + ".svg"), pcbf])
        _norm_text(os.path.join(OUT, "pcb", key + ".svg"), SVGDATE)
    # Gerber + 钻孔 → zip
    gdir = os.path.join(PROJ, ".route", "gerber")
    if os.path.isdir(gdir):
        shutil.rmtree(gdir)
    os.makedirs(gdir)
    run(["kicad-cli", "pcb", "export", "gerbers", "--no-x2", "--no-netlist", "-l",
         "F.Cu,In1.Cu,In2.Cu,B.Cu,F.Paste,B.Paste,F.SilkS,B.SilkS,F.Mask,B.Mask,Edge.Cuts", "-o", gdir + "/", pcbf])
    run(["kicad-cli", "pcb", "export", "drill", "--format", "excellon", "--excellon-separate-th", "--generate-map", "--map-format", "gerberx2",
         "-o", gdir + "/", pcbf])
    for fn in sorted(os.listdir(gdir)):
        _norm_text(os.path.join(gdir, fn), [(r"(?m)^G04 Created by KiCad.*\n", ""), (r"(?m)^; DRILL file .* date .*\n", ""),
                                             (r"(?m)^;.*[Dd]ate.*\n", ""), (r"(?m)^G04 .*[Dd]ate.*\n", ""), (r"%TF.CreationDate[^%]*%\*?%?\n?", ""),
                                             (r'"CreationDate": "[^"]*"', '"CreationDate": "{}T00:00:00"'.format(DATE))])
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:   # 不压缩：各版本 zlib 压出来的字节不同
        for fn in sorted(os.listdir(gdir)):
            zi = zipfile.ZipInfo(fn, date_time=(2026, 11, 5, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_STORED
            with open(os.path.join(gdir, fn), "rb") as f:
                z.writestr(zi, f.read())
    with open(os.path.join(OUT, "gerber.zip"), "wb") as f:
        f.write(buf.getvalue())
    # 贴片坐标
    run(["kicad-cli", "pcb", "export", "pos", "--format", "csv", "--units", "mm", "--side", "both",
         "-o", os.path.join(OUT, "pos.csv"), pcbf])
    # 三维：STEP（FreeCAD）→ GLB（网页）
    step = os.path.join(OUT, NAME + ".step")
    run(["kicad-cli", "pcb", "export", "step", "--subst-models", "--force", "-o", step, pcbf])
    _norm_text(step, [(r"FILE_NAME\('[^']*','[^']*'", "FILE_NAME('{}.step','{}T00:00:00'".format(NAME, DATE))])
    glb(step, os.path.join(OUT, NAME + ".glb"))
    # BOM
    bom(os.path.join(OUT, "bom.csv"))
    # KiCad 工程打包下载
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:   # 不压缩：各版本 zlib 压出来的字节不同
        for fn in sorted(os.listdir(KDIR)):
            if fn.endswith((".kicad_sch", ".kicad_pcb", ".kicad_pro")):
                zi = zipfile.ZipInfo("drv-joint/" + fn, date_time=(2026, 11, 5, 0, 0, 0))
                zi.compress_type = zipfile.ZIP_STORED
                with open(os.path.join(KDIR, fn), "rb") as f:
                    z.writestr(zi, f.read())
    with open(os.path.join(OUT, "kicad-project.zip"), "wb") as f:
        f.write(buf.getvalue())
    return net


def glb(step, out):
    """STEP → GLB（顶点单位米，Y 向上，与零件库三维查看器同一约定）"""
    import trimesh
    from build123d import import_step
    shape = import_step(step)
    scene = trimesh.Scene()
    solids = shape.solids() if hasattr(shape, "solids") else [shape]
    for i, s in enumerate(solids):
        verts, tris = s.tessellate(0.05, 0.5)
        if not tris:
            continue
        v = [(p.X / 1000, p.Z / 1000, -p.Y / 1000) for p in verts]
        m = trimesh.Trimesh(vertices=v, faces=tris, process=False)
        scene.add_geometry(m, node_name="s{}".format(i))
    data = scene.export(file_type="glb")
    with open(out, "wb") as f:
        f.write(data)


def bom(path):
    """BOM：同物料编号、同数值、同封装合一行；带电路板厂物料编号"""
    rows = {}
    for p in D.PARTS:
        if not p["item"]:
            continue
        k = (p["item"], p["value"], p["fp"].split(":")[1])
        rows.setdefault(k, []).append(p["ref"])
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["物料编号", "数值", "封装", "数量", "位号", "说明"])
        for (item, val, fp), refs in sorted(rows.items(), key=lambda kv: (kv[0][0], kv[0][1])):
            note = next(p["note"] for p in D.PARTS if p["ref"] == refs[0])
            w.writerow([item, val, fp, len(refs), " ".join(sorted(refs, key=_refkey)), note])


def _refkey(r):
    m = re.match(r"([A-Z]+)(\d+)", r)
    return (m.group(1), int(m.group(2))) if m else (r, 0)


# ------------------------------------------------------------------ 检查
def drc():
    """KiCad 设计规则检查（读工程文件里的严重程度）→ out/drc.json"""
    import pcbnew
    board = pcbnew.LoadBoard(os.path.join(KDIR, NAME + ".kicad_pcb"))
    rpt = os.path.join(PROJ, ".route", "drc.rpt")
    pcbnew.WriteDRCReport(board, rpt, pcbnew.EDA_UNITS_MILLIMETRES, True)
    with open(rpt, encoding="utf-8") as f:
        txt = f.read()
    items = []
    for m in re.finditer(r"\[(\w+)\]: ([^\n]*)\n\s*([^\n]*); Severity: (\w+)\n((?:\s+@\([^\n]*\n)+)", txt):
        locs = re.findall(r"@\(([-\d.]+) mm, ([-\d.]+) mm\): ([^\n]*)", m.group(5))
        items.append({"code": m.group(1), "text": m.group(2).strip(), "severity": m.group(4),
                      "at": [[round(float(x) - 100, 2), round(float(y) - 100, 2), what.strip()] for x, y, what in locs]})
    unc = re.search(r"Found (\d+) unconnected pads", txt)
    return {"errors": sum(1 for i in items if i["severity"] == "error"), "warnings": sum(1 for i in items if i["severity"] == "warning"),
            "unconnected": int(unc.group(1)) if unc else None, "items": items}


def summary(drc_res, dfm_res, route_stats, sch_net):
    import pcbnew
    board = pcbnew.LoadBoard(os.path.join(KDIR, NAME + ".kicad_pcb"))
    tracks = [t for t in board.GetTracks() if t.GetClass() == "PCB_TRACK"]
    vias = [t for t in board.GetTracks() if t.GetClass() == "PCB_VIA"]
    sheets = sorted(os.listdir(os.path.join(OUT, "schematic")))
    sheet_files = {}
    for i, (key, name, en) in enumerate(D.SHEETS):   # kicad-cli 按页码命名：drv-joint-<页> <页名>.svg（页名里的 / 换成 _）
        sheet_files[key] = next((s for s in sheets if s.startswith("{}-{} ".format(NAME, i + 1))), None)
    d = {
        "name": "关节伺服驱动板 DRV-JOINT", "item": "DRV-JOINT", "rev": "示例 A", "date": DATE,
        "disclaimer": "示例设计，未经硬件验证，不能直接投产",
        "tool": "KiCad 7.0.11 + Freerouting 1.9.0（自动布线）", "board_mm": list(D.BOARD_MM), "layers": D.LAYERS,
        "sheets": [{"key": k, "name": n, "name_en": e, "svg": sheet_files.get(k), "note": SHEET_NOTES[k]} for k, n, e in D.SHEETS],
        "root_svg": next((s for s in sheets if s == NAME + ".svg"), sheets[0] if sheets else None),
        "pcb_layers": [{"key": k, "name": n, "svg": k + ".svg"} for k, _, n in LAYERS_SVG],
        "parts": [{"ref": p["ref"], "value": p["value"], "fp": p["fp"], "sheet": p["sheet"], "item": p["item"], "note": p["note"],
                   "lib": p["lib"], "xy": list(D.PLACEMENT[p["ref"]][:2]), "side": D.PLACEMENT[p["ref"]][3]} for p in D.PARTS],
        "nets": len([n for n in D.nets() if n not in D.NC_NETS]),
        "bom_by_item": D.bom_by_item(),
        "stats": {"parts": len(D.PARTS), "tracks": len(tracks), "vias": len(vias),
                  "track_mm": round(sum(pcbnew.ToMM(t.GetLength()) for t in tracks), 1)},
        "values": {"rs_mohm": D.RS_MOHM, "gain": D.GAIN, "rg_ohm": D.RG_OHM, "vdrv": D.VDRV, "c_bus_uf": D.C_BUS_UF,
                   "enc_r_ohm": D.ENC_R_OHM, "enc_c_pf": D.ENC_C_PF},
        "drc": {k: drc_res[k] for k in ("errors", "warnings", "unconnected")},
        "dfm": {"pass": dfm_res["pass"], "n": len(dfm_res["checks"])},
        "files": {}
    }
    if getattr(D, "REV", "A") == "B":          # 第 98 轮：B 版带“A→B 改了什么”（A 版的 design.json 不变）
        import drv_joint as A
        a_items, b_items = A.bom_by_item(), D.bom_by_item()
        mcu_a = next(p for p in A.PARTS if p["ref"] == "U10")["pins"]
        mcu_b = next(p for p in D.PARTS if p["ref"] == "U10")["pins"]
        d["rev"] = "示例 B（设计对照）"
        d["changes"] = [{"ref": r, "what": w} for r, w in D.B_CHANGES]
        d["bom_delta"] = {k: b_items.get(k, 0) - a_items.get(k, 0) for k in sorted(set(a_items) | set(b_items)) if b_items.get(k, 0) != a_items.get(k, 0)}
        d["mcu_pins"] = [{"pin": k, "a": mcu_a.get(k), "b": mcu_b.get(k)} for k in sorted(set(mcu_a) | set(mcu_b), key=int) if mcu_a.get(k) != mcu_b.get(k)]
        d["nets_added"] = sorted(set(D.nets()) - set(A.nets()))
        d["firmware"] = ["SPI1：PA4 NSS / PA5 SCK / PA6 MISO / PA7 MOSI（AF5），模式 0，≤ 5 MHz（芯片要求 SCLK ≤ 时钟 / 10）",
                         "SSI：PB3 / PB4 改用 SPI3（AF6），引脚不变", "PB1 推挽输出，接芯片复位（低有效）；TIM3 编码器模式不再用",
                         "上电：拉低复位 ≥ 4 个芯片时钟后放开，读 ID（地址 0x00）应为 0x454E4331，再写 CTRL 设滤波长度",
                         "抱闸（第 110 轮）：PB6 = TIM4_CH1（AF2）PWM 20 kHz；松闸先 100% 50 ms，再保持占空比 = 24 V ÷ 母线电压；不输出 = 抱住"]
        d["disclaimer"] = "B 版：设计对照，不投产；编码器接口芯片 WQ-ENCIF 未流片。示例设计，未经硬件验证"
    for root, _, fs in os.walk(OUT):
        for fn in sorted(fs):
            if fn == "design.json" or fn.endswith((".glb", ".step")):    # 三维随 OpenCASCADE 版本略有不同，不记摘要
                continue
            p = os.path.join(root, fn)
            with open(p, "rb") as f:
                d["files"][os.path.relpath(p, OUT)] = hashlib.sha256(f.read()).hexdigest()[:16]
    with open(os.path.join(OUT, "design.json"), "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write("\n")
    return d


def use_rev_b():
    """第 98 轮：B 版——同一套流程，换设计描述（drv_joint_b：A 版打补丁）、工程名和产物目录；A 版的东西一律不碰"""
    global D, PROJ, KDIR, OUT, NAME
    import drv_joint_b
    D = drv_joint_b
    NAME = "drv-joint-b"
    PROJ = os.path.join(ROOT, NAME)
    KDIR = os.path.join(PROJ, "kicad")
    OUT = os.path.join(PROJ, "out")
    CLASSES["Supply"][2].append("+1V8")
    SHEET_NOTES["mcu"] = ("STM32G431（示例选型）：TIM1 三相互补 PWM、ADC 采三相电流与母线电压、SPI1 读编码器接口芯片 U14（模式 0，≤ 5 MHz）、"
                          "SPI3 读 SSI、TIM4_CH1（PB6）抱闸 PWM、FDCAN1；8 MHz 晶振；TP1–TP5 是烧录口和电源测试点。B 版：设计对照，不投产。")
    SHEET_NOTES["power"] = ("48 V 从 J1 进；C1 母线电容；R1–R3 分压测母线电压。B 版加抱闸（第 110 轮）：J6 接抱闸线圈，U16 + Q7 从母线 PWM 供电，"
                            "D5 续流，R38 下拉（MCU 没输出就抱住）。示例设计，未经硬件验证。")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-route", action="store_true", help="不重新布线，沿用已有 PCB")
    ap.add_argument("--rev", default="A", choices=["A", "B"], help="A 版（投产）或 B 版（第 98 轮：放上 WQ-ENCIF，设计对照）")
    a = ap.parse_args()
    if a.rev == "B":
        use_rev_b()
    import dfm
    schematic()
    stats = None
    if not a.no_route:
        jar = os.environ.get("FREEROUTING_JAR") or os.path.join(HERE, "freerouting-1.9.0.jar")
        stats = pcb_build(jar)
        # 导出和检查换一个新进程做：KiCad 的工程设置在同一进程里会沿用布线前读到的旧值
        return subprocess.call([sys.executable, os.path.abspath(__file__), "--no-route", "--rev", a.rev])
    _project_settings()
    net = exports()
    dr = drc()
    with open(os.path.join(OUT, "drc.json"), "w", encoding="utf-8") as f:
        json.dump(dr, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write("\n")
    df = dfm.check(os.path.join(KDIR, NAME + ".kicad_pcb"), D)
    with open(os.path.join(OUT, "dfm.json"), "w", encoding="utf-8") as f:
        json.dump(df, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write("\n")
    s = summary(dr, df, stats, net)
    print("原理图 {} 页、器件 {}、网络 {}；布线 {} 段、过孔 {}；DRC 错误 {}、未连接 {}；DFM {}".format(
        len(D.SHEETS), s["stats"]["parts"], s["nets"], s["stats"]["tracks"], s["stats"]["vias"], dr["errors"], dr["unconnected"],
        "通过" if df["pass"] else "未通过"))
    return 0 if dr["errors"] == 0 and df["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
