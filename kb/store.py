"""组件的导入、读取与导出（ADR-0018）。

导入入口依次把关：schema 校验 → 虚构组件拦截 → 来源许可 → 端口 id 唯一；
更新已有组件时必须给出原因，每项变更写入 change_log。
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from kb.db import require_autocommit
from kb.sources import SourceRegistry
from kb.validation import errors as schema_errors

TOP_FIELDS = ["series", "status", "superseded_by", "license", "envelope", "vendor_cad_url", "note",
              "category", "vendor", "model"]


class ImportRejected(Exception):
    """组件未通过入库把关。reasons 列出全部原因。"""

    def __init__(self, component_id: str, reasons: list[str]):
        self.component_id = component_id
        self.reasons = reasons
        super().__init__(f"{component_id} 被拒绝入库：" + "；".join(reasons))


def _source_docs(node: Any) -> set[str]:
    """收集参数值对象中引用的全部来源文档 id。"""
    found: set[str] = set()
    if isinstance(node, dict):
        src = node.get("source")
        if isinstance(src, dict) and isinstance(src.get("doc"), str):
            found.add(src["doc"])
        for value in node.values():
            found |= _source_docs(value)
    elif isinstance(node, list):
        for item in node:
            found |= _source_docs(item)
    return found


def _bad_values(node: Any, path: str = "") -> list[str]:
    """数据库无法存储的值：非有限数（NaN、Infinity）与 NUL 字符。"""
    found: list[str] = []
    if isinstance(node, float) and not math.isfinite(node):
        found.append(f"{path or '<root>'} 不是有限数值")
    elif isinstance(node, str) and "\x00" in node:
        found.append(f"{path or '<root>'} 含 NUL 字符")
    elif isinstance(node, dict):
        for k, v in node.items():
            if isinstance(k, str) and "\x00" in k:
                found.append(f"{path}/{k!r} 键名含 NUL 字符")
            found += _bad_values(v, f"{path}/{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            found += _bad_values(v, f"{path}/{i}")
    return found


def check_component(comp: Any, registry: SourceRegistry, *, allow_test: bool = False) -> list[str]:
    """返回拒绝入库的全部原因；可以入库时返回空列表。schema 不通过时只返回 schema 原因。"""
    if not isinstance(comp, dict):
        return ["组件必须是 JSON 对象"]
    reasons = [f"schema：{e}" for e in schema_errors("component.schema.json", comp)]
    reasons += [f"数值：{e}" for e in _bad_values(comp)]
    if reasons:
        return reasons
    cid = comp["id"]
    if cid.startswith("test.") and not allow_test:
        reasons.append("虚构测试组件（test.）不得进入正式库")
    for doc in sorted(_source_docs(comp)):
        why = registry.check_document(doc, vendor=comp["vendor"], allow_test=allow_test)
        if why:
            reasons.append(why)
    port_ids = [p["id"] for p in comp["ports"]]
    duplicates = sorted({p for p in port_ids if port_ids.count(p) > 1})
    if duplicates:
        reasons.append(f"端口 id 重复：{', '.join(map(str, duplicates))}")
    return reasons


def _num(x: Any) -> float | None:
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def _insert_children(cur: psycopg.Cursor, comp: dict) -> None:
    cid = comp["id"]
    for name, pv in comp["params"].items():
        src = pv.get("source", {})
        cur.execute(
            "INSERT INTO params (component_id, name, value, value_num, min_num, max_num, nominal_num,"
            " method, confidence, reviewed, source_doc) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (cid, name, Jsonb(pv), _num(pv.get("value")), _num(pv.get("min")), _num(pv.get("max")),
             _num(pv.get("nominal")), pv["method"], pv["confidence"], pv["reviewed"], src.get("doc")),
        )
    for pos, port in enumerate(comp["ports"]):
        frame = port.get("frame")
        cur.execute(
            "INSERT INTO ports (component_id, port_id, pos, type, dir, motion, frame, spec, note)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (cid, port["id"], pos, port["type"], port["dir"], port.get("motion"),
             Jsonb(frame) if frame is not None else None, Jsonb(port["spec"]), port.get("note")),
        )


def _log(cur: psycopg.Cursor, cid: str, scope: str, name: str, old: Any, new: Any,
         reason: str, changed_by: str) -> None:
    cur.execute(
        "INSERT INTO change_log (component_id, scope, name, old_value, new_value, reason, changed_by)"
        " VALUES (%s,%s,%s,%s,%s,%s,%s)",
        (cid, scope, name, None if old is None else Jsonb(old), None if new is None else Jsonb(new),
         reason, changed_by),
    )


def _diff(old: dict, new: dict) -> list[tuple[str, str, Any, Any]]:
    changes = []
    for f in TOP_FIELDS:
        if old.get(f) != new.get(f):
            changes.append(("component", f, old.get(f), new.get(f)))
    for name in sorted(set(old["params"]) | set(new["params"])):
        a, b = old["params"].get(name), new["params"].get(name)
        if a != b:
            changes.append(("param", name, a, b))
    old_ports = {p["id"]: p for p in old["ports"]}
    new_ports = {p["id"]: p for p in new["ports"]}
    for pid in sorted(set(old_ports) | set(new_ports)):
        a, b = old_ports.get(pid), new_ports.get(pid)
        if a != b:
            changes.append(("port", pid, a, b))
    if [p["id"] for p in old["ports"]] != [p["id"] for p in new["ports"]]:
        changes.append(("component", "port_order", [p["id"] for p in old["ports"]],
                        [p["id"] for p in new["ports"]]))
    return changes


def import_component(
    conn: psycopg.Connection,
    comp: dict,
    *,
    registry: SourceRegistry,
    changed_by: str,
    reason: str | None = None,
    allow_test: bool = False,
) -> dict:
    """导入一个组件。新建、更新或无变化；changed_by 必填，更新时 reason 必填。

    同一组件的并发写入用 advisory lock 串行化，保证 change_log 的原值准确。
    """
    require_autocommit(conn)
    if not (changed_by or "").strip():
        raise ValueError("必须给出变更人 changed_by")
    reasons = check_component(comp, registry, allow_test=allow_test)
    if reasons:
        cid = comp.get("id") if isinstance(comp, dict) else None
        raise ImportRejected(str(cid), reasons)
    cid = comp["id"]
    with conn.transaction(), conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (cid,))
        old = get_component(conn, cid)
        if old == comp:
            return {"id": cid, "status": "unchanged", "changes": 0}
        if old is not None and not (reason or "").strip():
            raise ValueError(f"更新已有组件 {cid} 必须给出原因")
        row = (comp["category"], comp["vendor"], comp["model"], comp.get("series"), comp["status"],
               comp.get("superseded_by"), comp["license"], Jsonb(comp["envelope"]),
               comp.get("vendor_cad_url"), comp.get("note"))
        if old is None:
            cur.execute(
                "INSERT INTO components (id, category, vendor, model, series, status, superseded_by,"
                " license, envelope, vendor_cad_url, note) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (cid, *row),
            )
            _insert_children(cur, comp)
            _log(cur, cid, "component", "created", None, comp, (reason or "").strip() or "初次导入",
                 changed_by)
            return {"id": cid, "status": "created", "changes": 1}
        changes = _diff(old, comp)
        cur.execute(
            "UPDATE components SET category=%s, vendor=%s, model=%s, series=%s, status=%s,"
            " superseded_by=%s, license=%s, envelope=%s, vendor_cad_url=%s, note=%s, updated_at=now()"
            " WHERE id=%s",
            (*row, cid),
        )
        cur.execute("DELETE FROM params WHERE component_id=%s", (cid,))
        cur.execute("DELETE FROM ports WHERE component_id=%s", (cid,))
        _insert_children(cur, comp)
        for scope, name, a, b in changes:
            _log(cur, cid, scope, name, a, b, reason, changed_by)
        return {"id": cid, "status": "updated", "changes": len(changes)}


def get_component(conn: psycopg.Connection, cid: str) -> dict | None:
    """按 id 读取组件，返回与 component.schema.json 一致的字典；不存在时返回 None。"""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, category, vendor, model, series, status, superseded_by, license, envelope,"
            " vendor_cad_url, note FROM components WHERE id=%s",
            (cid,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        (id_, category, vendor, model, series, status, superseded_by, license_, envelope,
         cad_url, note) = row
        comp: dict[str, Any] = {"id": id_, "category": category, "vendor": vendor, "model": model}
        if series is not None:
            comp["series"] = series
        comp["status"] = status
        if superseded_by is not None:
            comp["superseded_by"] = superseded_by
        comp["license"] = license_
        cur.execute("SELECT name, value FROM params WHERE component_id=%s ORDER BY name", (cid,))
        comp["params"] = {name: value for name, value in cur.fetchall()}
        cur.execute(
            "SELECT port_id, type, dir, motion, frame, spec, note FROM ports"
            " WHERE component_id=%s ORDER BY pos",
            (cid,),
        )
        ports = []
        for port_id, type_, dir_, motion, frame, spec, pnote in cur.fetchall():
            port: dict[str, Any] = {"id": port_id, "type": type_, "dir": dir_}
            if motion is not None:
                port["motion"] = motion
            if frame is not None:
                port["frame"] = frame
            port["spec"] = spec
            if pnote is not None:
                port["note"] = pnote
            ports.append(port)
        comp["ports"] = ports
        comp["envelope"] = envelope
        if cad_url is not None:
            comp["vendor_cad_url"] = cad_url
        if note is not None:
            comp["note"] = note
        return comp


def list_components(conn: psycopg.Connection, category: str | None = None) -> list[str]:
    """列出组件 id，可按品类筛选。"""
    with conn.cursor() as cur:
        if category:
            cur.execute("SELECT id FROM components WHERE category=%s ORDER BY id", (category,))
        else:
            cur.execute("SELECT id FROM components ORDER BY id")
        return [r[0] for r in cur.fetchall()]


def change_log(conn: psycopg.Connection, cid: str) -> list[dict]:
    """组件的变更记录，按时间先后。"""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT scope, name, old_value, new_value, reason, changed_by FROM change_log"
            " WHERE component_id=%s ORDER BY id",
            (cid,),
        )
        keys = ("scope", "name", "old_value", "new_value", "reason", "changed_by")
        return [dict(zip(keys, r, strict=True)) for r in cur.fetchall()]


def export_snapshot(conn: psycopg.Connection, out_dir: Path, *, prune: bool = False) -> list[Path]:
    """把全部组件写成 <品类>/<组件 id>.json，返回写出的文件。

    键按字母排序，保证同一内容每次导出逐字节相同、版本差异只反映真实变化。
    prune=True 时删除 out_dir 下其他 *.json（已删除或改了品类的组件留下的旧文件）。
    """
    out_dir = Path(out_dir)
    written = []
    for cid in list_components(conn):
        comp = get_component(conn, cid)
        path = out_dir / comp["category"] / f"{cid}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(comp, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        path.write_text(text, encoding="utf-8")
        written.append(path)
    if prune:
        keep = {p.resolve() for p in written}
        for stale in out_dir.glob("*/*.json"):
            if stale.resolve() not in keep:
                stale.unlink()
    return written
