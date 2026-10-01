"""单个连接的校验（M4a #66 find_compatible 用）。纯函数。

两个组件、各一个端口：先判 C1（类型、方向、运动方式），通过后按端口类型做该连接本身的判定：
圆柱（C2）、法兰（C3）、电机动力（C9 中电压等级与电流）、编码器（C10 中协议）、总线（协议有交集）。
需求相关的判定（供电、扭矩、转速等）不在这里做，要放进系统里用 verify_system。
"""

from __future__ import annotations

from engine.checks_electrical import c9_link, c10_encoder_link
from engine.checks_interface import _pair_ok, c2_link, c3_link
from engine.result import FAIL, NA, PASS, Finding, worst
from engine.system import PortRef, load_system
from engine.values import items


def check_link(comp_a: dict, port_a: str, comp_b: dict, port_b: str) -> dict:
    """返回 {"status", "findings": [...]}；状态取最严重的（fail > unknown > warn > pass）。"""
    comps = {"a": comp_a, "b": comp_b}
    system = load_system(
        {"id": "link", "requirement": {"output_torque_cont_nm": 1, "output_speed_rpm": 1},
         "components": [{"instance": "a", "component": "a"}, {"instance": "b", "component": "b"}],
         "connections": [{"a": f"a.{port_a}", "b": f"b.{port_b}"}]},
        comps.get,
    )
    a, b = PortRef("a", port_a), PortRef("b", port_b)
    pa, pb = system.port(a), system.port(b)
    ok, msg = _pair_ok(pa, pb)
    findings = [Finding(PASS if ok else FAIL, f"C1：{msg}", [str(a), str(b)])]
    if ok:
        t = pa["type"]
        if t.startswith("mechanical.cyl_"):
            findings += c2_link(system, a, b)
        elif t == "mechanical.flange":
            findings += c3_link(system, a, b)
        elif t == "electrical.motor_power":
            out, pin = (a, b) if pa["dir"] == "out" else (b, a)
            findings += c9_link(system, out, pin)
        elif t == "signal.encoder":
            enc, ein = (a, b) if pa["dir"] == "out" else (b, a)
            findings += c10_encoder_link(system, enc, ein)
        elif t == "signal.fieldbus":
            xa, xb = items(pa["spec"].get("protocol")) or [], items(pb["spec"].get("protocol")) or []
            common = sorted(set(xa) & set(xb))
            findings.append(Finding(PASS if common else FAIL,
                                    f"总线协议交集：{common}" if common else f"总线协议没有交集：{xa} 与 {xb}",
                                    [str(a), str(b)]))
        else:
            findings.append(Finding(NA, f"{t} 的连接只判类型与方向，其余在系统校验或布局中处理", [str(a), str(b)]))
    out = []
    for f in findings:
        d = f.to_dict()
        d["ports"] = [p.replace("a.", f"{comp_a['id']}:", 1).replace("b.", f"{comp_b['id']}:", 1)
                      for p in d.get("ports", [])]
        out.append(d)
    status = worst(f.status for f in findings)
    return {"status": PASS if status == NA else status, "findings": out}
