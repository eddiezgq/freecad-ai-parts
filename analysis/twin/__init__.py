"""数字孪生 · 预测性维护（ADR-0057，M10 第五步）：按 BOM 中零件的样本参数与运行记录，算每个零件已用掉的寿命、
剩余寿命、报警；“假如”负载、转速变了，寿命怎么变。纯 Python，不需要求解器；只用零件库里有出处的参数，缺的为待确认。

设置：
  parts: [{"instance": "reducer", "component": {完整组件}}]（可由 parts_from_system(系统, 取组件) 生成）
  records: [{"instance", "hours", "output_torque_avg_nm", "output_torque_max_nm", "output_speed_rpm" 或 "input_speed_rpm"}（减速器）,
            {"instance", "hours", "radial_load_n", "speed_rpm"}（轴承：当量动载荷与转速）]，可由 read_csv(路径) 读入
  recent_records: 估算剩余寿命用的最近记录条数（缺省 30）
  whatif: {"load_factor": 0.8, "speed_factor": 1.0}（可选）

模型：
  减速器：L = L_r·(T_r/T_av)³·(n_r/n_in)（厂商样本的寿命式；记录有输入转速时直接用，否则 n_in = 输出转速 × 减速比），变工况 Σ 小时 / Lᵢ
  轴承：ISO 281 L10 = (C/P)^p × 10⁶ 转，球轴承 p = 3、滚子轴承 p = 10/3
  过载：最大扭矩超过启停允许峰值扭矩报警，超过瞬间最大扭矩为严重
"""

from __future__ import annotations

import csv
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path

from analysis.common import result

MODULE = {
    "id": "twin", "name": "数字孪生 · 预测性维护", "version": "1",
    "description": "按零件样本参数与运行记录算已用寿命、剩余寿命与报警，可做“假如”分析",
    "python": [], "solvers": [], "install": "",
}
LIMITS = ["寿命为厂商样本寿命式与 ISO 281 基本额定寿命（L10，90% 可靠度），未计润滑、污染修正",
          "运行记录中的扭矩、载荷为每段的平均值；段内的波动按平均值的三次方计入会偏乐观",
          "剩余寿命按最近记录的消耗速度外推"]
WARN, SEVERE = 0.8, 1.0
CSV_FIELDS = ("instance", "hours", "output_torque_avg_nm", "output_torque_max_nm", "output_speed_rpm", "input_speed_rpm",
              "radial_load_n", "speed_rpm")


def _v(comp: Mapping, name: str) -> float | None:
    pv = (comp.get("params") or {}).get(name)
    if not isinstance(pv, Mapping):
        return None
    for k in ("value", "nominal", "min"):
        if isinstance(pv.get(k), (int, float)) and not isinstance(pv.get(k), bool):
            return float(pv[k])
    return None


def parts_from_system(system: Mapping, resolve: Callable[[str], dict | None]) -> list[dict]:
    """系统（或 BOM 的实例表）→ 孪生的零件：只取减速器与轴承（有寿命模型的品类）。"""
    out = []
    for item in system.get("components", []):
        comp = resolve(item["component"])
        if comp and comp["category"] in ("reducer", "bearing"):
            out.append({"instance": item["instance"], "component": comp})
    return out


def read_csv(path: str | Path) -> list[dict]:
    """运行记录 CSV：表头为 CSV_FIELDS 中的列（可缺），每行一段运行。空格为缺。"""
    rows = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for raw in csv.DictReader(f):
            row: dict = {"instance": (raw.get("instance") or "").strip()}
            for k in CSV_FIELDS[1:]:
                text = (raw.get(k) or "").strip()
                if text:
                    row[k] = float(text)
            if row["instance"] and row.get("hours"):
                rows.append(row)
    return rows


def reducer_life_h(comp: Mapping, torque_nm: float, out_speed_rpm: float, *,
                   in_speed_rpm: float | None = None) -> float | None:
    """厂商样本的寿命式；缺参数时为 None。给了输入转速（如工厂现场记录）就直接用，否则由输出转速 × 减速比得到。"""
    lr, tr, nr, ratio = (_v(comp, k) for k in ("rated_life_h", "rated_torque_nm", "rated_input_speed_rpm", "ratio"))
    if None in (lr, tr, nr, ratio) or torque_nm <= 0:
        return None
    n_in = in_speed_rpm if in_speed_rpm is not None else out_speed_rpm * ratio
    if n_in <= 0:
        return None
    return lr * (tr / torque_nm) ** 3 * (nr / n_in)


def bearing_life_h(comp: Mapping, load_n: float, speed_rpm: float) -> float | None:
    c = _v(comp, "dynamic_load_rating_n")
    if c is None or load_n <= 0 or speed_rpm <= 0:
        return None
    kind = ((comp.get("params") or {}).get("bearing_kind") or {}).get("value", "")
    p = 10 / 3 if "roller" in str(kind) else 3.0
    return (c / load_n) ** p * 1e6 / (60 * speed_rpm)


def _missing(comp: Mapping) -> list[str]:
    need = ("rated_life_h", "rated_torque_nm", "rated_input_speed_rpm", "ratio") if comp["category"] == "reducer" else (
        "dynamic_load_rating_n",)
    return [k for k in need if _v(comp, k) is None]


