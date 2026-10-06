# -*- coding: utf-8 -*-
"""AI 选型（零件库第 5 轮 P10③）：一句话提需求，只从零件库里挑；答案注明条目编号/规格、规格表行和出处，库里没有的不编造。

模型走数字工厂现有的 AI 通道（hub/llm.py）：国内部署只配已备案模型（DeepSeek），Claude 只在美国用。
没配模型时用规则回答（关键词 → 族，句子里的数字 → 关键参数），同样只从库里挑。
答案里出现的编号逐个核对：库里没有的编号不出现在结果里，并在 invalid_refs 里列出。
"""
import json
import os
import re
import threading
import time

from hub import library as L

REF = re.compile(r"\b([A-E]-[A-Z0-9]{2,5}-[A-Z0-9]+(?:-[A-Z0-9]+)*)(?:/([A-Za-z0-9.×x*\-]+))?")
NUM = re.compile(r"(\d+(?:\.\d+)?)\s*(mm|毫米|kg|公斤|N·m|Nm|N|r/min|rpm|转|W|V|齿|个|台|[A-Za-z])?", re.I)
TEETH = re.compile(r"(\d+)\s*齿")
PROFILE = re.compile(r"\b(GT2|3M|5M)\b", re.I)

# 规则回答用：关键词 → 首选条目（按顺序）；数字按单位落到哪个关键参数
RULES = [
    (("径向", "深沟", "轴承"), ["A-BRG-DG", "A-BRG-CR", "A-BRG-AC", "A-BRG-TR"]),
    (("轴向", "角接触", "联合载荷"), ["A-BRG-AC", "A-BRG-TR"]),
    (("圆锥滚子",), ["A-BRG-TR"]), (("圆柱滚子",), ["A-BRG-CR"]),
    (("键",), ["A-KEY-FLAT"]), (("螺栓",), ["A-BLT-HEX"]), (("螺钉",), ["A-SCR-SHC"]), (("螺母",), ["A-NUT-HEX"]),
    (("油封", "密封"), ["A-SEL-LIP", "A-SEL-ORING"]), (("丝杠",), ["A-BSC-SFU", "C-SCN-LEAD"]), (("导轨",), ["A-LGD-RAIL"]),
    (("带轮", "同步带"), ["A-PUL-HTD"]), (("联轴器",), ["A-CPL-JAW"]), (("弹簧",), ["A-SPR-CMP"]),
    (("谐波",), ["D-RDC-HD-CSF"]), (("RV",), ["D-RDC-NABTESCO-RVN"]), (("夹爪",), ["D-GRP-ROBOTIQ", "D-GRP-ONROBOT"]),
    (("激光雷达", "雷达"), ["D-LDR-OUSTER", "D-LDR-SICK-TIM"]), (("力传感器", "六维力"), ["D-FTS-ATI-FT"]),
]
# 句子里的毫米数对应哪个参数：区间（键按轴径、联轴器按孔径）或等于（导轨按导轨宽、弹簧按中径）；没列的取第一个直径类关键参数
DIM_RULE = {"A-KEY-FLAT": ("range", "shaft_min_mm", "shaft_max_mm", "gt"), "A-CPL-JAW": ("range", "d_min_mm", "d_max_mm", "ge"),
            "A-LGD-RAIL": ("eq", "rail_W_mm"), "A-SPR-CMP": ("eq", "D_mm"), "A-PUL-HTD": ("pulley",)}
SERIES_PREF = ["62", "63", "60", "72", "73", "302", "303", "NU2", "NU3"]       # 规则：轴承优先轻系列（常用、机械设计教材的首选）

SYSTEM = """你是问渠零件库的选型助手。规矩：
1. 只能推荐零件库里有的条目和规格。先用 search_library 找族，再用 find_sizes 按尺寸、参数筛规格；不确定就多查一次，不要凭记忆。
2. 答案里每个推荐都写成“编号/规格”（如 A-BRG-DG/6207），并列出你依据的规格表那一行的参数值（名称、数值、单位）和出处（数据来源）。
3. 库里没有合适的，直接说“零件库里没有”，可以说明缺什么，但不要编造编号或参数。
4. 给理由时只引用库里的参数和条目里的教学说明，不写“最好”“最畅销”之类库里没有的信息；需要计算（寿命、强度）而库里没有载荷参数时，说明需要查样本或计算。
5. 用中文，简短：先给推荐（1～3 个），再列依据。"""

