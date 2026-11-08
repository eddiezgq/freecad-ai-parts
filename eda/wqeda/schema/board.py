# -*- coding: utf-8 -*-
"""板子层（L4）新加的字段（第 111 轮 P4）：网络分类、叠层、设计规则、热分析条件、布局约束。只做格式校验，不判对错。

    net_classes  [{name, track_mm, clearance_mm, nets, layers?}]   布线器的线宽 / 间距类别
    stackup      {thickness_mm, outer_oz, inner_oz, source}        板厚、铜厚（大电流线宽、热分析用）
    rules        {trace_dt_c, ict_coverage_min, source}            设计规则：允许的走线温升、ICT 覆盖率要求
    thermal      {ambient_c, h_w_m2k, f_pwm_hz, source, heat:[...]}
                 热分析：环境温度、对流换热系数（假设）、开关频率、哪些器件发热
    constraints  [{key, kind, ...}]                                布局约束，五种：loop、kelvin、near、apart、edge

每个数都要有出处（source），没有出处写“示例值”；不编数。"""

from __future__ import annotations

KINDS = {
    "loop": ("功率回路", ("refs", "nets", "max_area_mm2")),
    "kelvin": ("开尔文采样", ("ref", "ties")),
    "near": ("靠近", ("ref", "to", "pin", "max_mm")),
    "apart": ("远离", ("hot", "cold", "min_mm")),
    "edge": ("接插件在板边", ("refs", "max_mm")),
}
HEAT_MODELS = ("mosfet", "shunt")


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _pos(v):
    return _num(v) and v > 0


def validate(bd, refs):
    """bd = 设计描述里的 board；refs = 全部位号。返回问题清单。"""
    p = []
    for c in bd.get("net_classes") or []:
        if not isinstance(c.get("name"), str) or not c.get("name"):
            p.append("网络分类缺 name")
        if not (_pos(c.get("track_mm")) and _pos(c.get("clearance_mm"))):
            p.append("网络分类 {} 的 track_mm、clearance_mm 应是正数".format(c.get("name")))
        if not isinstance(c.get("nets"), list) or not c["nets"]:
            p.append("网络分类 {} 应列出 nets".format(c.get("name")))
        if c.get("layers") is not None and not isinstance(c["layers"], list):
            p.append("网络分类 {} 的 layers 应是列表".format(c.get("name")))
    st = bd.get("stackup")
    if st is not None:
        for k in ("thickness_mm", "outer_oz", "inner_oz"):
            if not _pos(st.get(k)):
                p.append("stackup.{} 应是正数".format(k))
        if not st.get("source"):
            p.append("stackup 要写 source（出处，没有写“示例值”）")
    ru = bd.get("rules")
    if ru is not None:
        if ru.get("trace_dt_c") is not None and not _pos(ru["trace_dt_c"]):
            p.append("rules.trace_dt_c 应是正数")
        v = ru.get("ict_coverage_min")
        if v is not None and not (_num(v) and 0 < v <= 1):
            p.append("rules.ict_coverage_min 应在 0 到 1 之间")
        if not ru.get("source"):
            p.append("rules 要写 source")
    th = bd.get("thermal")
    if th is not None:
        for k in ("ambient_c", "h_w_m2k"):
            if not _num(th.get(k)):
                p.append("thermal.{} 应是数".format(k))
        if not th.get("source"):
            p.append("thermal 要写 source（环境温度、换热系数是假设就写假设）")
        for h in th.get("heat") or []:
            if h.get("model") not in HEAT_MODELS:
                p.append("thermal.heat 的 model 应是 {} 之一".format("、".join(HEAT_MODELS)))
            if not h.get("refs") or any(r not in refs for r in h["refs"]):
                p.append("thermal.heat 的位号要在器件清单里：{}".format(h.get("refs")))
    keys = []
    for c in bd.get("constraints") or []:
        kind = c.get("kind")
        keys.append(c.get("key"))
        if kind not in KINDS:
            p.append("布局约束 {} 的 kind 应是 {} 之一".format(c.get("key"), "、".join(KINDS)))
            continue
        for need in KINDS[kind][1]:
            if c.get(need) in (None, "", []):
                p.append("布局约束 {}（{}）缺 {}".format(c.get("key"), KINDS[kind][0], need))
        for k in ("refs", "hot", "cold", "ties"):
            for r in c.get(k) or []:
                if r not in refs:
                    p.append("布局约束 {} 的位号 {} 不在器件清单里".format(c.get("key"), r))
        for k in ("ref", "to"):
            if c.get(k) and c[k] not in refs:
                p.append("布局约束 {} 的位号 {} 不在器件清单里".format(c.get("key"), c[k]))
        if not c.get("source"):
            p.append("布局约束 {} 要写 source（出处，没有写“示例值”）".format(c.get("key")))
    if len(set(keys)) != len(keys):
        p.append("布局约束 key 重复")
    return p
