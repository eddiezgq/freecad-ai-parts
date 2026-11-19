"""问渠CAM 的免费 / 专业两档（ADR-0104 决策 5）。

- 版本（edition）同问渠有限元（`assist/fea_edition.py`）：`cam` 是单独安装的问渠CAM 版；全功能版（零件库安装包、仓库开发）不分档。
- 免费：G 代码检查（时间、撞料、过切、超程、功率），车削与 2.5 轴铣编程，两轴车床、三轴加工中心的整机仿真，FANUC 一种后处理。
- 专业（授权文件里有功能 `cam_pro`）：AI 起草工艺，3+2 定位、车铣复合、五轴联动（机床有回转轴），五轴与车铣整机仿真，
  全部后处理（西门子、广数……），工艺卡与程序单正式报告。
- 授权按 ADR-0066 的签名授权文件离线校验；一个授权文件可以同时开 fea_pro、mbd_pro、cam_pro（套装）。
  授权只决定能不能用专业版功能，不改变任何计算、仿真与检查结论——安全检查（整机仿真、回读比对）两档一样，免费版不少查一项。
"""

from __future__ import annotations

from assist import fea_edition

PRO = "cam_pro"
FREE_POSTS = ("fanuc",)
FEATURES = {"ai": "AI 起草工艺", "card": "工艺卡与程序单正式报告"}


class NeedsPro(Exception):
    """免费版不能用的功能；消息里写明是哪些、怎么开放"""


def edition() -> str:
    return fea_edition.edition()


def pro_allowed() -> bool:
    if edition() != "cam":
        return True
    from licensing import runtime

    return runtime.allows(PRO)


def pro_needs(setup: dict, machine_model: dict | None = None) -> list[str]:
    """这次计算（analysis.cam.run 的设置）用到的专业版功能（中文，界面显示时翻译）"""
    out = []
    post = setup.get("post")
    if post and post not in FREE_POSTS:
        out.append("FANUC 以外的后处理")
    if machine_model and any(a["type"] == "rotary" for a in machine_model.get("axes") or []):
        out.append("五轴 / 车铣复合机床")
    return out


def gate(setup: dict | None = None, *, feature: str | None = None, machine_model: dict | None = None) -> None:
    """免费版用了专业版功能就拒绝。feature：ai（AI 起草工艺）、card（正式工艺卡）"""
    if pro_allowed():
        return
    needs = ([FEATURES[feature]] if feature else []) + (pro_needs(setup, machine_model) if setup is not None else [])
    if needs:
        raise NeedsPro("这是问渠CAM 专业版的功能：{}。免费版可以检查 G 代码、车削和 2.5 轴铣编程、两轴车床和三轴加工中心的整机仿真、"
                       "出 FANUC 程序；要用专业版，请在“问渠CAM”菜单的“授权…”里导入授权文件".format("、".join(needs)))
