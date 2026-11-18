"""零件库的完整度报告（ADR-0099 41.3）：每个零件缺哪些数据、缺了会让哪些校验变成“待确认”、先补哪个。

“哪个字段影响哪项校验”不手写清单，由代码从校验规则里试出来：拿 tests/golden 里同品类的标准题（人审定过的系统），
把题里那个组件换成“标准题的组件 + 这个零件已有的数据”，再逐个删掉这个零件缺的字段跑引擎，看哪些校验从有结论
变成 unknown。这样替代数据（有效率曲线就不缺效率值；通孔法兰不要螺纹）自然算对；规则改了，结果跟着变。

没有标准题的品类（自制件、通用外购件、步进电机），只按品类 schema 的关键参数（x-key-fields）列缺项。

纯函数：不联网、不调用 AI、不读数据库。
"""

from __future__ import annotations

import copy
import json
from collections.abc import Iterable
from functools import cache, lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CATEGORIES = ROOT / "schema" / "categories"
CHECK_NAMES = {"C1": "接口类型", "C2": "圆柱配合", "C3": "法兰配合", "C4": "连续扭矩", "C5": "峰值扭矩",
               "C6": "减速器过载保护", "C7": "转速", "C8": "惯量比", "C9": "供电", "C10": "编码器与总线",
               "C11": "轴承与包络"}  # 与 freecad_addon/core/live_check.CHECK_NAMES 一致（测试核对）
CASES_PER_CATEGORY = 12                    # 每个品类最多用几道标准题试（贪心挑覆盖面最大的）
CONCLUSIVE = ("pass", "warn", "fail")


def _key(where: str, name: str) -> str:
    """params.<名> 或 ports.<端口 id>.<名>"""
    return f"{where}.{name}"


def _order(checks: Iterable[str]) -> list[str]:
    return sorted(set(checks), key=lambda c: int(c[1:]))


@lru_cache(maxsize=1)
def _golden() -> tuple[dict, dict[str, list[tuple[dict, dict, str]]]]:
    """标准题按品类分组：{品类: [(系统, 基线各校验状态, 题里该品类组件的 id)]}"""
    from engine.golden import GOLDEN, cases, load_fixtures
    from engine.validate import validate

    fixtures = load_fixtures(GOLDEN)
    by_cat: dict[str, list[tuple[dict, dict, str]]] = {}
    for path in cases(GOLDEN):
        system = yaml.safe_load(path.read_text(encoding="utf-8"))["system"]
        try:
            base = {c["check"]: c["status"] for c in validate(system, fixtures.get)["checks"]}
        except Exception:  # noqa: BLE001, S112 — 本身就算不了的题不用
            continue
        if not any(s in CONCLUSIVE for s in base.values()):
            continue
        seen = set()
        for inst in system.get("components", []):
            cid = inst.get("component")
            comp = fixtures.get(cid)
            if comp is None or cid in seen:
                continue
            seen.add(cid)
            by_cat.setdefault(comp["category"], []).append((system, base, cid))
    return fixtures, {cat: _cover(group) for cat, group in by_cat.items()}


def _cover(group: list[tuple[dict, dict, str]]) -> list[tuple[dict, dict, str]]:
    """挑几道题，使“有结论的校验 × 标准题组件的端口组合”都至少被一道题覆盖（贪心）"""
    def feats(item):
        _system, base, cid = item
        return {c for c, s in base.items() if s in CONCLUSIVE} | {("cid", cid)}

    chosen, covered = [], set()
    pool = sorted(group, key=lambda it: -len(feats(it)))
    while pool and len(chosen) < CASES_PER_CATEGORY:
        best = max(pool, key=lambda it: len(feats(it) - covered))
        if not feats(best) - covered:
            break
        chosen.append(best)
        covered |= feats(best)
        pool.remove(best)
    return chosen


def _fields(comp: dict) -> dict[str, tuple[str, str, str | None]]:
    out = {_key("params", k): ("params", k, None) for k in comp.get("params", {})}
    for p in comp.get("ports", []):
        for k in p.get("spec") or {}:
            out[_key(f"ports.{p['id']}", k)] = ("ports", k, p["id"])
    return out


