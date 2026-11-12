"""第 160 轮：两份工厂清单（原始 dict，yaml / Excel 导入的样子）比一比——网页上传改好的清单后给“改动预览”。纯函数。

比这些：物料、物料清单、工艺路线、成品、工序、设备。每类给 added / removed / changed 三张表，每张最多 LIMIT 条。"""

LIMIT = 50


def _by(rows, key):
    return {r[key]: r for r in rows or [] if isinstance(r, dict) and r.get(key) is not None}


def _cap(rows):
    rows = list(rows)
    return {"rows": rows[:LIMIT], "more": max(0, len(rows) - LIMIT)}


def _fields(a, b, keys):
    """a → b 改了的字段：[(字段, 原值, 新值)]"""
    return [(k, a.get(k), b.get(k)) for k in keys if a.get(k) != b.get(k)]


def _section(old, new, key, keys):
    o, n = _by(old, key), _by(new, key)
    added = [k for k in n if k not in o]
    removed = [k for k in o if k not in n]
    changed = []
    for k in n:
        if k in o:
            f = _fields(o[k], n[k], keys)
            if f:
                changed.append({"key": k, "fields": [{"field": x, "old": y, "new": z} for x, y, z in f]})
    return {"added": _cap(added), "removed": _cap(removed), "changed": _cap(changed)}


def _lines(rows):
    """[[子件, 用量]] 或 [[工序, 分钟]] → {名: 数}（同名多行相加）"""
    out = {}
    for r in rows or []:
        if isinstance(r, (list, tuple)) and len(r) >= 2:
            out[str(r[0])] = out.get(str(r[0]), 0) + (r[1] if isinstance(r[1], (int, float)) else 0)
    return out


def _nested(old, new, key, child):
    """物料清单（父件 → 子件、用量）、工艺路线（路线 → 工序、分钟）：父级增删，子级增删改"""
    o, n = _by(old, key), _by(new, key)
    added = [k for k in n if k not in o]
    removed = [k for k in o if k not in n]
    changed = []
    for k in n:
        if k not in o:
            continue
        a, b = _lines(o[k].get(child)), _lines(n[k].get(child))
        rows = [{"line": c, "old": None, "new": b[c]} for c in b if c not in a] + \
               [{"line": c, "old": a[c], "new": None} for c in a if c not in b] + \
               [{"line": c, "old": a[c], "new": b[c]} for c in b if c in a and a[c] != b[c]]
        extra = [{"line": f"（{f}）", "old": x, "new": y} for f, x, y in _fields(o[k], n[k], [x for x in ("routing",) if key == "item"])]
        order = [] if rows or extra or key != "name" or list(a) == list(b) else [{"line": "（工序顺序）", "old": " → ".join(a), "new": " → ".join(b)}]
        if rows or extra or order:
            changed.append({"key": k, "lines": rows + extra + order})
    return {"added": _cap(added), "removed": _cap(removed), "changed": _cap(changed)}


def diff(old, new):
    """old、new：清单原始 dict。返回 {类别: {added, removed, changed}, "total": 改动条数}"""
    old, new = old or {}, new or {}
    out = {
        "items": _section(old.get("items"), new.get("items"), "code", ("name", "kind", "uom", "price", "supplier")),
        "boms": _nested(old.get("boms"), new.get("boms"), "item", "components"),
        "routings": _nested(old.get("routings"), new.get("routings"), "name", "steps"),
        "products": _section(old.get("products"), new.get("products"), "item", ("price",)),
        "operations": _section(old.get("operations"), new.get("operations"), "name", ("workstation", "units", "stage")),
        "units": _section(old.get("units"), new.get("units"), "id", ("workstation", "name", "area")),
    }
    out["total"] = sum(len(v[k]["rows"]) + v[k]["more"] for v in out.values() for k in ("added", "removed", "changed"))
    return out