TOOLS = [
    {"name": "search_library", "description": "按关键词搜零件库的族/条目（名称、编号、标准号、类别、标签）。返回条目编号、名称、类别、关键参数名和规格数。",
     "input_schema": {"type": "object", "properties": {"query": {"type": "string"}, "part": {"type": "string", "enum": ["A", "B", "C", "D"]}},
                      "required": ["query"]}},
    {"name": "find_sizes", "description": "在一个条目里按参数筛规格。where 每项 {key, op, value}，op 取 = >= <= ≈（≈ 允许 ±5%）。返回规格行（全部参数）与出处。",
     "input_schema": {"type": "object", "properties": {
         "entry": {"type": "string"},
         "where": {"type": "array", "items": {"type": "object", "properties": {"key": {"type": "string"}, "op": {"type": "string"}, "value": {}},
                                              "required": ["key", "op", "value"]}}},
         "required": ["entry"]}},
    {"name": "get_entry", "description": "条目详情：参数定义（键、中文名、单位）、标准、教学说明（原理、用途）、数据来源。",
     "input_schema": {"type": "object", "properties": {"entry": {"type": "string"}}, "required": ["entry"]}},
]


class Catalog:
    """读服务器上的零件库（WQ_LIBRARY_DIR 下 latest.json → index.json、各条目 entry.json），按版本缓存"""

    def __init__(self, root=None):
        self.root = root
        self.lock = threading.Lock()
        self.version, self.index, self.entries, self.checked = None, None, {}, 0

    def _dir(self):
        return self.root or L._dir()

    def load(self):
        with self.lock:
            if self.index is not None and time.time() - self.checked < 60:
                return self.index
            self.checked = time.time()
            try:
                latest = json.load(open(os.path.join(self._dir(), "latest.json"), encoding="utf-8"))
            except (OSError, ValueError):
                self.index = None
                return None
            if latest["version"] != self.version or self.index is None:
                path = os.path.join(self._dir(), latest["index"].split("library/", 1)[-1])
                self.index = json.load(open(path, encoding="utf-8"))
                self.version, self.entries = latest["version"], {}
            return self.index

    def entry(self, eid):
        idx = self.load()
        if idx is None:
            return None
        if eid not in self.entries:
            try:
                self.entries[eid] = json.load(open(os.path.join(self._dir(), self.version, eid, "entry.json"), encoding="utf-8"))
            except (OSError, ValueError):
                self.entries[eid] = None
        return self.entries[eid]

    def families(self):
        out = {}
        for it in (self.load() or {}).get("items", []):
            f = out.setdefault(it["id"], {"id": it["id"], "name": (it.get("family") or it["name"])["zh"], "part": it["part"],
                                          "category": it.get("category"), "standards": it.get("standards") or [],
                                          "tags": it.get("tags") or [], "sizes": 0, "keys": list((it.get("params") or {}).keys())})
            f["sizes"] += 1
        return out

    # ---- 工具
    def search(self, query, part=None, limit=10):
        q = [w for w in re.split(r"[\s,，、/]+", (query or "").lower()) if w]
        cats = (self.load() or {}).get("categories") or {}
        hits = []
        for f in self.families().values():
            if part and f["part"] != part:
                continue
            cat_name = ((cats.get(f["part"]) or {}).get(f["category"]) or {}).get("zh", "")
            hay = " ".join([f["id"], f["name"], cat_name] + f["standards"] + f["tags"]).lower()
            score = sum(1 for w in q if w in hay)
            if score:
                hits.append((score, f))
        hits.sort(key=lambda x: (-x[0], x[1]["id"]))
        return [dict(f, category_name=((cats.get(f["part"]) or {}).get(f["category"]) or {}).get("zh")) for _, f in hits[:limit]]

    def find_sizes(self, entry, where=None, limit=12):
        e = self.entry(entry)
        if not e:
            return {"error": "零件库里没有条目 {}".format(entry)}
        rows = []
        for s in e.get("sizes") or []:
            ok = True
            for c in where or []:
                v = s["params"].get(c.get("key"))
                try:
                    v, t = float(v), float(c.get("value"))
                except (TypeError, ValueError):
                    ok = str(v) == str(c.get("value")) if c.get("op") == "=" else False
                    if not ok:
                        break
                    continue
                op = c.get("op", "=")
                ok = (abs(v - t) < 1e-9 if op == "=" else v >= t if op == ">=" else v <= t if op == "<=" else abs(v - t) <= 0.05 * abs(t) if op in ("≈", "~") else False)
                if not ok:
                    break
            if ok:
                rows.append({"ref": "{}/{}".format(e["id"], s["size"]), "size": s["size"], "params": s["params"]})
        return {"entry": e["id"], "name": e["name"]["zh"], "params": [{"key": p["key"], "zh": p.get("zh"), "unit": p.get("unit")} for p in e.get("params") or []],
                "count": len(rows), "rows": rows[:limit], "sources": _sources(e)}

    def get_entry(self, entry):
        e = self.entry(entry)
        if not e:
            return {"error": "零件库里没有条目 {}".format(entry)}
        return {"id": e["id"], "name": e["name"], "kind": e.get("kind"), "standards": [s.get("code") for s in e.get("standards") or []],
                "params": [{"key": p["key"], "zh": p.get("zh"), "unit": p.get("unit"), "role": p.get("role")} for p in e.get("params") or []],
                "teaching": {k: (e.get("teaching") or {}).get(k) for k in ("principle", "uses")}, "sources": _sources(e),
                "sizes": len(e.get("sizes") or []), "datasheet": (e.get("datasheet") or {}).get("values")}

    def valid(self, ref, size=None):
        """编号（及规格）是否在库里"""
        e = self.entry(ref)
        if not e:
            return False
        return size is None or any(str(s["size"]) == str(size) for s in e.get("sizes") or [])


