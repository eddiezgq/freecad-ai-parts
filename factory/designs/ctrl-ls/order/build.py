# -*- coding: utf-8 -*-
"""第 159 轮 159h：平缝机控制器 CTRL-LS 打样下单文件包（由仓库里的产物生成，可重复，CI 逐字核对）。

    python3 build.py        # 写 order/ 下的物料清单、坐标、定制件清单、磁性件绕制规格单、下单说明，打包 ctrl-ls-order.zip

来源（都是仓库里已有的，不另编数）：
- out/bom.csv、out/pos.csv、out/gerber.zip、kicad/ctrl-ls.kicad_pcb（判贴片 / 插件）、parts.yaml（型号、厂家、立创编号）
- 计算书（wqeda.calcbook，不跑仿真）：磁性件的匝数、气隙、电感量、线截面
手写的两份（核对表.md、板厂工艺核对.md）原样打进包里。示例设计，未经硬件验证，打样是为了验证设计。"""
from __future__ import annotations

import csv
import io
import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(PROJ)))
sys.path.insert(0, os.path.join(ROOT, "eda"))

import yaml  # noqa: E402

from wqeda import calcbook  # noqa: E402

ZIP = "ctrl-ls-order.zip"
STAMP = (2026, 11, 16, 0, 0, 0)
HAND = ["核对表.md", "板厂工艺核对.md"]


def _read_csv(path):
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _write_csv(name, head, rows):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(head)
    w.writerows(rows)
    with open(os.path.join(HERE, name), "w", encoding="utf-8") as f:
        f.write(buf.getvalue())
    return name


def _mount_types():
    """位号 → 'THT'（有通孔焊盘）/ 'SMD'，从 KiCad 板子文件读"""
    with open(os.path.join(PROJ, "kicad", "ctrl-ls.kicad_pcb"), encoding="utf-8") as f:
        txt = f.read()
    out = {}
    for blk in re.split(r'\n  \(footprint "', txt)[1:]:
        m = re.search(r'\(property "Reference" "([^"]+)"|\(fp_text reference "([^"]+)"', blk)
        if not m:
            continue
        ref = m.group(1) or m.group(2)
        out[ref] = "THT" if re.search(r'\(pad "[^"]*" thru_hole', blk) else "SMD"
    return out


def _catalog():
    with open(os.path.join(PROJ, "parts.yaml"), encoding="utf-8") as f:
        return {p["item"]: p for p in yaml.safe_load(f)["parts"] if p.get("item")}


def bom_files():
    """贴片 / 插件物料清单（一行一个物料：位号、型号、封装、立创编号）；定制件、散热器、随装件另列"""
    cat, mt = _catalog(), _mount_types()
    rows = _read_csv(os.path.join(PROJ, "out", "bom.csv"))
    pcba, other = [], []
    for r in rows:
        q = cat.get(r["物料编号"], {})
        refs = r["位号"].split()
        if q.get("custom") or q.get("mount_of"):
            other.append(r)
            continue
        kind = "插件" if any(mt.get(x) == "THT" for x in refs) else "贴片"
        model = r["型号"] or "通用件 {} {}".format(r["数值"], r["封装"])
        lcsc = r["立创编号"] or "（通用件：按数值、封装配料）"
        pcba.append([r["数值"] if not r["型号"] else r["型号"], " ".join(refs), r["封装"], lcsc, kind, model, r["厂家"], r["数量"],
                     r["物料编号"]])
    pcba.sort(key=lambda x: (x[4], x[8], x[1]))
    _write_csv("bom_pcba.csv", ["Comment", "Designator", "Footprint", "LCSC Part #", "贴装", "型号", "厂家", "数量", "物料编号"], pcba)
    cus = []
    for r in other:
        q = cat.get(r["物料编号"], {})
        if q.get("custom"):
            how = "定制：按《磁性件绕制规格单》绕制"
        elif q.get("kind") == "heatsink":
            how = "散热器：{} 贴在它的基板上。{}".format(r["位号"], q.get("note", ""))
        else:
            how = "随装件：装在 {} 上".format(r["位号"])
        cus.append([r["物料编号"], r["位号"], r["型号"] or q.get("role", ""), q.get("maker", ""), q.get("lcsc", ""), r["数量"], how])
    _write_csv("定制件与散热器.csv", ["物料编号", "位号", "型号", "厂家", "立创编号", "每板数量", "说明"], cus)
    return len(pcba), len(cus), sum(1 for x in pcba if x[4] == "插件")