def _hybrid(fixture: dict, comp: dict) -> dict:
    """标准题的组件，盖上这个零件已有的参数和端口数据（端口按 id 对上）"""
    h = copy.deepcopy(fixture)
    h["params"].update(copy.deepcopy(comp.get("params", {})))
    mine = {p["id"]: p for p in comp.get("ports", [])}
    for p in h.get("ports", []):
        if p["id"] in mine:
            p.setdefault("spec", {}).update(copy.deepcopy(mine[p["id"]].get("spec") or {}))
    return h


def _drop(comp: dict, where: str, name: str, port: str | None) -> dict:
    out = copy.deepcopy(comp)
    if where == "params":
        out["params"].pop(name, None)
    else:
        for p in out.get("ports", []):
            if p["id"] == port:
                (p.get("spec") or {}).pop(name, None)
    return out


def _unknowns(system: dict, fixtures: dict, fid: str, comp: dict) -> dict[str, int] | None:
    """各校验里“待确认”的条目数（比整项状态细：整项已因别的原因判 fail 时，也看得出多了一条待确认）"""
    from engine.validate import validate

    try:
        checks = validate(system, lambda i: comp if i == fid else fixtures.get(i))["checks"]
    except Exception:  # noqa: BLE001 — 由调用方按“算不下去”处理
        return None
    return {c["check"]: sum(f["status"] == "unknown" for f in c.get("findings") or [c]) for c in checks}


def check_impacts(comp: dict) -> dict[str, list[str]]:
    """这个零件缺的每个字段 → 缺它会变成 unknown 的校验（只列标准题能试出来的字段）"""
    fixtures, by_cat = _golden()
    have = set(_fields(comp))
    my_ports = {p["id"] for p in comp.get("ports", [])}
    impacts: dict[str, set[str]] = {}
    for system, _base, fid in by_cat.get(comp.get("category", ""), []):
        hyb = _hybrid(fixtures[fid], comp)
        before = _unknowns(system, fixtures, fid, hyb)
        if before is None:
            continue                             # 换上这个零件的数据后本题算不下去：这道题不用
        for key, (where, name, port) in _fields(hyb).items():
            if key in have or (port is not None and port not in my_ports):
                continue                         # 已有的不用补；这个零件没有的端口不要求它的字段
            after = _unknowns(system, fixtures, fid, _drop(hyb, where, name, port))
            if after is None:                    # 删了字段引擎算不下去：本题的全部校验都算受影响
                hit = set(before)
            else:
                hit = {c for c, n in after.items() if n > before.get(c, 0)}
            impacts.setdefault(key, set()).update(hit)
    return {k: _order(v) for k, v in impacts.items() if v}


@cache
def key_fields(category: str) -> tuple[str, ...]:
    p = CATEGORIES / f"{category}.schema.json"
    if not p.is_file():
        return ()
    return tuple(json.loads(p.read_text(encoding="utf-8")).get("x-key-fields", []))


# 关键参数的替代数据：有右边的，就不缺左边（ADR-0047：目录只给效率曲线时，校验按曲线查表）
ALTERNATIVES = {"params.efficiency_ratio": ("params.efficiency_curve",)}


def where_to_find(key: str, category: str | None = None) -> str:
    """去哪找这项数据（给人看的提示）"""
    name = key.rsplit(".", 1)[-1]
    own = category == "custom_part"
    if key == "envelope" or (key.startswith("ports.") and (name.endswith("_mm") or name in (
            "hole_count", "hole_kind", "pilot_kind", "fit", "feature", "thread", "clamping"))):
        return "三维模型上量（自制件）" if own else "规格书的外形尺寸图（或厂商三维模型）"
    if name in ("voltage_class_v", "rated_current_a", "peak_current_a", "voltage_v", "phases", "current_type"):
        return "规格书的电气规格表"
    if name in ("protocol", "kind"):
        return "规格书的通讯 / 编码器规格"
    if name.endswith("_kg"):
        return "按材料密度和三维模型体积算（自制件）" if own else "规格书的规格表"
    if name.endswith(("_nm", "_rpm", "_kgm2", "_w", "_n")) or name in ("ratio", "efficiency_ratio"):
        return "规格书的性能参数表"
    if name in ("part_kind", "material"):
        return "图纸标题栏" if own else "规格书或采购资料"
    return "规格书"


