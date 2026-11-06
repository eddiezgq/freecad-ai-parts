# -*- coding: utf-8 -*-
"""设计描述（问渠电子，第 102 轮 P1）：一块板子的四层描述，存成 YAML 文本文件，KiCad 文件由它生成。

    L1 spec      规格：这块板要干什么（电压、电流、层数、外形、目标工厂、验收等级）；没定的字段写 null，显示“未定”
    L2 blocks    功能块：板子由哪些块组成；本版每块带名称、参数（示例值）和算式说明，计算器在 P2 做
    L3 circuit   电路：器件、引脚接哪个网络、物料编号；网络分类；按规则生成的 ICT 测试点
    L4 board     板子：外形、层数、摆放、安装孔、测试点网格、大电流焊盘路径、功率铺铜

变体（variant）：在一份设计描述上打补丁（改引脚、改说明、加器件、加摆放），改了什么自动记成改动清单。
本模块只做读、校验和确定性展开：不联网、不调 AI。"""
from __future__ import annotations

import copy
import os

import yaml

DESIGN_FORMAT = "wqeda.design/1"
VARIANT_FORMAT = "wqeda.variant/1"
SIDES = ("F", "B")
PART_KEYS = ("ref", "lib", "value", "fp", "block", "pins", "item", "note")


class DesignError(ValueError):
    """设计描述不合格式：带全部问题的清单"""

    def __init__(self, problems):
        self.problems = list(problems)
        super().__init__("; ".join(self.problems))


