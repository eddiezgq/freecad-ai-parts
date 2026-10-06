"""就地补数据（M9 第二步，ADR-0055 第 4 条）：列出组件可补的字段，把用户填的值与依据组成参数值。纯函数。

- 字段取自品类 schema（与抽取同一份目标表 ingest.llm_extract.targets），缺的关键字段排在最前
- 值按字段的标准单位填写（字段名后缀即单位），不在这里换算
- 依据必填：企业资料、页码、原文、录入人；写入与校验由 kb.enterprise 完成
"""

from __future__ import annotations

import datetime
from collections.abc import Mapping
from dataclasses import dataclass

from ingest.llm_extract import targets

NAMES = {
    "accepted_diameter_range_mm": "可接受轴径范围", "avg_input_speed_limit_rpm": "平均输入转速上限",
    "backlash_arcmin": "回差", "bearing_kind": "轴承类型", "brake": "制动器", "brake_voltage_v": "制动器电压",
    "clamping": "紧固方式", "connector": "接插件", "current_type": "电流类型", "depth_mm": "孔深",
    "diameter_mm": "直径", "din_rail": "导轨安装", "dynamic_load_rating_n": "额定动载荷", "efficiency_ratio": "效率",
    "face_size_mm": "安装面外形", "feature": "形式（光轴/键/扁/花键）", "fit": "公差带", "fit_system": "公差体系",
    "frequency_hz": "频率", "hole_angle_offset_deg": "孔位角度偏置", "hole_count": "孔数", "hole_diameter_mm": "通孔直径",
    "hole_kind": "孔的形式", "input_inertia_kgm2": "输入惯量", "ip_rating": "防护等级", "key_width_mm": "键宽",
    "kind": "类型", "limiting_speed_rpm": "极限转速", "lost_motion_arcmin": "空程", "mass_kg": "质量",
    "max_axial_load_n": "最大轴向载荷", "max_input_speed_rpm": "最高输入转速", "max_radial_load_n": "最大径向载荷",
    "max_speed_rpm": "最高转速", "moment_load_rating_nm": "许用倾覆力矩", "momentary_max_torque_nm": "瞬间最大扭矩",
    "multi_turn": "多圈", "output_bearing_dynamic_load_rating_n": "输出轴承额定动载荷",
    "output_bearing_moment_load_rating_nm": "输出轴承许用倾覆力矩", "pattern": "孔位形式", "pcd_mm": "分度圆直径",
    "peak_current_a": "峰值电流", "peak_torque_nm": "峰值扭矩", "phases": "相数", "pilot_diameter_mm": "止口直径",
    "pilot_fit": "止口公差带", "pilot_kind": "止口形式（凸/凹）", "pitch_x_mm": "孔距 x", "pitch_y_mm": "孔距 y",
    "profile": "规格", "protocol": "协议", "rated_current_a": "额定电流", "rated_output_power_w": "额定输出功率",
    "rated_power_w": "额定功率", "rated_speed_rpm": "额定转速", "rated_torque_nm": "额定扭矩", "ratio": "减速比",
    "reducer_kind": "减速器类型", "repeated_peak_torque_nm": "启停允许峰值扭矩", "resolution_bits": "分辨率（位）",
    "rotor_inertia_kgm2": "转子惯量", "safety_functions": "安全功能", "seal": "密封", "square_size_mm": "方形法兰边长",
    "static_load_rating_n": "额定静载荷", "thread": "螺纹", "torque_constant_nm_per_a": "转矩常数",
    "torsional_stiffness_nm_per_arcmin": "扭转刚度", "usable_length_mm": "可用长度", "vendor": "厂商",
    "voltage_class_v": "电压等级", "voltage_v": "电压", "width_mm": "宽度",
}
UNIT_TEXT = {"N*m": "N·m", "kg*m**2": "kg·m²", "N*m/arcmin": "N·m/arcmin", "degree": "°", "dimensionless": "0–1 小数"}


@dataclass(frozen=True)
class FieldRow:
    target: str
    label: str
    unit: str
    kind: str
    enum: tuple | None
    key: bool
    current: str  # 当前值的文字；缺时为空
    configurable_port: bool  # 端口标了“按配套件定制”

    @property
    def missing(self) -> bool:
        return self.current == ""

    def title(self) -> str:
        mark = "缺 · " if self.missing else ""
        star = "★" if self.key else ""
        unit = f"（{self.unit}）" if self.unit else ""
        return f"{mark}{star}{self.label}{unit}"