def component_gaps(comp: dict) -> list[dict]:
    """一个零件缺的数据：[{field, checks, key, hint}]，影响校验多的排前面"""
    cat = comp.get("category", "")
    have = set(_fields(comp))
    gaps = {k: {"field": k, "checks": v, "key": False} for k, v in check_impacts(comp).items()}
    for name in key_fields(cat):
        k = _key("params", name)
        if k in have or any(a in have or a.split(".", 1)[1] in comp.get("params", {}) for a in ALTERNATIVES.get(k, ())):
            continue
        gaps.setdefault(k, {"field": k, "checks": [], "key": True})["key"] = True
    if not (comp.get("envelope") or {}).get("parts"):
        gaps["envelope"] = {"field": "envelope", "checks": ["C11"], "key": True}
    out = [{**g, "hint": where_to_find(g["field"], cat)} for g in gaps.values()]
    return sorted(out, key=lambda g: (-len(g["checks"]), not g["key"], g["field"]))


def report(components: Iterable[dict]) -> dict:
    """整库的完整度：每个零件的缺项与影响的校验，按影响面排序；再给“先补这些”清单"""
    rows = []
    for comp in components:
        gaps = component_gaps(comp)
        rows.append({"id": comp["id"], "category": comp.get("category"), "vendor": comp.get("vendor"),
                     "model": comp.get("model"), "missing": gaps,
                     "checks_affected": _order(c for g in gaps for c in g["checks"]), "complete": not gaps})
    rows.sort(key=lambda r: (-len(r["checks_affected"]), -len(r["missing"]), r["id"]))
    # 先补：按“这一项能让多少零件的多少项校验有结论”排
    weight: dict[tuple[str, str], list] = {}
    for r in rows:
        for g in r["missing"]:
            if g["checks"] or g["key"]:
                weight.setdefault((r["category"], g["field"]), []).append((r["id"], g))
    todo = []
    for (cat, field), items in weight.items():
        checks = _order(c for _, g in items for c in g["checks"])
        todo.append({"category": cat, "field": field, "components": [i for i, _ in items], "checks": checks,
                     "hint": items[0][1]["hint"], "score": sum(len(g["checks"]) or 0.5 for _, g in items)})
    todo.sort(key=lambda t: (-t["score"], t["category"], t["field"]))
    return {"count": len(rows), "complete": sum(r["complete"] for r in rows), "components": rows, "fill_first": todo[:20]}


def to_excel(rep: dict, path: str | Path) -> Path:
    """导出 Excel：总表（每个零件一行）、缺项（每个缺项一行）、先补（按收益排）"""
    from openpyxl import Workbook
    from openpyxl.styles import Font

    def names(checks):
        return "、".join(f"{c} {CHECK_NAMES.get(c, '')}" for c in checks)

    wb = Workbook()
    ws = wb.active
    ws.title = "零件"
    ws.append(["零件", "品类", "厂商", "型号", "缺项数", "缺了会待确认的校验", "完整"])
    for r in rep["components"]:
        ws.append([r["id"], r["category"], r["vendor"], r["model"], len(r["missing"]), names(r["checks_affected"]),
                   "是" if r["complete"] else "否"])
    ws2 = wb.create_sheet("缺项")
    ws2.append(["零件", "缺的字段", "关键参数", "缺了会待确认的校验", "去哪找"])
    for r in rep["components"]:
        for g in r["missing"]:
            ws2.append([r["id"], g["field"], "是" if g["key"] else "", names(g["checks"]) or "（不影响 C1–C11；入库复核要）",
                        g["hint"]])
    ws3 = wb.create_sheet("先补")
    ws3.append(["品类", "字段", "涉及零件数", "补上后有结论的校验", "去哪找", "零件"])
    for t in rep["fill_first"]:
        ws3.append([t["category"], t["field"], len(t["components"]), names(t["checks"]), t["hint"], "、".join(t["components"])])
    for sheet in (ws, ws2, ws3):
        for cell in sheet[1]:
            cell.font = Font(bold=True)
        for col in sheet.columns:
            sheet.column_dimensions[col[0].column_letter].width = min(60, max(10, *(len(str(c.value or "")) + 2 for c in col)))
        sheet.freeze_panes = "A2"
    path = Path(path)
    wb.save(path)
    return path
