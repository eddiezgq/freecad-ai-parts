# -*- coding: utf-8 -*-
"""FreeCAD 选型方案发布到工厂（本仓库 ADR-0058 第 4 条、M10 第 6c 项）。

FreeCAD 的“发布到工厂”把当前方案发来：方案编号与名称、BOM（每行：组件 id、品类、厂商、型号、数量、单件质量、
来源文档、来自公共库还是企业库）、需求、校验结论、布局概要、附件（STEP）。枢纽存一份新版本（同一编号的版本号加一），
再把 cad.release 消息发到数据总线（主题 wq/gearbox/design/cad-<编号>/release），工作台“CAD 方案”页列出。
"""
import re

CODE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,39}$")
CATEGORIES = {"servo_motor": "伺服电机", "reducer": "减速器", "drive": "驱动器", "bearing": "轴承", "adapter": "转接件"}


class CadError(ValueError):
    pass


def validate(body):
    """检查发布内容；返回整理后的数据。纯函数。"""
    if not isinstance(body, dict):
        raise CadError("内容须为对象")
    code = str(body.get("code") or "").strip()
    if not CODE.match(code):
        raise CadError("方案编号只能用字母、数字、点、横线、下划线，最多 40 个字符")
    name = str(body.get("name") or "").strip()
    if not name:
        raise CadError("请写方案名称")
    bom = body.get("bom")
    if not isinstance(bom, list) or not bom:
        raise CadError("BOM 是空的")
    rows = []
    for i, r in enumerate(bom, 1):
        if not isinstance(r, dict) or not r.get("component_id") or not r.get("model"):
            raise CadError("BOM 第 {} 行缺组件 id 或型号".format(i))
        qty = r.get("quantity", 1)
        if not isinstance(qty, int) or isinstance(qty, bool) or qty < 1:
            raise CadError("BOM 第 {} 行数量须为正整数".format(i))
        rows.append({k: r.get(k) for k in ("component_id", "category", "vendor", "model", "quantity", "instances",
                                            "unit_mass_kg", "source_docs", "all_params_reviewed", "library")})
    files = []
    for f in body.get("files") or []:
        if not isinstance(f, dict) or not str(f.get("url", "")).startswith("/api/files/"):
            raise CadError("附件须先经 /api/files 上传")
        files.append({k: f.get(k) for k in ("kind", "name", "url", "sha256", "size")})
    return {"code": code, "name": name[:120], "bom": rows, "files": files,
            "requirement": body.get("requirement"), "checks": body.get("checks"), "layout": body.get("layout"),
            "note": str(body.get("note") or "")[:500], "tool": str(body.get("tool") or "FreeCAD AI Parts")[:80]}


def release(db, emit, mode, author, body):
    d = validate(body)
    cur = db.one("select max(revision) as r from cad_design where mode=%s and code=%s", (mode, d["code"]))
    rev = ((cur or {}).get("r") or 0) + 1
    data = {k: d[k] for k in ("bom", "files", "requirement", "checks", "layout", "note", "tool")}
    import json
    db.x("insert into cad_design (mode, code, revision, name, author, data) values (%s,%s,%s,%s,%s,%s)",
         (mode, d["code"], rev, d["name"], author, json.dumps(data, ensure_ascii=False)))
    msg = {"code": d["code"], "revision": rev, "name": d["name"], "author": author, "bom": d["bom"], "files": d["files"],
           "note": d["note"], "checks_overall": (d["checks"] or {}).get("overall") if isinstance(d["checks"], dict) else None}
    emit("wq/gearbox/design/cad-{}/release".format(d["code"].lower()), "cad.release", msg)
    return {"code": d["code"], "revision": rev, "name": d["name"]}


def designs(db, mode):
    rows = db.q("select distinct on (code) code, revision, name, author, ts, data from cad_design where mode=%s "
                "order by code, revision desc", (mode,))
    return [{"code": r["code"], "revision": r["revision"], "name": r["name"], "author": r["author"],
             "ts": r["ts"].isoformat(), "parts": sum(x.get("quantity") or 1 for x in r["data"]["bom"]),
             "overall": (r["data"].get("checks") or {}).get("overall")} for r in sorted(rows, key=lambda r: r["ts"], reverse=True)]


def design(db, mode, code):
    rows = db.q("select revision, name, author, ts, data from cad_design where mode=%s and code=%s order by revision desc",
                (mode, code))
    if not rows:
        return None
    head = rows[0]
    return {"code": code, "revision": head["revision"], "name": head["name"], "author": head["author"],
            "ts": head["ts"].isoformat(), **head["data"],
            "history": [{"revision": r["revision"], "author": r["author"], "ts": r["ts"].isoformat(),
                         "note": r["data"].get("note")} for r in rows]}
