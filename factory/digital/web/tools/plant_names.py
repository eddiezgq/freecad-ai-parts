"""第 130 轮第二批：从各厂清单（factory/plants/*.yaml）和工厂本体（factory/digital/ontology/*.yaml 的 label_en）生成名字的中英对照 → src/locales/en_names.json。
运营各页显示的设备名、工作站、工序、物料、客户、供应商是枢纽按清单给的中文（或中英合写），网页用 $td() 按这张表换成英文。
清单改了重跑：python3 factory/digital/web/tools/plant_names.py（tests/test_i18n.py 会检查表和清单一致）"""
import glob
import json
import os
import re

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
PLANTS = os.path.join(HERE, "..", "..", "..", "plants")
ONT = os.path.join(HERE, "..", "..", "ontology")
OUT = os.path.join(HERE, "..", "src", "locales", "en_names.json")
CJK = re.compile(r"[　-〿㐀-鿿＀-￯]")


def en_part(s):
    toks = str(s).split()
    last = max([i for i, t in enumerate(toks) if CJK.search(t)], default=-1)
    rest = toks[last + 1:]
    while len(rest) > 1 and rest[0] in rest[1:]:
        rest = rest[1:]
    return " ".join(rest)


def zh_part(s):
    toks = str(s).split()
    last = max([i for i, t in enumerate(toks) if CJK.search(t)], default=-1)
    return " ".join(toks[:last + 1])


def pairs():
    out = {}

    def add(zh, en):
        zh, en = (zh or "").strip(), (en or "").strip()
        if zh and en and CJK.search(zh) and not CJK.search(en) and zh not in out:
            out[zh] = en

    def bil(s):                       # 中英合写：整句 → 英文部分；中文部分（去掉“示例·”）→ 英文部分
        if s and CJK.search(s) and en_part(s):
            add(s, en_part(s))
            z, e = zh_part(s), en_part(s)
            if not re.search(r"\d", e) and not re.search(r"[A-Za-z]", z):   # 英文里有规格、编号（中文部分没有）的不单拆
                add(z, e)
                add(re.sub(r"^示例·", "", z), e)

    for f in sorted(glob.glob(os.path.join(PLANTS, "wenquest-*.yaml"))):
        p = yaml.safe_load(open(f, encoding="utf-8"))
        bil(p["company"]["name"])
        ws_en = {}
        for u in p.get("units", []):
            add(u["name"], u.get("name_en"))
            if u.get("workstation") and u.get("name_en"):
                z = zh_part(u["workstation"])
                e = re.sub(r" [A-Z]$", "", u["name_en"]) if not re.search(r" [A-Z]$", z) else u["name_en"]
                ws_en.setdefault(z, e)
        for z, e in ws_en.items():
            add(z, e)
        for w in p.get("workstations", []):
            z = zh_part(w["name"])
            if z in ws_en:
                add(w["name"], w["name"].replace(z, ws_en[z]))
        for o in p.get("operations", []):
            bil(o["name"])
        for r in p.get("routings", []):
            bil(r["name"])
            for st in r.get("steps", []):
                bil(st[0])
        for it in p.get("items", []):
            bil(it["name"])
        for c in p.get("customers", []) or []:
            bil(c if isinstance(c, str) else c.get("name"))
        for s in (p.get("suppliers") or {}).values():
            bil(s.get("name"))
            bil((s.get("alt") or {}).get("name"))
    for f in sorted(glob.glob(os.path.join(ONT, "*.yaml"))):          # 工厂本体：领域名、对象类型名
        o = yaml.safe_load(open(f, encoding="utf-8")) or {}
        add(o.get("label"), o.get("label_en"))
        for t in (o.get("types") or {}).values():
            if isinstance(t, dict):
                add(t.get("label"), t.get("label_en"))
    return sorted(([k, v] for k, v in out.items()), key=lambda x: (-len(x[0]), x[0]))


if __name__ == "__main__":
    json.dump(pairs(), open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    open(OUT, "a").write("\n")
    print(len(pairs()), "pairs →", OUT)