def cpl_file():
    """贴片坐标：原点 = 板子左下角，x 向右、y 向上（mm）；插件件也列出（板厂插件或手焊对位用）"""
    with open(os.path.join(PROJ, "out", "design.json"), encoding="utf-8") as f:
        import json

        d = json.load(f)
    ox, oy = d["origin_mm"]
    w, h = d["board_mm"]
    rows = []
    for r in _read_csv(os.path.join(PROJ, "out", "pos.csv")):
        x = float(r["PosX"]) - ox
        y = h - (-float(r["PosY"]) - oy)
        rows.append([r["Ref"], "{:.2f}".format(x), "{:.2f}".format(y), "Top" if r["Side"] == "top" else "Bottom", "{:g}".format(float(r["Rot"]))])
    _write_csv("cpl.csv", ["Designator", "Mid X", "Mid Y", "Layer", "Rotation"], rows)
    return len(rows)


def _f(x, nd=3):
    return "{:.{}g}".format(x, nd)


def magnetics():
    """升压电感、反激变压器各一页，每个数取自计算书（按理论）"""
    b = calcbook.build(os.path.join(PROJ, "design.yaml"), sim=False)
    u = {x["type"]: {i["key"]: i for i in x["items"]} for x in b["units"]}
    pf, fl = u["pfc_boost"], u["flyback_aux"]
    with open(os.path.join(PROJ, "design.yaml"), encoding="utf-8") as f:
        des = yaml.safe_load(f)
    fly = next(x["params"] for blk in des["blocks"] for x in blk["units"] if x["type"] == "flyback_aux")
    sec = re.search(r"次级：(.+)$", fl["t_np"]["note"]).group(1)
    s = []
    s.append("# 磁性件绕制规格单：平缝机控制器 CTRL-LS（A 版）\n")
    s.append("> 由 `order/build.py` 从计算书生成（第 159 轮 159h）。示例设计，未经硬件验证：打样件，绕好后按本单实测电感量、调气隙。\n"
             "> 每个数都在计算书（`calc/calc.md`）“功率因数校正”“反激辅助电源”两节里；计算书没有的（线径具体规格、胶带层数等）写“绕制厂按……选”，不另编。\n")
    s.append("## 一、升压电感 L201（物料编号 IND-PFC-CUSTOM）\n")
    s.append("| 项 | 要求 | 计算书出处 |\n|---|---|---|")
    s.append("| 磁芯 | TDK（EPCOS）ETD 59/31/22，材料 N87，一对（B66397） | 升压电感：磁芯面积积（{}） |".format(pf["l_ap"]["source"] or "ETD59-N87"))
    s.append("| 骨架 | B66398（卧式，引出两根线：起、末；板上孔距 50.8 mm、孔 2.0 mm，见封装 wq:L_ETD59_Horizontal） | 同上 |")
    s.append("| 匝数 | {} 匝，一个绕组 | 升压电感：匝数 |".format(int(pf["l_n"]["value"])))
    s.append("| 导线 | 截面 ≥ {} mm²，多股绞线（利兹线）；股径、股数由绕制厂按 65 kHz 选 | 升压电感：导线截面（{}） |".format(_f(pf["l_aw"]["value"]), pf["l_aw"]["note"]))
    s.append("| 气隙（总） | 约 {} mm（中柱磨气隙或两边垫片均分；按实测电感量调） | 升压电感：气隙（{}） |".format(_f(pf["l_lg"]["value"]), pf["l_lg"]["note"]))
    s.append("| 电感量 | ≥ {} µH（65 kHz 下工作；出厂按 LCR 表实测记录） | 升压电感（最少） |".format(_f(pf["L"]["value"] * 1e6, 4)))
    s.append("| 峰值电流 | {} A 时不饱和（峰值磁密约 {} T） | 电感峰值电流；升压电感：峰值磁密 |".format(_f(pf["i_l_pk"]["value"]), _f(pf["l_b_pk"]["value"])))
    s.append("| 工作电压 | 绕组对磁芯：母线最高 {} V（过压保护点）；层间、出线套管按此选 | 过压保护动作的母线电压 |".format(_f(pf["v_ovp"]["value"], 4)))
    s.append("| 铜损参考 | 约 {} W（100 ℃，不含高频损耗） | 升压电感：铜损 |\n".format(_f(pf["l_p_cu"]["value"])))
    s.append("## 二、反激变压器 T301（物料编号 XFMR-FLY-CUSTOM）\n")
    s.append("| 项 | 要求 | 计算书出处 |\n|---|---|---|")
    s.append("| 磁芯 | TDK（EPCOS）ETD 29/16/10，材料 N87，一对（B66358） | 反激变压器：磁芯面积积（{}） |".format(fl["t_ap"]["source"] or "ETD29-N87"))
    s.append("| 骨架 | 卧式 B66359A1013T（13 脚，KiCad 官方封装 Transformer_EPCOS_B66359A1013T_Horizontal） | 原理图 T301 |")
    s.append("| 引脚 | 初级 1（接母线）– 3（接开关管漏极）；24 V：8 – 9（9 接地）；15 V：10 – 11（11 接地）；5 V：12 – 13（13 接地） | 原理图 T301 |")
    s.append("| 匝数 | 初级 {} 匝；次级 {} | 反激变压器：初级匝数 |".format(int(fl["t_np"]["value"]), sec))
    s.append("| 匝比 | 初级 : 24 V = {} | 匝比 N_p : N_24V |".format(_f(fl["n"]["value"], 4)))
    s.append("| 电感量（初级） | ≤ {} µH（断续模式要求的最大值；出厂实测记录） | 初级电感（最多） |".format(_f(fl["lp"]["value"] * 1e6, 4)))
    s.append("| 气隙（总） | 约 {} mm（按实测初级电感调） | 反激变压器：气隙（{}） |".format(_f(fl["t_lg"]["value"]), fl["t_lg"]["note"]))
    s.append("| 初级峰值电流 | {} A 时不饱和 | 初级峰值电流 |".format(_f(fl["i_pk"]["value"])))
    s.append("| 漏感 | 越小越好，实测记录（计算书按 {} µH 估钳位） | 漏感（按理论） |".format(_f(fl["llk"]["value"] * 1e6)))
    s.append("| 导线 | 按电流密度 4 A/mm² 选（计算书窗口占用按此算，占 {}） | 反激变压器：窗口占用 |".format(_f(fl["t_fill"]["value"])))
    s.append("| 绕制顺序 | 建议初级分两半夹住次级（三明治）以减小漏感；次级三路共地，**不要求初次级安规绝缘**（整块板以母线负端为地） | 原理图 T301 说明 |")
    s.append("| 工作电压 | 初级最高 {} V（开关管最高漏极电压）；层间胶带按此选 | 开关管最高漏极电压 |".format(_f(fl["v_ds"]["value"], 4)))
    s.append("| 工作频率 | {} kHz | 初级电感（f） |\n".format(_f(fly["f_sw"] / 1000)))
    s.append("## 三、能不能用现成型号代替\n")
    s.append("- 升压电感：451 µH / 12.7 A 峰值的现成 PFC 电感本轮没有查到能直接放进 wq:L_ETD59_Horizontal 封装的型号，打样用定制。\n"
             "- 反激变压器：三路输出（24 V、15 V、5 V）共地、配 TOP266 的现成型号本轮没有查到；打样用定制。"
             "绕制厂有同骨架的现成 TOP 系列变压器时，匝数、电感量满足上表即可代用。\n")
    s.append("## 四、交货与验收\n")
    s.append("- 打样数量：每种 6 只（5 块板 + 1 只备件）。\n- 每只附实测记录：电感量（1 kHz 或 10 kHz，注明）、直流电阻、反激变压器另附漏感。\n"
             "- 外观：引出线长度按封装孔位、浸漆。\n")
    with open(os.path.join(HERE, "磁性件绕制规格单.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(s))
    return "磁性件绕制规格单.md"


def readme(n_pcba, n_cus, n_tht, n_cpl):
    s = f"""# 下单说明：平缝机控制器 CTRL-LS 打样（A 版，5 块）

> 由 `order/build.py` 生成（第 159 轮 159h）。示例设计，未经硬件验证：打样是为了验证设计，不是投产；安规、电磁兼容认证不在这一轮。

## 包里有什么

| 文件 | 给谁 | 内容 |
|---|---|---|
| `gerber.zip` | 板厂 | 光绘与钻孔（与 `out/gerber.zip` 同一份） |
| `bom_pcba.csv` | 贴片厂 | {n_pcba} 行物料：位号、型号、封装、立创编号、贴片 / 插件（插件 {n_tht} 行） |
| `cpl.csv` | 贴片厂 | {n_cpl} 个器件的坐标：原点板子左下角、mm、x 向右 y 向上 |
| `定制件与散热器.csv` | 采购 | 定制磁性件、保险丝夹、散热器（{n_cus} 行） |
| `磁性件绕制规格单.md` | 绕线厂 | 升压电感、反激变压器的磁芯、骨架、匝数、气隙、电感量 |
| `核对表.md` | 设计 | 关键器件引脚与封装逐项对照规格书的记录 |
| `板厂工艺核对.md` | 设计 / 采购 | 板厂公开工艺能力与本板要求的对照，选哪家、选哪些工艺参数 |

## 板子工艺参数（下单时选）

- 4 层 FR-4，板厚 1.6 mm，尺寸 250 × 150 mm，数量 5
- **外层成品铜厚 3 oz、内层 1 oz**（大电流线按 3 oz 设计；嘉立创多层板外层只到 2 oz，见《板厂工艺核对》，光板与贴片在 PCBWay 下）
- 最小线宽 / 线距按光绘（设计规则检查 0 错误），阻焊绿色、字符白色，表面处理有铅喷锡或沉金均可
- 安装孔 4 个（H1 接保护地）

## 贴装

- 贴片件按 `bom_pcba.csv` + `cpl.csv` 由板厂贴；立创编号是参考料号（PCBWay 代购时按型号配，通用阻容按数值、封装配）。
- 插件件（整流桥、升压管、升压二极管、功率模块、大电容、端子、继电器、共模电感、磁性件等）建议回来手焊：
  装在散热器上的四个（BR101、Q201、D201、U401）先装散热器、上螺丝，再焊脚，脚不受力。
- F101 是两个保险丝夹（`定制件与散热器.csv`），焊好后再插保险丝。

## 上电

样板到手后照 `docs/设计/WQ-LS/GC/打样/上电调试步骤书.md` 一步一步来，**不要直接上 220 V**。
"""
    with open(os.path.join(HERE, "README.md"), "w", encoding="utf-8") as f:
        f.write(s)
    return "README.md"


def pack(names):
    with zipfile.ZipFile(os.path.join(HERE, ZIP), "w", zipfile.ZIP_STORED) as z:
        def add(arc, path):
            zi = zipfile.ZipInfo(arc, STAMP)
            zi.external_attr = 0o644 << 16
            with open(path, "rb") as f:
                z.writestr(zi, f.read())
        add("gerber.zip", os.path.join(PROJ, "out", "gerber.zip"))
        for n in names:
            add(n, os.path.join(HERE, n))


def main():
    n_pcba, n_cus, n_tht = bom_files()
    n_cpl = cpl_file()
    mg = magnetics()
    rd = readme(n_pcba, n_cus, n_tht, n_cpl)
    names = [rd, "bom_pcba.csv", "cpl.csv", "定制件与散热器.csv", mg] + [h for h in HAND if os.path.exists(os.path.join(HERE, h))]
    pack(names)
    print("物料 {} 行（插件 {}）、坐标 {} 个、定制件与散热器 {} 行；{} 已写".format(n_pcba, n_tht, n_cpl, n_cus, ZIP))


if __name__ == "__main__":
    main()
