"""录制会话的查看、导出与重放（ADR-0042，issue #148）。

    python -m freecad_addon.sessions list                     # 列出会话
    python -m freecad_addon.sessions show <会话>               # 一次会话的摘要
    python -m freecad_addon.sessions export out.jsonl [--rated-only]   # 导出数据集（每行一个会话）
    <FreeCAD 的 python> -m freecad_addon.sessions replay <会话> [--save out.FCStd]   # 在新文档中重建对象

会话目录缺省为 FAP_SESSIONS_DIR 或 ~/.freecad-ai-parts/sessions/；<会话> 可写目录名或路径。
list、show、export 不需要 FreeCAD；replay 需要。

重放只重建参数化对象（类型、属性、位置）；形体数据不录，AI 布局里的零件可用会话中记下的工具调用重新生成。
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import sys
from collections import Counter
from pathlib import Path

from freecad_addon.core.session_log import DEFAULT_ROOT, RecorderError, read_session

DATASET_FORMAT = "session-dataset/1"


def sessions_root() -> Path:
    return Path(os.environ.get("FAP_SESSIONS_DIR") or DEFAULT_ROOT)


def resolve(name: str, root: Path | None = None) -> Path:
    p = Path(name)
    if p.is_dir():
        return p
    p = (root or sessions_root()) / name
    if not p.is_dir():
        raise RecorderError(f"找不到会话 {name}")
    return p


def list_sessions(root: Path | None = None) -> list[dict]:
    out = []
    for d in sorted((root or sessions_root()).glob("*/meta.json")):
        try:
            s = read_session(d.parent)
        except (RecorderError, ValueError, OSError):
            continue
        o = s["outcome"] or {}
        out.append({"session": d.parent.name, "started_at": s["meta"].get("started_at"),
                    "events": len(s["events"]), "rating": o.get("rating"), "video": o.get("video"),
                    "finished": s["outcome"] is not None})
    return out


def summarize(session: dict) -> dict:
    ev = session["events"]
    changes = [e for e in ev if e["kind"] == "doc_change"]
    return {
        "started_at": session["meta"].get("started_at"),
        "ended_at": session["meta"].get("ended_at"),
        "events": dict(Counter(e["kind"] for e in ev)),
        "changes_by_origin": dict(Counter(e.get("origin") for e in changes)),
        "objects": sorted({e["object"] for e in changes}),
        "commands": [e["name"] for e in ev if e["kind"] == "command"],
        "tool_calls": [e.get("name") for e in ev if e["kind"] == "chat" and e.get("role") == "tool_call"],
        "outcome": session["outcome"],
    }


def to_record(name: str, session: dict) -> dict:
    """一次会话 → 数据集的一行：需求、对话、操作序列、结果与评价（ADR-0042 第 4 条）。"""
    ev = session["events"]
    chat = [{k: e[k] for k in ("t", "role", "text", "name", "data", "is_error") if k in e}
            for e in ev if e["kind"] == "chat"]
    first_user = next((c.get("text", "") for c in chat if c["role"] == "user"), "")
    actions = [{k: e[k] for k in ("t", "op", "doc", "object", "type", "property", "value", "origin") if k in e}
               for e in ev if e["kind"] == "doc_change"]
    o = session["outcome"] or {}
    return {
        "format": DATASET_FORMAT, "session": name, "started_at": session["meta"].get("started_at"),
        "request": first_user, "conversation": chat, "actions": actions,
        "commands": [{"t": e["t"], "name": e["name"]} for e in ev if e["kind"] == "command"],
        "snapshots": [e["file"] for e in ev if e["kind"] == "snapshot"],
        "rating": o.get("rating"), "note": o.get("note", ""), "results": o.get("last_results", {}),
        "user_edits_after_ai": _user_edits_after_ai(actions),
    }


def _user_edits_after_ai(actions: list[dict]) -> list[dict]:
    """AI 改过之后又被用户改的属性：最有价值的学习信号（用户纠正了 AI）。"""
    touched_by_ai = set()
    out = []
    for a in actions:
        key = (a.get("doc"), a.get("object"), a.get("property"))
        if a.get("origin") == "ai":
            touched_by_ai.add(key)
            touched_by_ai.add(key[:2] + (None,))
        elif a.get("op") == "changed" and (key in touched_by_ai or key[:2] + (None,) in touched_by_ai):
            out.append({"object": a["object"], "property": a.get("property"), "value": a.get("value"), "t": a["t"]})
    return out


def export(out: Path, *, root: Path | None = None, rated_only: bool = False) -> int:
    rows = []
    for item in list_sessions(root):
        if not item["finished"] or (rated_only and item["rating"] is None):
            continue
        name = item["session"]
        rows.append(to_record(name, read_session((root or sessions_root()) / name)))
    Path(out).write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows),
                         encoding="utf-8")
    return len(rows)


# ---------------------------------------------------------------- 重放


def parse_value(value):
    """录下的简短表示 → 可赋给 FreeCAD 属性的值；解析不了时原样返回字符串。"""
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str):
        return value
    try:
        return ast.literal_eval(value)
    except (ValueError, SyntaxError):
        return value


def plan_replay(events: list[dict], doc: str | None = None) -> list[dict]:
    """按顺序整理出重放步骤：只取一个文档；只重放会话中新建的对象；删除后不再改。纯函数。"""
    changes = [e for e in events if e["kind"] == "doc_change" and (doc is None or e["doc"] == doc)]
    if doc is None and changes:
        doc = Counter(e["doc"] for e in changes).most_common(1)[0][0]
        changes = [e for e in changes if e["doc"] == doc]
    live: set[str] = set()
    steps = []
    for e in changes:
        obj = e["object"]
        if e["op"] == "created" and e.get("type"):
            live.add(obj)
            steps.append({"op": "create", "object": obj, "type": e["type"], "origin": e.get("origin")})
        elif e["op"] == "changed" and obj in live:
            steps.append({"op": "set", "object": obj, "property": e["property"], "value": parse_value(e["value"]),
                          "origin": e.get("origin")})
        elif e["op"] == "deleted" and obj in live:
            live.discard(obj)
            steps.append({"op": "delete", "object": obj, "origin": e.get("origin")})
    return steps


def apply_replay(steps: list[dict], doc_name: str = "FapReplay") -> tuple[object, dict]:
    """在 FreeCAD 新文档中执行重放步骤；返回（文档, 统计）。只能在 FreeCAD 的 Python 中调用。"""
    import FreeCAD

    doc = FreeCAD.newDocument(doc_name)
    names: dict[str, str] = {}
    stats = Counter()
    for s in steps:
        try:
            if s["op"] == "create":
                obj = doc.addObject(s["type"], s["object"])
                names[s["object"]] = obj.Name
            elif s["op"] == "delete":
                doc.removeObject(names.pop(s["object"]))
            else:
                obj = doc.getObject(names[s["object"]])
                value = s["value"]
                if s["property"] == "Placement" and isinstance(value, dict):
                    value = FreeCAD.Placement(FreeCAD.Vector(*value["position_mm"]),
                                              FreeCAD.Rotation(FreeCAD.Vector(*value["axis"]), value["angle_deg"]))
                setattr(obj, s["property"], value)
            stats[s["op"]] += 1
        except Exception:  # noqa: BLE001 — 只读属性、类型不符等：跳过并计数
            stats["skipped"] += 1
    doc.recompute()
    return doc, dict(stats)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="录制会话的查看、导出与重放（ADR-0042）")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    s = sub.add_parser("show")
    s.add_argument("session")
    e = sub.add_parser("export")
    e.add_argument("out", type=Path)
    e.add_argument("--rated-only", action="store_true", help="只导出用户评价过的会话")
    r = sub.add_parser("replay")
    r.add_argument("session")
    r.add_argument("--doc", help="只重放这个文档的改动（默认取改动最多的文档）")
    r.add_argument("--save", type=Path, help="把重建的文档存为 .FCStd")
    args = p.parse_args(argv)
    try:
        if args.cmd == "list":
            for it in list_sessions():
                print(f"{it['session']}  {it['started_at']}  事件 {it['events']}  评价 {it['rating'] or '—'}"
                      f"{'  视频' if it['video'] else ''}{'' if it['finished'] else '  （未正常结束）'}")
        elif args.cmd == "show":
            print(json.dumps(summarize(read_session(resolve(args.session))), ensure_ascii=False, indent=2))
        elif args.cmd == "export":
            n = export(args.out, rated_only=args.rated_only)
            print(f"已导出 {n} 个会话 → {args.out}")
        else:
            steps = plan_replay(read_session(resolve(args.session))["events"], args.doc)
            doc, stats = apply_replay(steps)
            if args.save:
                doc.saveAs(str(args.save))
            print(f"重放 {len(steps)} 步：{stats}")
    except RecorderError as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