def _sources(e):
    src = e.get("source") or {}
    out = [{"title": d.get("title"), "url": d.get("url")} for d in src.get("data_sources") or []]
    if not out:
        out = [{"title": src.get("attribution") or src.get("origin"), "url": src.get("repo")}]
    return out


def check_refs(cat, text):
    """答案里的编号逐个核对：返回 (有效 [{ref, entry, size}], 无效 [ref])"""
    ok, bad, seen = [], [], set()
    for m in REF.finditer(text or ""):
        eid, size = m.group(1), m.group(2)
        key = eid + ("/" + size if size else "")
        if key in seen:
            continue
        seen.add(key)
        if cat.valid(eid, size):
            ok.append({"ref": key, "entry": eid, "size": size})
        else:
            bad.append(key)
    return ok, bad


def _detail(cat, r):
    e = cat.entry(r["entry"])
    out = {"ref": r["ref"], "entry": r["entry"], "size": r["size"], "name": e["name"]["zh"] if e else r["entry"]}
    if e and r["size"]:
        s = next((s for s in e.get("sizes") or [] if str(s["size"]) == str(r["size"])), None)
        if s:
            names = {p["key"]: (p.get("zh"), p.get("unit")) for p in e.get("params") or []}
            out["row"] = [{"key": k, "zh": names.get(k, (k, None))[0], "value": v, "unit": names.get(k, (None, None))[1]}
                          for k, v in s["params"].items() if k in names]
    if e:
        out["sources"] = _sources(e)
    return out


