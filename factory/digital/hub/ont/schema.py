# -*- coding: utf-8 -*-
"""本体定义：读 digital/ontology/*.yaml，校验，给出类型、属性、链接（含反向）的索引。"""
import glob
import os
import re

import yaml

HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DIR = os.environ.get("WQ_ONTOLOGY_DIR", os.path.join(HERE, "ontology"))
MATURITY = {"have": "已有数据", "erp": "ERPNext 可启用", "capture": "待采集", "sim": "教学模拟", "next": "后续各期生成"}
ANY = "*"                    # 通用链接的目标：任何类型（如“异常 —涉及→ 任何对象”）
PROP_TYPES = {"str", "num", "int", "bool", "date", "time", "json"}
ROWS = {"chain", "support", "core"}


class OntologyError(ValueError):
    pass


class Ontology:
    def __init__(self, domains):
        self.domains = domains                    # [{domain, order, label, label_en, row, types: [名]}]
        self.types = {}                           # 名 → spec（含 domain、links、props）
        self.links = {}                           # (类型, 链接名) → spec（含 frm、to）
        self.incoming = {}                        # 类型 → [(源类型, 链接名, spec)]

    def type(self, name):
        t = self.types.get(name)
        if t is None:
            raise KeyError("本体里没有对象类型 " + str(name))
        return t

    def incoming_of(self, t):
        """指向类型 t 的链接，含通用链接"""
        return self.incoming.get(t, []) + self.incoming.get(ANY, [])

    def link(self, frm, name):
        s = self.links.get((frm, name))
        if s is None:
            raise KeyError("本体里没有链接 {}.{}".format(frm, name))
        return s

    def public(self):
        """给网页和 AI 的本体说明（不含映射细节）"""
        out = []
        for d in self.domains:
            out.append({k: d[k] for k in ("domain", "order", "label", "label_en", "row")} | {"types": [
                {"name": n, "label": self.types[n]["label"], "label_en": self.types[n].get("label_en", ""),
                 "maturity": self.types[n]["maturity"], "maturity_label": MATURITY[self.types[n]["maturity"]],
                 "key": self.types[n].get("key", ""), "sensitivity": self.types[n].get("sensitivity", 0),
                 "sources": self.types[n].get("sources", []),
                 "props": [{"name": p, "label": s["l"], "type": s["t"], "unit": s.get("u", ""), "series": bool(s.get("series")),
                            "sensitivity": s.get("s", self.types[n].get("sensitivity", 0))} for p, s in self.types[n]["props"].items()],
                 "links": [{"name": ln, "to": s["to"], "label": s["l"], "inverse": s.get("inv", "")} for ln, s in self.types[n]["links"].items()],
                 "incoming": [{"from": f, "name": ln, "label": s.get("inv") or s["l"]} for f, ln, s in self.incoming_of(n)]}
                for n in d["types"]]})
        return out


def load(path=DIR):
    files = sorted(glob.glob(os.path.join(path, "*.yaml")))
    if not files:
        raise OntologyError("没有找到本体定义：" + path)
    domains, seen_dom = [], set()
    onto = Ontology(domains)
    for f in files:
        try:
            doc = yaml.safe_load(open(f, encoding="utf-8"))
        except yaml.YAMLError as e:
            raise OntologyError("{}：YAML 格式错误：{}".format(os.path.basename(f), e)) from None
        name = os.path.basename(f)
        for k in ("domain", "order", "label", "row", "types"):
            if k not in doc:
                raise OntologyError("{}：缺少 {}".format(name, k))
        if doc["domain"] in seen_dom:
            raise OntologyError("{}：领域代号 {} 重复".format(name, doc["domain"]))
        if doc["row"] not in ROWS:
            raise OntologyError("{}：row 只能是 {}".format(name, "、".join(sorted(ROWS))))
        seen_dom.add(doc["domain"])
        d = {"domain": doc["domain"], "order": doc["order"], "label": doc["label"], "label_en": doc.get("label_en", ""),
             "row": doc["row"], "types": []}
        for tn, ts in (doc["types"] or {}).items():
            where = "{} 的 {}".format(name, tn)
            if not re.fullmatch(r"[A-Z][A-Za-z0-9]*", tn):
                raise OntologyError("{}：类型名要用大驼峰英文".format(where))
            if tn in onto.types:
                raise OntologyError("{}：对象类型重复（{} 已在 {} 定义）".format(where, tn, onto.types[tn]["domain"]))
            if ts.get("maturity") not in MATURITY:
                raise OntologyError("{}：maturity 只能是 {}".format(where, "、".join(MATURITY)))
            props = ts.get("props") or {}
            for pn, ps in props.items():
                if not isinstance(ps, dict) or ps.get("t") not in PROP_TYPES or not ps.get("l"):
                    raise OntologyError("{}.{}：属性要写 t（{}）和 l（显示名）".format(where, pn, "、".join(sorted(PROP_TYPES))))
            title = ts.get("title", "{key}")
            for ref in re.findall(r"{(\w+)}", title):
                if ref != "key" and ref not in props:
                    raise OntologyError("{}：显示名模板引用了不存在的属性 {}".format(where, ref))
            spec = dict(ts, name=tn, domain=doc["domain"], props=props, links=ts.get("links") or {}, title=title)
            onto.types[tn] = spec
            d["types"].append(tn)
        domains.append(d)
    for tn, t in onto.types.items():
        for ln, ls in t["links"].items():
            if not isinstance(ls, dict) or not ls.get("to") or not ls.get("l"):
                raise OntologyError("{}.{}：链接要写 to 和 l".format(tn, ln))
            if ls["to"] != ANY and ls["to"] not in onto.types:
                raise OntologyError("{}.{}：链接目标 {} 不是本体里的对象类型".format(tn, ln, ls["to"]))
            onto.links[(tn, ln)] = dict(ls, frm=tn, name=ln)
            onto.incoming.setdefault(ls["to"], []).append((tn, ln, ls))
    domains.sort(key=lambda d: d["order"])
    return onto


_cache = {}


def get(path=DIR):
    if path not in _cache:
        _cache[path] = load(path)
    return _cache[path]


def title_of(spec, key, props):
    def rep(m):
        k = m.group(1)
        v = key if k == "key" else props.get(k)
        return "" if v is None else str(v)
    return re.sub(r"{(\w+)}", rep, spec["title"]).strip() or key
