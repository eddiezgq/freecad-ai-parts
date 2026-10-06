"""新建零件向导（M9 第四步，ADR-0055）：从规格书的抽取结果（逐项确认）加人工补录的值，按品类模板组装新零件，存入企业库。

- 组装沿用 ingest.assemble：端口 id、类型、方向取自品类 schema，坐标系按品类约定，包络由外形尺寸生成
- 值只来自两处：代码核对通过且经人勾选的抽取项；人工补录（须附企业资料、页码、原文与录入人）
- 组装不出（缺包络尺寸、端口类型判断不了、不合 schema）时列出缺项，不存
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping

from freecad_addon.core.fill import NAMES, UNIT_TEXT, FieldRow
from freecad_addon.core.spec_import import SpecImportError, confirmed_pv
from ingest.assemble import assemble, component_id, standard_ports
from ingest.llm_extract import CATEGORIES, targets

CATEGORY_NAMES = {"servo_motor": "伺服电机", "reducer": "减速器", "drive": "驱动器", "bearing": "轴承",
                  "adapter": "转接件"}
DIM_NAMES = {"overall_length_mm": "总长", "body_length_mm": "机身长度（不含轴伸）", "outer_diameter_mm": "外径",
             "square_mm": "方形边长", "width_mm": "宽", "height_mm": "高", "depth_mm": "深"}


def field_rows(category: str) -> list[FieldRow]:
    """品类的全部可填字段（含外形尺寸），关键字段在前；供人工补录。"""
    if category not in CATEGORIES:
        raise SpecImportError(f"不支持的品类：{category}")
    out = []
    for tgt, (t, _refs) in targets(category).items():
        name = tgt.rsplit("/", 1)[-1]
        if tgt.startswith("dims/"):
            label = "外形 · " + DIM_NAMES.get(name, name)
        elif tgt.startswith("ports/"):
            label = f"{tgt.split('/')[1]} · " + NAMES.get(name, name)
        else:
            label = NAMES.get(name, name)
        out.append(FieldRow(tgt, label, UNIT_TEXT.get(t.unit or "", t.unit or ""), t.kind, t.enum, t.key, "", False))
    return sorted(out, key=lambda r: (not r.key, not r.target.startswith("dims/"), r.target))


def values(extraction: Mapping | None, chosen: Iterable[str], manual: Mapping[str, dict], actor: str,
           today: str | None = None) -> dict:
    """target → 参数值：勾选的抽取项（记确认人）+ 人工补录的值（人工值优先）。"""
    out: dict = {}
    items = {i["target"]: i for i in (extraction or {}).get("items", [])}
    chosen = set(chosen)
    unknown = chosen - set(items)
    if unknown:
        raise SpecImportError(f"这些字段不在核对通过的抽取结果中：{'、'.join(sorted(unknown))}")
    for tgt in sorted(chosen):
        out[tgt] = confirmed_pv(items[tgt], actor, today)
    out.update(manual)
    return out


OPEN_PORT_REASON = "厂商目录不规定，按配套件定制（企业新建零件时注明）"


def draft(category: str, vendor: str, model: str, vals: Mapping[str, dict], *,
          open_ports: bool = False) -> tuple[dict | None, list[str], list[str]]:
    """按品类模板组装；返回（零件或 None, 缺项与错误, 提示）。

    open_ports：规格书没给规格的标准端口按“配套件定制”输出（ADR-0045），如谐波减速器的电机法兰。"""
    vendor, model = vendor.strip(), model.strip()
    if not vendor or not model:
        return None, ["请填写厂商与型号"], []
    note = "企业新建零件：参数取自企业资料（见各值来源）；端口坐标系按品类约定生成，布局时核对"
    configurable = None
    if open_ports:
        given = {t.split("/")[1] for t in vals if t.startswith("ports/")}
        configurable = {p.id: OPEN_PORT_REASON for p in standard_ports(category) if p.id not in given}
    return assemble(category, vendor, model, dict(vals), note=note, configurable=configurable)


def new_id(category: str, vendor: str, model: str) -> str:
    return component_id(category, vendor.strip(), model.strip())


def save(enterprise, comp: dict, actor: str, base: Callable[[str], dict | None], *, overwrite: bool = False) -> None:
    """存入企业库。公共库已有同 id 的零件时不新建（应在那个零件上导入规格书补数据）。"""
    if enterprise is None:
        raise SpecImportError("还没有企业库：请先选择企业库文件夹")
    if base(comp["id"]) is not None:
        raise SpecImportError(f"公共库已有 {comp['id']}，请在这个零件上用“导入规格书”或“补数据”")
    if enterprise.get(comp["id"]) is not None and not overwrite:
        raise SpecImportError(f"企业库已有 {comp['id']}；确认要覆盖时再保存")
    enterprise.save_component(comp, actor, f"新建零件 {comp['vendor']} {comp['model']}")