def _holder(comp: Mapping, target: str) -> tuple[Mapping | None, Mapping | None]:
    parts = target.split("/")
    if parts[0] == "params":
        return comp.get("params") or {}, None
    port = next((p for p in comp.get("ports", []) if p["id"] == parts[1]), None)
    return (port or {}).get("spec") or {}, port


def value_text(pv: Mapping | None) -> str:
    if not isinstance(pv, Mapping):
        return ""
    if pv.get("value") is not None:
        v = pv["value"]
        return ", ".join(map(str, v)) if isinstance(v, list) else (f"{v:g}" if isinstance(v, float) else str(v))
    if pv.get("nominal") is not None:
        return f"{pv['nominal']:g}（{pv.get('tol_upper', 0):+g} / {pv.get('tol_lower', 0):+g}）"
    if pv.get("min") is not None or pv.get("max") is not None:
        return f"{pv.get('min', '')}–{pv.get('max', '')}"
    return ""


def fields(comp: Mapping, focus_ports: frozenset[str] | set[str] = frozenset()) -> list[FieldRow]:
    """组件可补的字段：校验待确认所涉端口的字段（focus_ports）→ 缺的关键字段 → 缺的其他字段 → 已有的字段。"""
    rows = []
    params = comp.get("params") or {}
    for target, (t, _refs) in targets(comp["category"]).items():
        if not target.startswith(("params/", "ports/")):
            continue  # 外形尺寸改包络，不在这里补
        if target == "params/efficiency_ratio" and "efficiency_curve" in params:
            continue  # 有效率曲线时不需要单值效率（ADR-0047）
        holder, port = _holder(comp, target)
        if holder is None:
            continue
        name = target.rsplit("/", 1)[-1]
        where = "" if target.startswith("params/") else f"{target.split('/')[1]} · "
        rows.append(FieldRow(target, where + NAMES.get(name, name), UNIT_TEXT.get(t.unit or "", t.unit or ""), t.kind,
                             t.enum, t.key, value_text(holder.get(name)), bool((port or {}).get("configurable"))))
    def in_focus(r: FieldRow) -> bool:
        return r.target.startswith("ports/") and r.target.split("/")[1] in focus_ports

    return sorted(rows, key=lambda r: (not r.missing, not in_focus(r), not r.key, r.target))


def build_pv(row: FieldRow, value: str, *, doc: str, page: int | None, quote: str, actor: str,
             tol_upper: str = "", tol_lower: str = "", condition: str = "", today: str | None = None) -> dict:
    """由表单文字组成参数值；不合格时抛 ValueError（说明原因）。依据（资料、页码、原文、录入人）必填。"""
    value, quote, actor = value.strip(), quote.strip(), actor.strip()
    if not value:
        raise ValueError("请填写值")
    if not doc or page is None or page < 1 or not quote or not actor:
        raise ValueError("请写明资料、页码、原文与录入人")
    pv: dict = {}
    if row.kind in ("number", "integer", "number_pair"):
        try:
            num = int(value) if row.kind == "integer" else float(value)
        except ValueError as exc:
            raise ValueError(f"{row.label} 须为{'整数' if row.kind == 'integer' else '数字'}") from exc
        if tol_upper.strip() or tol_lower.strip():
            if row.kind == "integer":
                raise ValueError("整数字段不能写公差")
            try:
                hi, lo = float(tol_upper or 0), float(tol_lower or 0)
            except ValueError as exc:
                raise ValueError("上下偏差须为数字") from exc
            if lo > hi:
                raise ValueError("下偏差不能大于上偏差")
            pv.update({"nominal": float(num), "tol_upper": hi, "tol_lower": lo})
        else:
            pv["value"] = num
    else:
        if tol_upper.strip() or tol_lower.strip():
            raise ValueError("文字字段不能写公差")
        if row.enum and value not in row.enum:
            raise ValueError(f"{row.label} 只能是：{'、'.join(map(str, row.enum))}")
        pv["value"] = value
    if condition.strip():
        pv["condition"] = condition.strip()
    day = today or datetime.datetime.now().astimezone().date().isoformat()
    pv.update({"source": {"doc": doc, "page": int(page), "note": f"原文“{quote}”；录入人：{actor}（{day}）"},
               "method": "manual", "confidence": 1, "reviewed": True})
    return pv
