"""机床模型 cam-machine/1（ADR-0105）：读文件、按 schema 校验、旧格式（ADR-0059 的 machines.yaml）转换、给旧代码的简单视图。

- `load(path)` 读一个 JSON 文件（一台机床）；`validate(model)` 返回 schema 错误清单（空 = 合格）。
- `from_legacy(m)` 把旧格式的一台机床转成 cam-machine/1；旧格式里没有的数（数控系统等）不编：
  控制系统写 `other`，出处写“由旧格式 machines.yaml 转换”。
- `legacy_view(model)` 给现有车削、2.5 轴铣、程序检查用的旧字段（max_rpm、power_kw、eff、x/y/z 行程、rapid、home、tool_change_s），
  同时在 `model` 键里带上完整的机床模型。旧格式必填而新文件缺的（功率、效率），不编，视图里不写；用到它们的检查报“未知”。
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

FORMAT = "cam-machine/1"
ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "schema" / "cam-machine.schema.json"


class MachineError(ValueError):
    pass


@lru_cache(maxsize=1)
def _validator():
    from jsonschema import Draft202012Validator

    return Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8")))


def validate(model: dict) -> list[str]:
    """schema 错误（中文前缀 + jsonschema 原文），空表示合格"""
    data = {k: v for k, v in model.items() if not k.startswith("_")}
    errs = sorted(_validator().iter_errors(data), key=lambda e: list(e.absolute_path))
    return [f"{'/'.join(map(str, e.absolute_path)) or '（顶层）'}：{e.message}" for e in errs]


def check(model: dict, where: str = "") -> dict:
    errs = validate(model)
    if errs:
        name = model.get("id") or where or "机床"
        raise MachineError(f"{where + '：' if where else ''}机床 {name} 不符合 cam-machine/1：" + "；".join(errs[:5]))
    return model


def load(path: str | Path) -> dict:
    p = Path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MachineError(f"{p}：读不了机床文件：{exc}") from exc
    return with_dir(check(data, str(p)), p.parent)


def with_dir(model: dict, folder) -> dict:
    """记下机床文件所在目录（三角网格部件的文件相对它）。以 _ 开头的键不算机床数据：不进指纹、不进 schema 检查"""
    return {**model, "_dir": str(Path(folder).resolve())}


def from_legacy(m: dict) -> dict:
    """旧格式（kind lathe | mill，x/y/z 行程，rapid，home）→ cam-machine/1。车床 X 为直径编程。"""
    kind = m.get("kind")
    if kind not in ("lathe", "mill"):
        raise MachineError(f"旧格式机床 {m.get('id')!r}：kind 要是 lathe 或 mill")
    rapid = m.get("rapid") or {}
    axes = []
    ids = ("x", "z") if kind == "lathe" else ("x", "y", "z")
    unit = {"x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}
    for a in ids:
        if a not in m:
            continue
        lo, hi = m[a]
        ax = {"id": a.upper(), "type": "linear", "carrier": "tool", "direction": unit[a], "min": float(lo), "max": float(hi)}
        if a in rapid:
            ax["rapid"] = float(rapid[a])
        if kind == "lathe" and a == "x":
            ax["diameter_mode"] = True
        axes.append(ax)
    spindle = {"max_rpm": float(m["max_rpm"])}
    if "power_kw" in m:
        spindle["power_kw"] = float(m["power_kw"])
    if "eff" in m:
        spindle["efficiency"] = float(m["eff"])
    out = {"format": FORMAT, "id": str(m["id"]), "name": str(m["name"]), "source": "由旧格式 machines.yaml 转换",
           "kind": kind, "controller": {"family": "other"}, "spindle": spindle, "axes": axes}
    if m.get("example"):
        out["example"] = True
    if kind == "mill":
        # 旧格式的铣床是三轴立式：刀具沿 +Z；主轴端面基准点在旧格式里没有，取原点（只影响刀长的零点，三轴程序用不到）
        out["tool"] = {"direction": [0, 0, 1], "gauge_point_mm": [0, 0, 0]}
    if "home" in m:
        out["lathe_home_mm"] = [float(v) for v in m["home"]]
    if "tool_change_s" in m:
        out["tool_change_s"] = float(m["tool_change_s"])
    return out


def is_three_axis(model: dict) -> bool:
    """只有直线轴（车床两轴、加工中心三轴）——现有的车削、2.5 轴铣、程序检查只认这种"""
    return model["kind"] in ("lathe", "mill") and all(a["type"] == "linear" for a in model["axes"])


def is_three_plus_two(model: dict) -> bool:
    """三根直线轴 + 两根回转轴的加工中心（3+2 定位，ADR-0106 C2a）"""
    t = [a["type"] for a in model["axes"]]
    return model["kind"] == "mill" and t.count("linear") == 3 and t.count("rotary") == 2


def b_axis(model: dict) -> dict | None:
    """B 轴车铣中心（ADR-0106 C4a）刀具一侧的摆动轴；没有返回 None"""
    rs = [a for a in model["axes"] if a["type"] == "rotary" and a["carrier"] == "tool"]
    return rs[0] if len(rs) == 1 else None


def sub_spindle(model: dict) -> dict | None:
    """双主轴车铣中心的副主轴（ADR-0106 C4b、ADR-0121）；没有返回 None"""
    return model.get("sub_spindle")


def sub_axes(model: dict) -> set:
    """只带副主轴一侧的轴（副主轴移动轴、副主轴 C 轴）：主主轴上的加工不看它们"""
    sp = model.get("sub_spindle")
    return {sp["axis"], *([sp["c_axis"]] if sp.get("c_axis") else [])} if sp else set()


def main_model(model: dict, sub_pos: float = 0.0) -> dict:
    """主主轴上加工用的运动链：去掉副主轴的轴，副主轴一侧的部件按副主轴停在 sub_pos（移动轴的位置）固定在机床上（ADR-0106 C4b-1）。
    去掉的轴记在 sub_spindle["axis_def"] 里（查行程用）"""
    sx = sub_axes(model)
    if not sx:
        return model
    sp = model["sub_spindle"]
    ax = next(a for a in model["axes"] if a["id"] == sp["axis"])
    off = [float(sub_pos) * float(c) for c in ax["direction"]]

    def moved(c):
        if "mesh" in c and any(abs(v) > 1e-9 for v in off):
            raise MachineError(f"副主轴一侧的部件 {c['id']} 是网格，还不能跟着副主轴移动（ADR-0106 C4b-2）")
        c = {**c, "attached_to": "base"}
        if "box_mm" in c:
            b = c["box_mm"]
            c["box_mm"] = [b[0] + off[0], b[1] + off[1], b[2] + off[2], b[3] + off[0], b[4] + off[1], b[5] + off[2]]
        if "cylinder_mm" in c:
            cy = c["cylinder_mm"]
            c["cylinder_mm"] = {**cy, "p0": [u + v for u, v in zip(cy["p0"], off, strict=True)],
                                "p1": [u + v for u, v in zip(cy["p1"], off, strict=True)]}
        return c

    return {**model, "axes": [a for a in model["axes"] if a["id"] not in sx],
            "components": [moved(c) if c.get("attached_to") in sx else c for c in model.get("components") or []],
            "sub_spindle": {**sp, "axis_def": ax}}


def is_mill_turn(model: dict) -> bool:
    """车铣中心：X、Z（可带 Y）直线轴 + C 轴（ADR-0106 C2b）；B 轴车铣中心再加刀具一侧一根摆动轴（C4a）；副主轴的轴不算（C4b）"""
    t = [a["type"] for a in model["axes"] if a["id"] not in sub_axes(model)]
    nr = t.count("rotary")
    return model["kind"] == "mill_turn" and t.count("linear") in (2, 3) and (nr == 1 or (nr == 2 and b_axis(model) is not None))


def legacy_view(model: dict) -> dict:
    """旧代码用的字段；行程按工件坐标（刀具相对工件）给，带工件一侧的直线轴把方向翻过来"""
    model = main_model(model)                 # 双主轴：主主轴上加工时副主轴停在零位（ADR-0106 C4b-1）
    v = {"id": model["id"], "name": model["name"], "kind": model["kind"], "max_rpm": float(model["spindle"]["max_rpm"]),
         "rapid": {}, "model": model, "example": bool(model.get("example"))}
    sp = model["spindle"]
    if "power_kw" in sp:
        v["power_kw"] = float(sp["power_kw"])
    if "efficiency" in sp:
        v["eff"] = float(sp["efficiency"])
    for a in model["axes"]:
        if a["type"] != "linear" or a["id"] in sub_axes(model):
            continue
        key = a["id"].lower()
        lo, hi = float(a["min"]), float(a["max"])
        d = a["direction"]
        # 带工件一侧、方向与名义轴相反（[-1,0,0] 之类）：刀具相对工件的坐标 = -工作台位移，但指令值不变；
        # 旧代码里的行程是指令值的范围，原样给
        if max(abs(x) for x in d) < 0.999:
            continue  # 斜轴不进旧视图
        v[key] = [lo, hi]
        if "rapid" in a:
            v["rapid"][key] = float(a["rapid"])
    rot = [a["id"] for a in model["axes"] if a["type"] == "rotary"]
    if rot:
        v["rotary"] = rot
    if "lathe_home_mm" in model:
        v["home"] = list(model["lathe_home_mm"])
    if "tool_change_s" in model:
        v["tool_change_s"] = float(model["tool_change_s"])
    return v
