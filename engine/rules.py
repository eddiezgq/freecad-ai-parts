"""校验规则数据表（schema/rules/，ADR-0011）。只读本仓库内的数据文件，不联网、不读数据库。

规则表目前为草稿，逐项核对见 issue #3、#14；校验结果中引用草稿规则时，由调用方在说明中注明。
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path

RULES_DIR = Path(__file__).resolve().parent.parent / "schema" / "rules"


@cache
def _table(name: str) -> dict:
    return json.loads((RULES_DIR / f"{name}.json").read_text(encoding="utf-8"))


@cache
def iso286_pairs() -> dict[tuple[str, str], str]:
    """(孔公差带, 轴公差带) → 配合类别。"""
    return {(e["hole"], e["shaft"]): e["fit_class"] for e in _table("iso286-fits")["entries"]}


@cache
def clamping_matrix() -> dict[tuple[str, str, str], tuple[str, str | None]]:
    """(轴形式, 孔形式, 紧固方式) → (结果, 原因)。"""
    return {(e["shaft_feature"], e["bore_feature"], e["clamping"]): (e["result"], e.get("reason"))
            for e in _table("feature-clamping-matrix")["entries"]}


@cache
def iso273_medium() -> dict[str, float]:
    """螺纹 → 中等系列间隙孔直径（mm）。"""
    return {e["thread"]: e["medium_mm"] for e in _table("iso273-clearance-holes")["entries"]}


def bearing_fit_classes(ring: str, load_on_ring: str, bearing_kind: str, d_mm: float) -> set[str] | None:
    """轴承配合推荐表（ADR-0017）：该圈、该载荷状态、该轴承类型与直径下，任一载荷等级推荐的公差带集合。

    表未覆盖（轴承类型或直径超出范围）时返回 None。
    """
    found: set[str] = set()
    covered = False
    for e in _table("bearing-fits")["entries"]:
        if e["ring"] != ring or e["load_on_ring"] != load_on_ring or bearing_kind not in e["bearing_kinds"]:
            continue
        if e["d_over_mm"] < d_mm <= e["d_upto_mm"]:
            covered = True
            found.update(e["classes"])
    return found if covered else None