def read_yaml(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ------------------------------------------------------------------------------------------------- 校验


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _check_xy(v):
    return isinstance(v, list) and len(v) == 2 and all(_is_num(x) for x in v)


def validate_design(doc):
    """返回问题清单（空 = 合格）。只看结构和引用是否对得上，不判电气上对不对（那是检查引擎的事）。"""
    p = []
    if not isinstance(doc, dict):
        return ["设计描述应是一个映射（mapping）"]
    if doc.get("format") != DESIGN_FORMAT:
        p.append("format 应为 {}".format(DESIGN_FORMAT))
    for key in ("name", "spec", "blocks", "circuit", "board"):
        if key not in doc:
            p.append("缺 {}".format(key))
    if p:
        return p
    blocks = doc["blocks"]
    if not isinstance(blocks, list) or not blocks:
        return p + ["blocks 应是非空列表"]
    keys = [b.get("key") for b in blocks]
    if len(set(keys)) != len(keys):
        p.append("功能块 key 重复")
    for b in blocks:
        for k in ("key", "name", "name_en"):
            if not isinstance(b.get(k), str) or not b.get(k):
                p.append("功能块缺 {}：{}".format(k, b.get("key")))
        for name, v in (b.get("params") or {}).items():
            if not _is_num(v):
                p.append("功能块 {} 的参数 {} 不是数".format(b.get("key"), name))
    c = doc["circuit"]
    parts = c.get("parts") or []
    refs = [q.get("ref") for q in parts]
    dup = sorted({r for r in refs if refs.count(r) > 1})
    if dup:
        p.append("位号重复：{}".format(", ".join(map(str, dup))))
    for q in parts:
        p += _check_part(q, set(keys))
    nets = c.get("nets") or {}
    for name in ("nc", "power"):
        if not isinstance(nets.get(name, []), list):
            p.append("circuit.nets.{} 应是列表".format(name))
    for net, amps in (nets.get("high_current") or {}).items():
        if not _is_num(amps) or amps <= 0:
            p.append("大电流网络 {} 的电流应是正数".format(net))
    ict = c.get("ict_test_points")
    if ict is not None:
        for k in ("ref_start", "lib", "fp", "block", "power_block", "note"):
            if k not in ict:
                p.append("ict_test_points 缺 {}".format(k))
    bd = doc["board"]
    if not _check_xy(bd.get("outline_mm")):
        p.append("board.outline_mm 应是 [宽, 高]")
    if not isinstance(bd.get("layers"), int) or bd.get("layers") < 1:
        p.append("board.layers 应是正整数")
    place = bd.get("placement") or {}
    known = set(refs)
    for ref, v in place.items():
        if ref not in known:
            p.append("摆放里的 {} 不在器件清单里".format(ref))
        if not (isinstance(v, list) and len(v) == 4 and all(_is_num(x) for x in v[:3]) and v[3] in SIDES):
            p.append("摆放 {} 应是 [x, y, 角度, F/B]".format(ref))
    for h in bd.get("holes") or []:
        if not _check_xy(h):
            p.append("安装孔应是 [x, y]")
    for pour in bd.get("pours") or []:
        if not (isinstance(pour.get("net"), str) and isinstance(pour.get("layer"), str)
                and isinstance(pour.get("points"), list) and len(pour["points"]) >= 3
                and all(_check_xy(xy) for xy in pour["points"])):
            p.append("铺铜 {} 应有 net、layer 和至少三个 [x, y] 顶点".format(pour.get("net")))
    for net, pads in (bd.get("power_pads") or {}).items():
        for pad in pads:
            if not (isinstance(pad, list) and len(pad) == 2 and pad[0] in known and isinstance(pad[1], str)):
                p.append("大电流焊盘 {} 应是 [位号, 引脚]，位号要在器件清单里".format(net))
    return p


def _check_part(q, blocks):
    p = []
    ref = q.get("ref")
    if not isinstance(ref, str) or not ref:
        return ["器件缺位号"]
    for k in ("lib", "value", "fp"):
        if not isinstance(q.get(k), str) or not q.get(k):
            p.append("{} 缺 {}".format(ref, k))
    if q.get("block") not in blocks:
        p.append("{} 的功能块 {} 不在 blocks 里".format(ref, q.get("block")))
    pins = q.get("pins")
    if not isinstance(pins, dict) or not pins:
        p.append("{} 没有引脚".format(ref))
    else:
        for pin, net in pins.items():
            if not isinstance(pin, str) or not isinstance(net, str) or not net:
                p.append("{} 的引脚 {} 应是 '引脚号': 网络名（都是文字）".format(ref, pin))
    for k in set(q) - set(PART_KEYS):
        p.append("{} 有不认识的字段 {}".format(ref, k))
    return p


def validate_variant(doc, base):
    p = []
    if not isinstance(doc, dict) or doc.get("format") != VARIANT_FORMAT:
        return ["format 应为 {}".format(VARIANT_FORMAT)]
    if not isinstance(doc.get("rev"), str):
        p.append("变体缺 rev")
    refs = {q["ref"] for q in base["circuit"]["parts"]}
    new = [q.get("ref") for q in doc.get("add_parts") or []]
    blocks = {b["key"] for b in base["blocks"]}
    for ref in doc.get("pin_changes") or {}:
        if ref not in refs:
            p.append("改引脚的 {} 不在原设计里".format(ref))
    for ref in doc.get("note_changes") or {}:
        if ref not in refs:
            p.append("改说明的 {} 不在原设计里".format(ref))
    for ref in new:
        if ref in refs:
            p.append("新增的 {} 与原设计位号重复".format(ref))
    for q in doc.get("add_parts") or []:
        p += _check_part(q, blocks)
    for ref in doc.get("add_placement") or {}:
        if ref not in refs and ref not in new:
            p.append("新增摆放的 {} 不在器件清单里".format(ref))
    return p


# ------------------------------------------------------------------------------------------------- 读


def load_design(path):
    doc = read_yaml(path)
    probs = validate_design(doc)
    if probs:
        raise DesignError(probs)
    return doc


def load_variant(path):
    """读一份变体，连同它的底稿（base 写相对变体文件的路径），返回 (底稿, 变体)"""
    var = read_yaml(path)
    if not isinstance(var, dict) or not isinstance(var.get("base"), str):
        raise DesignError(["变体缺 base（底稿设计描述的路径）"])
    base = load_design(os.path.join(os.path.dirname(os.path.abspath(path)), var["base"]))
    probs = validate_variant(var, base)
    if probs:
        raise DesignError(probs)
    return base, var


# ------------------------------------------------------------------------------------------------- 展开


def apply_variant(doc, var):
    """在底稿上打补丁，返回 (新设计描述, 改动清单 [(位号, 改了什么)])；底稿不动"""
    out = copy.deepcopy(doc)
    parts = out["circuit"]["parts"]
    by_ref = {q["ref"]: q for q in parts}
    changes = []
    if var.get("title"):
        out["title"] = var["title"]
    for ref, edits in (var.get("pin_changes") or {}).items():
        pins = by_ref[ref]["pins"]
        for e in edits:
            pin, new = str(e["pin"]), e.get("net")
            old = pins.get(pin)
            if new is None:
                pins.pop(pin, None)
            else:
                pins[pin] = new
            changes.append((ref, "引脚 {}：{} → {}".format(pin, old or "未用", new or "未用")))
    for ref, note in (var.get("note_changes") or {}).items():
        by_ref[ref]["note"] = note
    for q in var.get("add_parts") or []:
        parts.append(copy.deepcopy(q))
        changes.append((q["ref"], "新增：" + q.get("note", "")))
    out["board"].setdefault("placement", {}).update(copy.deepcopy(var.get("add_placement") or {}))
    return out, changes


def ict_nets(parts, rule):
    """要放 ICT 测试点的网络：所有网络 − 接插件（J*，有通孔焊盘可扎）的网络 − 已有测试点的网络 − 规则里排除的"""
    tht = {n for q in parts if q["ref"].startswith("J") for n in q["pins"].values()}
    has_tp = {q["pins"]["1"] for q in parts if q["ref"].startswith("TP")}
    every = {n for q in parts for n in q["pins"].values()}
    return sorted(every - tht - has_tp - set(rule.get("exclude_nets") or []))


def test_point_parts(parts, rule):
    """按规则生成 ICT 测试点器件：每个要测的网络一个，位号从 ref_start 起"""
    power = set(rule.get("power_block_nets") or [])
    out = []
    for k, net in enumerate(ict_nets(parts, rule)):
        out.append({"ref": "TP{}".format(rule["ref_start"] + k), "lib": rule["lib"], "value": net, "fp": rule["fp"],
                    "block": rule["power_block"] if net in power else rule["block"], "pins": {"1": net}, "item": None,
                    "note": rule["note"]})
    return out


def test_point_spots(grid):
    """测试点网格：每一行 [x0, dx, y, 个数]，x 保留两位小数"""
    spots = []
    for x0, dx, y, n in grid["rows"]:
        spots += [(round(x0 + dx * i, 2), y) for i in range(n)]
    return spots


def expand(doc, var=None):
    """设计描述 → 生成程序要的平铺数据（器件清单、摆放、网络分类、铺铜……）。确定性：同一份描述每次展开结果一样。"""
    changes = []
    if var is not None:
        doc, changes = apply_variant(doc, var)
    c, bd = doc["circuit"], doc["board"]
    parts = copy.deepcopy(c["parts"])
    rule = c.get("ict_test_points")
    ict = ict_nets(parts, rule) if rule else []
    tps = test_point_parts(parts, rule) if rule else []
    parts += tps
    placement = {ref: tuple(v) for ref, v in (bd.get("placement") or {}).items()}
    grid = bd.get("test_point_grid")
    if grid:
        refs = list(grid.get("first") or []) + [q["ref"] for q in tps]
        spots = test_point_spots(grid)
        if len(refs) > len(spots):
            raise DesignError(["测试点 {} 个，网格只有 {} 个位置".format(len(refs), len(spots))])
        for ref, (x, y) in zip(refs, spots[:len(refs)], strict=True):
            placement[ref] = (x, y, 0, grid.get("side", "B"))
    params = {}
    for b in doc["blocks"]:
        params.update(b.get("params") or {})
    nets = c.get("nets") or {}
    return {
        "name": doc["name"],
        "rev": var["rev"] if var is not None else doc.get("rev", "A"),
        "title": doc.get("title"),
        "params": params,
        "sheets": [(b["key"], b["name"], b["name_en"]) for b in doc["blocks"]],
        "footprints": dict(c.get("footprints") or {}),
        "parts": parts,
        "changes": changes,
        "ict_nets": ict,
        "nc_nets": set(nets.get("nc") or []),
        "power_nets": set(nets.get("power") or []),
        "high_current": dict(nets.get("high_current") or {}),
        "back_end_items": set(c.get("back_end_items") or []),
        "board_mm": tuple(bd["outline_mm"]),
        "layers": bd["layers"],
        "placement": placement,
        "holes": [tuple(h) for h in bd.get("holes") or []],
        "power_pads": {net: [tuple(x) for x in pads] for net, pads in (bd.get("power_pads") or {}).items()},
        "pours": [(q["net"], q["layer"], [tuple(xy) for xy in q["points"]]) for q in bd.get("pours") or []],
    }