def rules_answer(cat, question):
    """没配模型时：关键词定族，数字定关键参数（mm → 第一个直径/尺寸键），按常用系列排序，最多 3 个"""
    q = question or ""
    fams = []
    for words, ids in RULES:
        if any(w.lower() in q.lower() for w in words):
            fams += [i for i in ids if cat.entry(i) and i not in fams]
    if not fams:
        hits = cat.search(q)
        fams = [h["id"] for h in hits[:3]]
    if not fams:
        return "零件库里没有找到和“{}”相关的条目。".format(q.strip()), []
    nums = [(float(m.group(1)), (m.group(2) or "").lower()) for m in NUM.finditer(q)]
    mm = [v for v, u in nums if u in ("mm", "毫米")] or [v for v, u in nums if u == "" and v < 400]
    picks, unfiltered = [], []
    for fid in fams:
        e = cat.entry(fid)
        keys = [p["key"] for p in e.get("params") or [] if p.get("role") == "key"]
        rule = DIM_RULE.get(fid)
        if rule is None:
            dkey = next((k for k in keys if k.startswith(("d_", "d0_", "d1_", "id_"))), None)
            rule = ("eq", dkey) if dkey else ("none",)
        if rule[0] == "pulley":                            # 同步带轮：按“N 齿”和齿形（GT2、3M、5M）筛
            where = [{"key": "z", "op": "=", "value": int(m.group(1))} for m in TEETH.finditer(q)][:1]
            where += [{"key": "profile", "op": "=", "value": m.group(1).upper()} for m in PROFILE.finditer(q)][:1]
            if not where and mm:
                unfiltered.append(fid)
                continue
            rows = cat.find_sizes(fid, where, limit=50).get("rows") or []
        elif mm and rule[0] == "range":
            rows = [r for r in (cat.find_sizes(fid, [], limit=10000).get("rows") or [])
                    if _num(r["params"].get(rule[1])) is not None and _num(r["params"].get(rule[2])) is not None
                    and (_num(r["params"][rule[1]]) < mm[0] if rule[3] == "gt" else _num(r["params"][rule[1]]) <= mm[0])
                    and mm[0] <= _num(r["params"][rule[2]])]
        elif mm and rule[0] == "eq":
            rows = cat.find_sizes(fid, [{"key": rule[1], "op": "=", "value": mm[0]}], limit=50).get("rows") or []
        elif mm:                                           # 这个族不能按毫米数直接筛：不挑规格，提示看规格表
            unfiltered.append(fid)
            continue
        else:
            rows = cat.find_sizes(fid, [], limit=50).get("rows") or []
        rows.sort(key=lambda r: next((i for i, p in enumerate(SERIES_PREF) if str(r["size"]).startswith(p)), 99))
        picks += [{"ref": r["ref"], "entry": fid, "size": r["size"]} for r in rows[:3 - len(picks)]]
        if len(picks) >= 3:
            break
    if not picks and unfiltered:
        names = "、".join((cat.entry(f) or {}).get("name", {}).get("zh", f) for f in unfiltered)
        return "零件库里有相关的族（{}），但没法按“{}”直接筛规格，请在库页面打开这个族看规格表。".format(
            names, "、".join(fmt(v) + " mm" for v in mm)), []
    if not picks:
        names = "、".join((cat.entry(f) or {}).get("name", {}).get("zh", f) for f in fams)
        return "零件库里有相关的族（{}），但没有符合“{}”尺寸的规格。".format(names, "、".join(fmt(v) + " mm" for v in mm)), []
    lines = ["按零件库的规格表（规则匹配，未用 AI 模型）："]
    for i, p in enumerate(picks, 1):
        d = _detail(cat, p)
        row = "，".join("{} {}{}".format(x["zh"], x["value"], " " + x["unit"] if x.get("unit") else "") for x in (d.get("row") or [])[:4])
        lines.append("{}. {}（{}）：{}".format(i, p["ref"], d["name"], row))
    e0 = cat.entry(picks[0]["entry"])
    if e0 and (e0.get("teaching") or {}).get("principle"):
        lines.append("说明：" + e0["teaching"]["principle"])
    lines.append("排序：同一内径时先列轻系列（如 62 系列），寿命和载荷要按样本额定载荷另算。")
    return "\n".join(lines), picks


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def fmt(v):
    return ("%g" % v)


def answer(cat, llm, question):
    """返回 {answer, refs[], invalid_refs[], engine}"""
    if cat.load() is None:
        return {"answer": "零件库还没有发布，暂时不能选型。", "refs": [], "invalid_refs": [], "engine": "none"}
    if llm is not None and llm.available():
        tools = {"search_library": lambda a: cat.search(a.get("query"), a.get("part")),
                 "find_sizes": lambda a: cat.find_sizes(a.get("entry"), a.get("where")),
                 "get_entry": lambda a: cat.get_entry(a.get("entry"))}
        text, trace = llm.run(SYSTEM, [{"role": "user", "content": question}], TOOLS,
                              lambda name, args: tools[name](args) if name in tools else {"error": "没有这个工具"})
        engine = llm.name
    else:
        text, _ = rules_answer(cat, question)
        engine = "rules"
    ok, bad = check_refs(cat, text)
    if bad:
        text += "\n\n（核对：{} 不在零件库里，已从推荐里去掉。）".format("、".join(bad))
    return {"answer": text, "refs": [_detail(cat, r) for r in ok], "invalid_refs": bad, "engine": engine,
            "library_version": cat.version}
