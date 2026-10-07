"""材料库（ADR-0056）：analysis/common/materials.yaml，每条注明出处，没有出处的性能不写。"""

from __future__ import annotations

from functools import cache
from pathlib import Path

import yaml

from kb.validation import errors

PATH = Path(__file__).with_name("materials.yaml")


class MissingData(LookupError):
    """计算需要的材料性能缺失；消息说明缺什么。"""


@cache
def _table() -> dict[str, dict]:
    raw = yaml.safe_load(PATH.read_text(encoding="utf-8"))
    srcs = raw["sources"]
    out = {}
    for m in raw["materials"]:
        m = dict(m)
        m["sources"] = [srcs[k] for k in m.pop("src")]
        errs = errors("material.schema.json", m)
        if errs:
            raise ValueError(f"材料 {m.get('id')} 不符合 schema：{'；'.join(errs[:3])}")
        out[m["id"]] = m
    return out


def all_materials() -> list[dict]:
    return [dict(m) for m in _table().values()]


def get(mid: str) -> dict:
    m = _table().get(mid)
    if m is None:
        raise MissingData(f"材料库里没有 {mid}")
    return dict(m)


def require(m: dict, fields: list[str], purpose: str) -> None:
    """计算前检查需要的性能是否都有；缺时抛 MissingData，不估。"""
    miss = [f for f in fields if f not in m]
    if miss:
        raise MissingData(f"{m['name']} 缺少{purpose}需要的性能：{'、'.join(miss)}（材料库只收有出处的值）")


def safety(stats: dict, m: dict, optional: bool = False) -> None:
    """按材料强度给 stats 加 strength_mpa、strength_kind、safety_factor；optional=True 时材料没有强度就不加（工厂教学材料表用）。"""
    if optional and not (m.get("yield_strength_mpa") if not m.get("brittle") else m.get("ultimate_strength_mpa")):
        return
    strength, kind = strength_mpa(m)
    stats["strength_mpa"], stats["strength_kind"] = strength, kind
    stats["safety_factor"] = round(strength / max(stats["vm_max_mpa"], 1e-9), 3)


def strength_mpa(m: dict) -> tuple[float, str]:
    """安全系数按屈服强度；脆性材料按抗拉强度。"""
    if m.get("brittle"):
        require(m, ["ultimate_strength_mpa"], "强度校核")
        return m["ultimate_strength_mpa"], "抗拉强度"
    require(m, ["yield_strength_mpa"], "强度校核")
    return m["yield_strength_mpa"], "屈服强度"
