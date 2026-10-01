"""由复核后的抽取值组装组件（ADR-0023 第 4 条）。纯函数：不联网、不读数据库。

输入是 target → 参数值对象（ADR-0021 的 target 写法），输出完整组件或缺项清单。
- 端口 id、类型、方向、运动方式取自品类 schema
- 端口坐标系按品类约定布置，备注写明“按品类约定生成，布局时核对”
- 包络由 dims/ 与端口尺寸按品类规则生成
- 由已有字段推出的值记为 method: computed，并写明依据；只在该字段没有给出时补
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from functools import cache

from kb.validation import SCHEMA_DIR, errors

FRAME_NOTE = "坐标系按品类约定生成（ADR-0023），布局时核对"


@dataclass(frozen=True)
class PortSpec:
    id: str
    types: tuple[str, ...]
    dir: str
    motion: str | None


@cache
def standard_ports(category: str) -> tuple[PortSpec, ...]:
    cat = json.loads((SCHEMA_DIR / "categories" / f"{category}.schema.json").read_text(encoding="utf-8"))
    out = []
    for rule in cat["properties"].get("ports", {}).get("allOf", []):
        props = rule["contains"]["properties"]
        types = tuple(props["type"].get("enum") or [props["type"]["const"]])
        mechanical = types[0].startswith("mechanical.")
        motion = props.get("motion", {}).get("const") or ("stationary" if mechanical else None)
        out.append(PortSpec(props["id"]["const"], types, props.get("dir", {}).get("const", "bidir"), motion))
    return tuple(out)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.casefold()).strip("-")


def component_id(category: str, vendor: str, model: str, *, test: bool = False) -> str:
    """<品类>.<厂商>.<型号>；厂商或型号转写后为空时报错（如纯中文名称，须人工给出拉丁转写）。"""
    vendor_part = slug(vendor)
    model_part = re.sub(r"[^a-z0-9.]+", "-", model.casefold()).strip("-.")
    model_part = re.sub(r"[.-]{2,}", "-", model_part)
    if not vendor_part or not model_part:
        raise ValueError(f"厂商 {vendor!r} 或型号 {model!r} 无法转写为组件 id，请给出拉丁字母写法")
    return f"{'test.' if test else ''}{category}.{vendor_part}.{model_part}"


def _derived(value, why: str, basis: list[dict] | None) -> dict:
    """推导值。basis 为所依据的字段：复核状态取它们的“与”；basis 为 None 表示按约定推出，未经复核。"""
    reviewed = bool(basis) and all(b.get("reviewed") is True for b in basis)
    return {"value": value, "source": {"formula": why}, "method": "computed", "confidence": 1, "reviewed": reviewed}


def _num(values: dict, target: str):
    pv = values.get(target)
    return pv.get("value") if pv and isinstance(pv.get("value"), (int, float)) else None


def derive(category: str, values: dict) -> dict:
    """由已有字段推出的值（只补没给出的字段）。返回新增的 target → 参数值。

    定义性推导（如轴承端口的公差体系）视为与依据字段同等可靠；按约定的推导（如轴承内外圈为光面）
    记为未复核，组装计划中列出，由复核员确认。
    """
    out: dict = {}

    def put(target, value, why, basis):
        if target not in values:
            out[target] = _derived(value, why, basis)

    for p in standard_ports(category):
        base = f"ports/{p.id}"
        if "mechanical.flange" in p.types:
            thread, hole = values.get(f"{base}/thread"), values.get(f"{base}/hole_diameter_mm")
            if thread and not hole:
                put(f"{base}/hole_kind", "threaded", "印有螺纹规格，故为螺纹孔", [thread])
            elif hole and not thread:
                put(f"{base}/hole_kind", "through", "印有孔径，故为通孔", [hole])
        if "mechanical.mount_face" in p.types and f"{base}/pitch_x_mm" in values:
            put(f"{base}/pattern", "rect", "安装孔按水平、垂直间距排列（schema 只有 rect）",
                [values[f"{base}/pitch_x_mm"]])
    if category == "bearing":
        for port in ("inner", "outer"):
            fit = values.get(f"ports/{port}/fit")
            put(f"ports/{port}/fit_system", "bearing", "滚动轴承内外圈按 ISO 492 精度等级", [fit] if fit else None)
            put(f"ports/{port}/feature", "plain", "按约定：轴承内外圈为圆柱光面（锥孔轴承须人工改正）", None)
    if category == "drive":
        ct = values.get("ports/power_in/current_type")
        if ct and ct.get("value") == "dc":
            put("ports/power_in/phases", 0, "直流供电，相数按 schema 约定记 0", [ct])
        pv = values.get("ports/encoder_in/protocol")
        protos = pv.get("value") if pv else None
        if protos:
            protos = protos if isinstance(protos, list) else [protos]
            if "vendor_proprietary" not in protos:
                kinds = sorted({"incremental" if x == "incremental_abz" else "absolute" for x in protos})
                put("ports/encoder_in/kind", kinds, "由支持的编码器协议推出", [pv])
    return out


def _part(shape: str, z: float, label: str, **dims) -> dict:
    part = {"shape": shape, "z_start_mm": z, "label": label}
    part.update({k: copy.deepcopy(v) for k, v in dims.items()})
    return part


def envelope(category: str, values: dict) -> tuple[list[dict] | None, list[str]]:
    """按品类规则生成包络各部分；缺尺寸时返回（None, 缺项）。"""
    v = values.get

    def need(*targets):
        return [t for t in targets if t not in values]

    if category == "servo_motor":
        miss = need("dims/body_length_mm", "dims/square_mm")
        if miss:
            return None, miss
        parts = [_part("box", -_num(values, "dims/body_length_mm"), "body", length_mm=v("dims/body_length_mm"),
                       width_mm=v("dims/square_mm"), height_mm=v("dims/square_mm"))]
        if "ports/shaft/usable_length_mm" in values and "ports/shaft/diameter_mm" in values:
            parts.append(_part("cylinder", 0, "shaft", length_mm=v("ports/shaft/usable_length_mm"),
                               diameter_mm=v("ports/shaft/diameter_mm")))
        return parts, []
    if category == "reducer":
        if "dims/overall_length_mm" not in values:
            return None, ["dims/overall_length_mm"]
        if "dims/square_mm" in values:
            return [_part("box", 0, "body", length_mm=v("dims/overall_length_mm"), width_mm=v("dims/square_mm"),
                          height_mm=v("dims/square_mm"))], []
        if "dims/outer_diameter_mm" in values:
            return [_part("cylinder", 0, "body", length_mm=v("dims/overall_length_mm"),
                          diameter_mm=v("dims/outer_diameter_mm"))], []
        return None, ["dims/outer_diameter_mm 或 dims/square_mm"]
    if category == "drive":
        miss = need("dims/width_mm", "dims/height_mm", "dims/depth_mm")
        if miss:
            return None, miss
        return [_part("box", 0, "body", length_mm=v("dims/depth_mm"), width_mm=v("dims/width_mm"),
                      height_mm=v("dims/height_mm"))], []
    if category == "bearing":
        od = v("dims/outer_diameter_mm") or v("ports/outer/diameter_mm")
        if od is None or "params/width_mm" not in values:
            return None, need("params/width_mm") + ([] if od else ["ports/outer/diameter_mm"])
        return [_part("cylinder", 0, "body", length_mm=v("params/width_mm"), diameter_mm=od)], []
    if category == "adapter":
        if "dims/overall_length_mm" not in values:
            return None, ["dims/overall_length_mm"]
        if "dims/outer_diameter_mm" in values:
            return [_part("cylinder", 0, "body", length_mm=v("dims/overall_length_mm"),
                          diameter_mm=v("dims/outer_diameter_mm"))], []
        side = v("dims/square_mm")
        w, h = v("dims/width_mm") or side, v("dims/height_mm") or side
        if w and h:
            return [_part("box", 0, "body", length_mm=v("dims/overall_length_mm"), width_mm=w, height_mm=h)], []
        return None, ["dims/outer_diameter_mm、dims/square_mm 或 dims/width_mm + dims/height_mm"]
    return None, [f"不支持的品类 {category}"]


def frame_z(category: str, port_id: str, values: dict) -> float | None:
    """端口坐标系原点的 z（品类约定）：安装面在 0，输出侧在总长处，电机轴端在轴伸长度处。"""
    if category == "servo_motor" and port_id == "shaft":
        return _num(values, "ports/shaft/usable_length_mm")
    if category == "reducer" and port_id in ("output_flange", "housing_mount"):
        return _num(values, "dims/overall_length_mm")
    return 0


def _port_type(p: PortSpec, values: dict) -> str | None:
    """端口允许多种类型时，按已给出的规格字段判断；判断不了返回 None。"""
    if len(p.types) == 1:
        return p.types[0]
    given = {t.rsplit("/", 1)[-1] for t in values if t.startswith(f"ports/{p.id}/")}
    fits = []
    for ptype in p.types:
        spec = json.loads((SCHEMA_DIR / "port-types" / f"{ptype}.schema.json").read_text(encoding="utf-8"))
        if given and given <= set(spec["properties"]["spec"]["properties"]):
            fits.append(ptype)
    return fits[0] if len(fits) == 1 else None


_ENVELOPE_DIMS = {
    "servo_motor": {"dims/body_length_mm", "dims/square_mm"},
    "reducer": {"dims/overall_length_mm", "dims/square_mm", "dims/outer_diameter_mm"},
    "drive": {"dims/width_mm", "dims/height_mm", "dims/depth_mm"},
    "bearing": {"dims/outer_diameter_mm"},
    "adapter": {"dims/overall_length_mm", "dims/outer_diameter_mm", "dims/square_mm", "dims/width_mm",
                "dims/height_mm"},
}


def assemble(category: str, vendor: str, model: str, values: dict, *, test: bool = False,
             license: str = "params-only", note: str | None = None,
             fallback_envelope: dict | None = None,
             fallback_frames: dict | None = None) -> tuple[dict | None, list[str], list[str]]:
    """组装组件。返回（组件或 None, 缺项与错误, 需要复核员确认的事项）。

    fallback_envelope / fallback_frames：更新已有组件且本次没有足够的整体尺寸时，沿用原包络与原端口坐标系。
    """
    problems: list[str] = []
    notes: list[str] = []
    try:
        cid = component_id(category, vendor, model, test=test)
    except ValueError as exc:
        return None, [str(exc)], []
    derived = derive(category, values)
    values = {**values, **derived}
    notes += [f"推导 {t} = {pv['value']}（{pv['source']['formula']}）" for t, pv in sorted(derived.items())]
    comp: dict = {
        "id": cid, "category": category, "vendor": vendor, "model": model, "status": "active", "license": license,
        "params": {t.split("/", 1)[1]: copy.deepcopy(pv) for t, pv in values.items() if t.startswith("params/")},
        "ports": [],
    }
    for p in standard_ports(category):
        spec = {t.rsplit("/", 1)[-1]: copy.deepcopy(pv) for t, pv in values.items() if t.startswith(f"ports/{p.id}/")}
        ptype = _port_type(p, values)
        if ptype is None:
            problems.append(f"端口 {p.id} 的类型无法由已给字段判断（{' / '.join(p.types)}），请补字段")
            continue
        port = {"id": p.id, "type": ptype, "dir": p.dir}
        if p.motion is not None:
            z = frame_z(category, p.id, values)
            port["motion"] = p.motion
            if z is not None:
                port["frame"] = {"origin_mm": [0, 0, z], "axis": [0, 0, 1]}
            elif fallback_frames and p.id in fallback_frames:
                port["frame"] = copy.deepcopy(fallback_frames[p.id])
            else:
                problems.append(f"端口 {p.id} 的坐标系需要轴伸或总长，请补字段")
                continue
            port["note"] = FRAME_NOTE
        port["spec"] = dict(sorted(spec.items()))
        comp["ports"].append(port)
    parts, missing = envelope(category, values)
    if parts is None and fallback_envelope is not None:
        comp["envelope"] = copy.deepcopy(fallback_envelope)
        notes.append("本次没有足够的整体尺寸，沿用原组件的包络")
    elif parts is None:
        problems += [f"包络缺少 {m}" for m in missing]
    else:
        comp["envelope"] = {"parts": parts}
    unused = sorted(t for t in values if t.startswith("dims/") and t not in _ENVELOPE_DIMS.get(category, set()))
    notes += [f"{t} 未用于包络，不会写入组件" for t in unused]
    if note:
        comp["note"] = note
    if problems:
        return None, problems, notes
    errs = errors("component.schema.json", comp)
    if errs:
        return None, [f"schema：{e}" for e in errs], notes
    return comp, [], notes


def values_from_component(comp: dict) -> dict:
    """已有组件 → target → 参数值（用于更新时以原组件为底合并）。"""
    out = {f"params/{k}": copy.deepcopy(v) for k, v in comp["params"].items()}
    for p in comp["ports"]:
        out.update({f"ports/{p['id']}/{k}": copy.deepcopy(v) for k, v in p["spec"].items()})
    return out
