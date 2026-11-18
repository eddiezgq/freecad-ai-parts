"""问渠多体动力学的免费 / 专业两档（ADR-0102 决策 3；第 4 步）。

- 版本（edition）同问渠有限元（`assist/fea_edition.py`）：安装时写在工作台包里的 `edition.json`，`mbd` 是单独安装的问渠多体动力学版；
  全功能版（零件库安装包、仓库开发）不分档，与以前一样。
- 问渠多体动力学版分两档。免费：刚体（最多 15 个构件）、六种运动副与驱动、弹簧阻尼 / 扭簧 / 衬套 / 恒力与函数力、
  运动学 / 静平衡 / 动力学（DOP853），曲线、动画、核查结论。
  专业（授权文件里有功能 `mbd_pro`）：构件数不限、AI 帮着挑运动副、柔性体、接触 / 齿轮啮合 / 摩擦 / 间隙、梁元件、控制器与执行器、
  HHT 隐式积分、线性化与模态、正式报告。参数研究、优化、疲劳交接现在只有模型文件的用法（窗口里没有入口），加进窗口时算专业版。
- 授权按 ADR-0066 的签名授权文件离线校验；一个授权文件可以同时开 `fea_pro` 与 `mbd_pro`（套装）。
  授权只决定能不能用专业版功能，不改变任何计算结果与核查结论。
"""

from __future__ import annotations

from assist import fea_edition

PRO = "mbd_pro"
FREE_MAX_BODIES = 15
FREE_ANALYSES = ("kinematic", "dynamic", "static", "static_then_dynamic")
FREE_FORCES = ("force", "torque", "spring_damper", "rotational_spring_damper", "bushing")
FORCE_NAMES = {"beam": "梁元件", "gear_mesh": "齿轮啮合", "actuator": "执行器"}


class NeedsPro(Exception):
    """免费版不能用的功能；消息里写明是哪些、怎么开放"""


def edition() -> str:
    return fea_edition.edition()


def pro_allowed() -> bool:
    """全功能版不分档；问渠多体动力学版看授权文件里有没有 mbd_pro"""
    if edition() != "mbd":
        return True
    from licensing import runtime

    return runtime.allows(PRO)


def pro_needs(model: dict, flex_parts: dict | None = None) -> list[str]:
    """这个模型（mbd-model/1）用到的专业版功能（中文，界面显示时翻译）；flex_parts 是窗口里选了按柔性体算的零件"""
    out: list[str] = []
    bodies = model.get("bodies") or []
    if len(bodies) > FREE_MAX_BODIES:
        out.append("超过 15 个构件")
    if flex_parts or any(b.get("flex") for b in bodies):
        out.append("柔性体")
    joints = model.get("joints") or []
    if any(j.get("friction") for j in joints):
        out.append("摩擦")
    if any(j.get("clearance") for j in joints):
        out.append("间隙")
    if model.get("contacts") or model.get("geometries"):
        out.append("接触")
    for f in model.get("forces") or []:
        t = f.get("type")
        if t not in FREE_FORCES:
            out.append(FORCE_NAMES.get(t, str(t)))
    if model.get("controllers"):
        out.append("控制器")
    an = model.get("analysis") or {}
    if an.get("type", "dynamic") not in FREE_ANALYSES:
        out.append("线性化与模态")
    if an.get("integrator") == "HHT":
        out.append("HHT 隐式积分")
    return list(dict.fromkeys(out))


def gate(model: dict | None = None, *, feature: str | None = None, flex_parts: dict | None = None) -> None:
    """免费版用了专业版功能就拒绝：model 给模型（看用到哪些），feature 给按钮名（AI 帮着挑运动副、正式报告……）"""
    if pro_allowed():
        return
    needs = ([feature] if feature else []) + (pro_needs(model, flex_parts) if model is not None else [])
    if needs:
        raise NeedsPro("这是问渠多体动力学专业版的功能：{}。免费版可以算最多 15 个刚性构件的运动学、静平衡和动力学（弹簧、衬套、恒力与函数力）；"
                       "要用专业版，请在“问渠多体动力学”菜单的“授权…”里导入授权文件".format("、".join(needs)))
