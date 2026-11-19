"""问渠有限元的版本与免费 / 专业两档（ADR-0096 决策 3；第 5 步）。

- 版本（edition）：`full` 是零件库全功能版（含有限元，不分档，与以前一样）；`fea` 是单独安装的问渠有限元版。
  安装时写在工作台包里的 `edition.json`（`python -m freecad_addon.install --standalone --edition fea`）；
  环境变量 FAP_EDITION 可另指定（测试用）。仓库里直接用时没有这个文件，按 `full`。
- 问渠有限元版分两档。免费：单个实体零件的静力、模态、线性屈曲，可信度核查，结果进 FEM 后处理。
  专业（授权文件里有功能 `fea_pro`）：AI 一句话起草与 AI 解释、正式报告（Word / PDF）、多实体（绑定、接触、螺栓）、
  弹塑性、大变形、谐响应、随机振动、瞬态、附加质量、壳、梁、工况组合、超过 20 万单元的大模型。
- 授权按 ADR-0066 的签名授权文件离线校验（2026-11-17 项目负责人定：第一版只靠签名授权，不编译成二进制）。
  授权只决定能不能用专业版功能，不改变任何计算结果与核查结论。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

PRO = "fea_pro"
EDITIONS = ("full", "fea", "mbd", "cam")          # mbd：问渠多体动力学版（ADR-0102 第 4 步，分档见 mbd_edition）；cam：问渠CAM（ADR-0104，cam_edition）
EDITION_FILE = Path(__file__).resolve().parents[1] / "edition.json"
FREE_MAX_ELEMENTS = 200000
FREE_STEPS = ("static", "modal", "buckling")


class NeedsPro(Exception):
    """免费版不能用的功能；消息里写明是哪些、怎么开放"""


def info() -> dict:
    """{"edition": full | fea | mbd, "test_build": bool}"""
    data: dict[str, Any] = {}
    try:
        data = json.loads(EDITION_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    env = (os.environ.get("FAP_EDITION") or "").strip().lower()
    ed = env if env in EDITIONS else str(data.get("edition") or "full")
    return {"edition": ed if ed in EDITIONS else "full", "test_build": bool(data.get("test_build"))}


def edition() -> str:
    return info()["edition"]


def pro_allowed() -> bool:
    """全功能版不分档；问渠有限元版看授权文件里有没有 fea_pro"""
    if edition() != "fea":
        return True
    from licensing import runtime

    return runtime.allows(PRO)


def pro_needs(study: dict) -> list[str]:
    """这个算例用到的专业版功能（中文，界面显示时翻译）"""
    out: list[str] = []
    bodies = study.get("bodies") or []
    if len(bodies) > 1:
        out.append("多个实体")
    for b in bodies:
        if b.get("kind", "solid") != "solid":
            out.append("壳" if b["kind"] == "shell" else "梁")
        if b.get("plasticity"):
            out.append("弹塑性")
    if study.get("connections"):
        out.append("绑定、接触或螺栓")
    for s in study.get("steps") or []:
        if s.get("type") not in FREE_STEPS:
            out.append({"harmonic": "谐响应", "random": "随机振动", "transient": "瞬态"}.get(s.get("type"), str(s.get("type"))))
        if s.get("large_deformation"):
            out.append("大变形")
    if any(ld.get("type") == "mass" for ld in study.get("loads") or []):
        out.append("附加质量")
    if study.get("load_cases") or study.get("combinations"):
        out.append("工况组合")
    if int((study.get("mesh") or {}).get("max_elements") or 0) > FREE_MAX_ELEMENTS:
        out.append("超过 20 万单元的大模型")
    return list(dict.fromkeys(out))


def gate(study: dict | None = None, *, feature: str | None = None) -> None:
    """免费版用了专业版功能就拒绝：study 给算例（看用到哪些），feature 给按钮名（AI 起草、正式报告……）"""
    if pro_allowed():
        return
    needs = ([feature] if feature else []) + (pro_needs(study) if study else [])
    if needs:
        raise NeedsPro("这是问渠有限元专业版的功能：{}。免费版可以算单个实体零件的静力、模态、线性屈曲；"
                       "要用专业版，请在“帮助”菜单的“问渠有限元：授权…”里导入授权文件".format("、".join(needs)))