def assess(part: Mapping, records: Iterable[Mapping], *, load_factor: float = 1.0, speed_factor: float = 1.0,
           recent: int = 30) -> dict:
    comp, inst = part["component"], part["instance"]
    recs = [r for r in records if r.get("instance") == inst and r.get("hours", 0) > 0]
    out = {"instance": inst, "component": comp["id"], "model": f"{comp.get('vendor', '')} {comp.get('model', '')}".strip(),
           "category": comp["category"], "hours": sum(r["hours"] for r in recs), "alerts": []}
    missing = _missing(comp)
    if missing:
        return {**out, "status": "unknown", "missing": missing,
                "note": "缺样本参数：" + "、".join(missing) + "（可用“补数据”或“导入规格书”补）"}
    damages = []
    for r in recs:
        if comp["category"] == "reducer":
            t = r.get("output_torque_avg_nm", 0) * load_factor
            n_in_rec = r.get("input_speed_rpm")
            n_in_rec = None if n_in_rec is None else n_in_rec * speed_factor
            life = reducer_life_h(comp, t, r.get("output_speed_rpm", 0) * speed_factor, in_speed_rpm=n_in_rec)
            tmax = r.get("output_torque_max_nm", 0) * load_factor
            rep, mom = _v(comp, "repeated_peak_torque_nm"), _v(comp, "momentary_max_torque_nm")
            if mom is not None and tmax > mom:
                out["alerts"].append({"level": "severe", "text": f"最大扭矩 {tmax:g} N·m 超过瞬间最大扭矩 {mom:g} N·m"})
            elif rep is not None and tmax > rep:
                out["alerts"].append({"level": "warn", "text": f"最大扭矩 {tmax:g} N·m 超过启停允许峰值扭矩 {rep:g} N·m"})
            lim = _v(comp, "avg_input_speed_limit_rpm")
            n_in = n_in_rec if n_in_rec is not None else r.get("output_speed_rpm", 0) * speed_factor * (_v(comp, "ratio") or 0)
            if lim is not None and n_in > lim:
                out["alerts"].append({"level": "warn", "text": f"平均输入转速 {n_in:g} rpm 超过限值 {lim:g} rpm"})
        else:
            life = bearing_life_h(comp, r.get("radial_load_n", 0) * load_factor, r.get("speed_rpm", 0) * speed_factor)
        damages.append((r["hours"], 0.0 if life is None else r["hours"] / life))
    used = sum(d for _, d in damages)
    tail = damages[-recent:]
    rate = sum(d for _, d in tail) / max(sum(h for h, _ in tail), 1e-12)  # 每运行小时用掉的比例
    remaining = None if rate <= 0 else max(0.0, 1 - used) / rate
    status = "severe" if used >= SEVERE else "warn" if used >= WARN else "ok"
    if used >= WARN:
        out["alerts"].append({"level": status, "text": f"已用掉 {used:.0%} 的额定寿命"})
    if any(a["level"] == "severe" for a in out["alerts"]):
        status = "severe"
    elif out["alerts"] and status == "ok":
        status = "warn"
    # 去重报警（同一句话只报一次）
    seen, alerts = set(), []
    for a in out["alerts"]:
        if a["text"] not in seen:
            seen.add(a["text"])
            alerts.append(a)
    out["alerts"] = alerts
    return {**out, "status": status, "used_ratio": used, "rate_per_hour": rate, "remaining_h": remaining,
            "life_at_recent_rate_h": None if rate <= 0 else 1 / rate}


def run(setup: dict) -> dict:
    parts = setup.get("parts") or []
    records = setup.get("records") or []
    if not parts:
        return result.failed("twin", MODULE["version"], setup, "没有可建孪生的零件（减速器或轴承）")
    if not isinstance(records, list):
        return result.failed("twin", MODULE["version"], setup, "records 须为列表")
    wi = setup.get("whatif") or {}
    lf, sf = float(wi.get("load_factor", 1.0)), float(wi.get("speed_factor", 1.0))
    if lf <= 0 or sf <= 0:
        return result.failed("twin", MODULE["version"], setup, "假如的负载、转速倍数须大于 0")
    recent = int(setup.get("recent_records", 30))
    now = [assess(p, records, recent=recent) for p in parts]
    data: dict = {"parts": now}
    if wi:
        data["whatif"] = {"load_factor": lf, "speed_factor": sf,
                          "parts": [assess(p, records, load_factor=lf, speed_factor=sf, recent=recent) for p in parts]}
    rank = {"severe": 0, "warn": 1, "unknown": 2, "ok": 3}
    first = sorted((p for p in now if p.get("remaining_h") is not None), key=lambda p: p["remaining_h"])
    data["first_due"] = first[0]["instance"] if first else None
    data["overall"] = min((p["status"] for p in now), key=lambda s: rank[s])
    # 输出里不重复整份组件数据：只留 id
    slim = {**setup, "parts": [{"instance": p["instance"], "component": p["component"]["id"]} for p in parts]}
    return result.make("twin", MODULE["version"], slim, data, limitations=LIMITS)
