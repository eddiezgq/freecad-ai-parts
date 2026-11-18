"""积分器建议（ADR-0098 E3）：看模型里有什么，建议用 DOP853 还是 HHT、容差多少。纯规则，不算东西。

规则（依据 ADR-0098 补充一、二的实测）：
- 有柔性构件或梁元件：硬系统，用 HHT。有梁元件时 rtol 1e-7（梁的刚度比例阻尼对速度误差敏感，rtol 1e-5 时力矩差 14%）；
  只有柔性构件时 rtol 1e-6。
- 没有上面这些：用 DOP853（显式高阶，冲击接触、阶跃设定值、输出限幅都处理得好）。
- 有接触、执行器限幅这类不光滑的输入，又必须用 HHT 时：rtol 收紧到 1e-8（补充一：接触样例 rtol 1e-8 时与 DOP853 差 2e-4）。
只用于动力学（dynamic、static_then_dynamic）；其他分析不用积分器。
"""

from __future__ import annotations

DYNAMIC = ("dynamic", "static_then_dynamic")


def suggest(model: dict) -> dict:
    """返回 {"integrator", "rtol", "atol", "reason"}；不是动力学分析时返回 {}"""
    an = model.get("analysis") or {}
    if an.get("type") not in DYNAMIC:
        return {}
    flex = [b["id"] for b in model.get("bodies", []) if b.get("flex") and b["flex"].get("type") != "nonlinear_beam"]
    beams = [f["id"] for f in model.get("forces", []) if f.get("type") == "beam"]
    beams += [b["id"] for b in model.get("bodies", []) if (b.get("flex") or {}).get("type") == "nonlinear_beam"]   # ADR-0101
    rough = []
    if model.get("contacts"):
        rough.append("接触")
    for c in model.get("controllers") or []:
        if "output_min" in c or "output_max" in c:
            rough.append("控制器输出限幅")
            break
    if not flex and not beams:
        return {"integrator": "DOP853", "rtol": 1e-8, "atol": 1e-10,
                "reason": "没有柔性构件和梁元件，系统不硬，用显式积分（精度高，冲击、限幅都处理得好）"}
    why = []
    if flex:
        why.append(f"柔性构件 {'、'.join(flex[:3])}{' 等' if len(flex) > 3 else ''}")
    if beams:
        why.append(f"{len(beams)} 个梁元件或大变形梁")
    rtol = 1e-7 if beams else 1e-6
    if rough:
        rtol = 1e-8
    reason = f"有{'和'.join(why)}，系统硬，显式积分步长会被压得很小，用 HHT 隐式积分"
    if beams:
        reason += "；梁元件的刚度比例阻尼对速度误差敏感，容差收紧"
    if rough:
        reason += f"；有{'、'.join(rough)}（不光滑），容差再收紧到 1e-8"
    return {"integrator": "HHT", "rtol": rtol, "atol": rtol * 1e-2, "reason": reason}


def apply(model: dict) -> str | None:
    """模型没写积分器时按建议填上（原地改），返回理由；写了就不动，返回 None"""
    an = model.get("analysis") or {}
    if an.get("integrator"):
        return None
    s = suggest(model)
    if not s:
        return None
    an["integrator"] = s["integrator"]
    an.setdefault("rtol", s["rtol"])
    an.setdefault("atol", s["atol"])
    return s["reason"]
