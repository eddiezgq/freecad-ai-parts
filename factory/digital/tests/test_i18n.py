# -*- coding: utf-8 -*-
"""第 130 轮：数字工厂英文版（第一批）。
- 网页第一批页面：t() 的钥匙英文表里都有、t() 外不留中文、页面显示的数据文件都能译成英文（web/tools/i18n_check.mjs，要 Node）；
- 枢纽、计算服务给第一批页面的固定文字（例题参数、读数名、测量任务、功能测试步骤）英文表里都有；
- 枢纽看板文字的英文、语言怎么定。"""
import json
import os
import re
import shutil
import subprocess
import sys

import pytest

DIG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [DIG, os.path.dirname(DIG)]
WEB = os.path.join(DIG, "web")
EN = json.load(open(os.path.join(WEB, "src", "locales", "en.json"), encoding="utf-8"))
CJK = re.compile(r"[　-〿㐀-鿿＀-￯]")
ALLOW = 40     # 第 130 轮第四批 D-16：后端句子、报错的英文缺口容许数（别的轮次新加的句子先显示中文）


@pytest.mark.skipif(not shutil.which("node"), reason="没有 Node")
def test_web_batch1_node():
    r = subprocess.run(["node", "tools/i18n_check.mjs"], capture_output=True, text=True, cwd=WEB, timeout=120)
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-2000:]


def test_en_table_is_english():
    for k, v in EN.items():
        assert v and not CJK.search(v), "英文表里还有中文：{} → {}".format(k, v)
        assert set(re.findall(r"\{(\w+)\}", k)) == set(re.findall(r"\{(\w+)\}", v)), "占位符对不上：" + k


def test_hub_texts_have_english():
    from cae import circuit as C
    from cae import instruments as I
    from hub import fct
    need = []
    for k, v in C.EXAMPLES.items():
        need += [b for _, b, *_ in v["params"]] + [v["title"]]
        assert C.EN[k][0] and not CJK.search(C.EN[k][0] + C.EN[k][1])
    need += [v[0] for v in C.READING_NAMES.values()]
    need += re.findall(r'"note_formula": "([^"]+)"', open(os.path.join(DIG, "cae", "circuit.py"), encoding="utf-8").read())
    need += list(I.TITLES.values()) + [v[0] for v in I.LABELS.values()]
    for st in fct.STEPS:
        need += [st["title"], st["how"]]
    missing = [x for x in need if x not in EN]
    assert not missing, missing


def test_circuit_catalog_english():
    from cae import circuit as C
    for e in C.catalog():
        assert e["title_en"] and e["question_en"] and not CJK.search(e["question_en"])
    b = C.build("sense")
    assert "30 A" in b["question_en"]


def test_overview_localized():
    from hub import i18n
    ov = {
        "kpis": [{"label": "准时交付率（本月）", "note": "目标 95% · 2 单延期风险"},
                 {"label": "在制品", "note": "比昨天 +3（GRD-01 前排队 4 件）", "unit": "件"},
                 {"label": "设备综合效率 OEE（今日）", "note": "目标 75% · GRD-01 仅 52%"},
                 {"label": "一次合格率（本周）", "note": "目标 97% · 未达标 · 12 件"},
                 {"label": "本周完工 SH-301", "note": "计划到今天 8 件"},
                 {"label": "实际成本偏差（本周）", "note": "每件高 $12 · 主要是调整与换刀工时"}],
        "orders": [{"risk": "预计晚 2 天", "work_orders": "WO-0001 SH-301 已完工 3/10；WO-0002 SH-301 已完工 0/5"},
                   {"risk": "待排产，缺 BRG-6207", "work_orders": "尚未下达工单"}],
        "materials": [{"status": "低于安全库存", "qty_text": "6 件 · 在途 20", "uom": "件"}, {"status": "11-12 到货", "qty_text": "3.5 kg"}],
        "machines": [{"unit": "grd-01", "name": "外圆磨床"}],
        "week": {"days": [{"day": "周一"}], "bottleneck": "grd-01"},
        "quality": {"chart": {"title": "SH-301 轴承位 Ø35k6"}},
        "todos": [{"kind": "任务", "act": "去做", "src": "实验 7 · 接单", "text": "x"}],
    }
    units = {"grd-01": ("machining", "外圆磨床", "Cylindrical grinder", None)}
    out = i18n.localize_overview(json.loads(json.dumps(ov)), "en", units)
    texts = [k["label"] for k in out["kpis"]] + [k["note"] for k in out["kpis"]] + [o["risk"] for o in out["orders"]] \
        + [o["work_orders"] for o in out["orders"]] + [m["status"] for m in out["materials"]] + [m["qty_text"] for m in out["materials"]] \
        + [out["week"]["days"][0]["day"], out["quality"]["chart"]["title"], out["todos"][0]["kind"], out["todos"][0]["act"]]
    for x in texts:
        assert not CJK.search(x), x
    assert out["kpis"][1]["note"] == "+3 vs yesterday (4 queued at GRD-01)"
    assert out["machines"][0]["name_en"] == "Cylindrical grinder" and out["machines"][0]["name"] == "外圆磨床"
    assert out["todos"][0]["src"] == "Lab 7 · 接单"          # 实验任务的说明第二批再翻
    zh = i18n.localize_overview(json.loads(json.dumps(ov)), "zh", units)
    assert zh["kpis"] == ov["kpis"] and zh["machines"][0]["name_en"] == "Cylindrical grinder"   # 中文不变，只多 name_en


def test_lang_and_names():
    from hub import i18n

    class R:
        def __init__(self, h, c):
            self.headers, self.cookies = h, c
    assert i18n.lang_of(R({"x-wq-lang": "en"}, {})) == "en"
    assert i18n.lang_of(R({}, {"wq_lang": "en"})) == "en"
    assert i18n.lang_of(R({}, {})) == "zh"                       # 没带语言：照旧中文
    assert i18n.en_part("问渠电路板厂 WenQuest Electronics (Demo)") == "WenQuest Electronics (Demo)"
    assert i18n.en_part("贴片电阻 0402 Chip resistor 0402") == "Chip resistor 0402"
    assert i18n.en_part("45钢圆棒 Ø50 Steel bar 1045 Ø50") == "Steel bar 1045 Ø50"
    assert i18n.tr("没有这块板的功能测试记录：P-1") == "No functional test record for this board: P-1"
    assert i18n.tr("没见过的提示") == "没见过的提示"            # 没有对照的原样（中文），不报错


@pytest.mark.parametrize("plant", ["wenquest-gearbox", "wenquest-robot", "wenquest-pcb", "wenquest-chip", "wenquest-sensor"])
def test_plant_names_have_english(plant):
    """第一批页面显示的厂名、设备名、物料名、客户名：都能取到英文"""
    import yaml
    from hub import i18n
    p = yaml.safe_load(open(os.path.join(os.path.dirname(DIG), "plants", plant + ".yaml"), encoding="utf-8"))
    names = [p["company"]["name"]] + [i["name"] for i in p.get("items", [])] + list(p.get("customers", [])) + [o["name"] for o in p["operations"]]
    for n in names:
        e = i18n.en_part(n)
        assert e and not CJK.search(e), n
    for u in p["units"]:
        assert u.get("name_en") and not CJK.search(u["name_en"]), u["id"]


def test_supplier_categories_have_english():
    """供应商的物料类别（清单 suppliers.*.cat_name，采购与来料页“物料”一列用 $td 显示）：英文表里都有（11-10 录 07 英文画面时发现漏翻）"""
    import glob
    import yaml
    names = dict(json.load(open(os.path.join(WEB, "src", "locales", "en_names.json"), encoding="utf-8")))
    cats = set()

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                cats.add(v) if k == "cat_name" and isinstance(v, str) else walk(v)
        elif isinstance(o, list):
            [walk(x) for x in o]
    for f in glob.glob(os.path.join(os.path.dirname(DIG), "plants", "*.yaml")):
        walk(yaml.safe_load(open(f, encoding="utf-8")))
    missing = sorted(c for c in cats if CJK.search(c) and c not in EN and c not in names)
    assert not missing, missing


def test_lab_task_texts_have_english():
    """第二批：实验 7、实验 15–33 的任务题目、说明、提示、选项（模块常量），实验目录的题目、领域、学时，英文表里都有（页面用 $td 显示）"""
    import importlib
    from hub import labs_api
    need = []
    for m in ["teach"] + ["lab%d" % n for n in range(15, 41)]:
        mod = importlib.import_module("hub." + m)
        for t in mod.TASKS:
            need += [t[k] for k in ("title", "desc", "hint") if t.get(k)]
    for lab in labs_api.LABS:
        need += [lab[k] for k in ("title", "domain", "hours") if isinstance(lab.get(k), str) and CJK.search(lab[k])]

    def walk(o):                      # 模块里的常量（选择题选项、注入的问题种类……）
        if isinstance(o, str):
            if CJK.search(o):
                need.append(o)
        elif isinstance(o, dict):
            [walk(v) for v in o.values()]
        elif isinstance(o, (list, tuple)):
            [walk(v) for v in o]
    for m in ["teach"] + ["lab%d" % n for n in range(15, 41)]:
        for k, v in vars(importlib.import_module("hub." + m)).items():
            if k.isupper() and isinstance(v, (list, tuple, dict)):
                walk(v)
    names = dict(json.load(open(os.path.join(WEB, "src", "locales", "en_names.json"), encoding="utf-8")))
    missing = [x for x in need if x not in EN and x not in names]
    assert not missing, missing[:10]


def test_plant_names_table_in_sync():
    """第二批：运营各页按 web/src/locales/en_names.json 把清单里的名字换成英文；清单改了要重跑 web/tools/plant_names.py"""
    sys.path.insert(0, os.path.join(WEB, "tools"))
    import plant_names
    have = json.load(open(os.path.join(WEB, "src", "locales", "en_names.json"), encoding="utf-8"))
    assert have == plant_names.pairs(), "重跑 python3 factory/digital/web/tools/plant_names.py"
    d = dict(have)
    assert d["带锯床"] == "Band saw" and d["精车"] == "Finish turning"


def test_backend_texts_have_english():
    """第三批（细则 D-7、D-8）：枢纽、仿真写给页面的句子（句型）都在英文表、名字表或句型表里，占位一致；跳过的只能是不给人看的"""
    sys.path.insert(0, os.path.join(WEB, "tools"))
    import backend_texts as B
    loc = os.path.join(WEB, "src", "locales")
    names = dict(json.load(open(os.path.join(loc, "en_names.json"), encoding="utf-8")))
    tpls = json.load(open(os.path.join(loc, "en_templates.json"), encoding="utf-8"))
    skip = set(json.load(open(os.path.join(WEB, "tools", "backend_texts_skip.json"), encoding="utf-8")))
    have = set(EN) | set(names) | {z for z, _ in tpls}
    missing = [k for k in list(B.texts()) + list(B.yaml_texts()) if k not in have and k not in skip]
    # 别的轮次往这些模块里加了新句子、还没配英文时不卡他们的测试（英文界面显示中文）；缺口超过 ALLOW 才算回退（细则 D-16）
    assert len(missing) <= ALLOW, missing[:20]
    for z, e in tpls:
        assert set(re.findall(r"\{([a-z])\}", z)) == set(re.findall(r"\{([a-z])\}", e)), z
        assert e.strip() and not CJK.search(e), z
    assert len(skip) < 260     # 跳过的只是认关键词的字、给大模型的提示词与工具说明、正则


def test_hub_errors_have_english():
    """第三批（D-9）：各接口的报错都有英文（hub/i18n_en.json），按请求语言返回"""
    sys.path.insert(0, os.path.join(WEB, "tools"))
    import backend_texts as B
    from hub import i18n
    tpl = {z for z, _ in i18n._TABLE["templates"]}
    missing = [k for k in B.errors() if k not in i18n.EXACT and k not in tpl]
    assert len(missing) <= ALLOW, missing[:20]
    assert i18n.tr("实验 7 只在减速器厂") == "Lab 7 is only in the reducer plant"
    assert i18n.tr("实验 24 只在机器人厂") == "Lab 24 is only in the robot plant"
    assert i18n.tr("本小时已问了 20 次，请 13 分钟后再问") == "You have asked 20 times this hour; ask again in 13 minutes"
    assert i18n.tr("实验 7 只在减速器厂", "zh") == "实验 7 只在减速器厂"      # 中文界面原样


def test_lab7_only_in_reducer_plant(monkeypatch):
    """第三批 D-12：别的厂打开实验 7（/api/teach）回 404“实验 7 只在减速器厂”，不再 500"""
    from fastapi import HTTPException
    from hub import app as A
    monkeypatch.setattr(A.F, "ITEMS", {"WQ-CR5": ("协作机器人",)})
    with pytest.raises(HTTPException) as e:
        A._lab7_here()
    assert e.value.status_code == 404 and e.value.detail == "实验 7 只在减速器厂"


# —— 第四批（细则 D-13、D-14）：英文帮助稿 ——
HELP = os.path.join(WEB, "src", "help")
FENCE = re.compile(r"^```(\w+)\n(.*?)^```", re.M | re.S)
KEEP = ("name", "tour", "action", "kind", "id", "preset", "domain", "height")     # 这些字段英文稿不改


def _blocks(md):
    out = []
    for kind, body in FENCE.findall(md):
        keys = tuple(ln for ln in body.splitlines() if ln.split(":")[0].strip() in KEEP)
        out.append((kind, keys))
    return out


def _en_chapters():
    for ed in sorted(os.listdir(HELP)):
        d = os.path.join(HELP, ed, "en")
        if os.path.isdir(d):
            for f in sorted(os.listdir(d)):
                if f.endswith(".md"):
                    yield ed, f


def test_en_help_matches_zh():
    """英文章节：中文稿得有；块的种类、顺序和 name/tour/id 等字段跟中文稿一样；问答的 more 锚点在英文稿里有这个标题。"""
    n = 0
    for ed, f in _en_chapters():
        zh = os.path.join(HELP, ed, f)
        assert os.path.exists(zh), "英文稿没有对应的中文稿：{}/en/{}".format(ed, f)
        a, b = open(zh, encoding="utf-8").read(), open(os.path.join(HELP, ed, "en", f), encoding="utf-8").read()
        assert _blocks(a) == _blocks(b), "块和中文稿对不上：{}/en/{}".format(ed, f)
        assert ("\n:::查表" in a) == ("\n:::查表" in b), "查表分隔：" + f
        heads = set(re.findall(r"^#+\s+(.+?)\s*$", b, re.M))
        for anchor in re.findall(r"^more:\s*#(.+?)\s*$", b, re.M):
            assert anchor in heads, "{}/en/{}：more 指向的标题不存在：{}".format(ed, f, anchor)
        assert not CJK.search(re.sub(r":::查表|\{\{厂名\}\}", "", b)), "英文稿里还有中文：{}/en/{}".format(ed, f)
        n += 1
    # 8 册 62 章（第四批 b 第一次推送）。企业版帮助两边各写各的（SYNC.md 的 sync-own）：freecad-ai-parts 那边的企业版是全套中文、
    # 还没有英文稿，所以共有的 7 册必须全有英文（56 章），企业版有 en/ 的那边也要每章都有（第 139 轮 139h 同步时改）
    shared = ("chip", "motor", "pcb", "robot", "sensor", "sewing", "teach")
    for ed in sorted(os.listdir(HELP)):
        zh = {f for f in os.listdir(os.path.join(HELP, ed)) if re.match(r"\d\d-.*\.md$", f)} if os.path.isdir(os.path.join(HELP, ed)) else set()
        if ed in shared or os.path.isdir(os.path.join(HELP, ed, "en")):
            en = set(os.listdir(os.path.join(HELP, ed, "en"))) if os.path.isdir(os.path.join(HELP, ed, "en")) else set()
            assert zh <= en, "{} 册缺英文稿：{}".format(ed, sorted(zh - en))
    assert n >= 56 + (6 if os.path.isdir(os.path.join(HELP, "enterprise", "en")) else 0)


def test_docs_en_pending():
    """每份中文资料要么有英文稿，要么在待译表里；待译表里的东西真实存在、还没译（表只许变短）。"""
    P = json.load(open(os.path.join(WEB, "tools", "docs_en_pending.json"), encoding="utf-8"))
    pend = set(P["help_chapters"]) | set(P["reference_docs"]) | set(P["lab_guides"])
    missing = []
    for ed in sorted(os.listdir(HELP)):
        d = os.path.join(HELP, ed)
        if os.path.isdir(d):
            for f in sorted(os.listdir(d)):
                if f.endswith(".md") and not os.path.exists(os.path.join(d, "en", f)) and "{}/{}".format(ed, f) not in pend:
                    missing.append("{}/{}".format(ed, f))
    hd = os.path.join(DIG, "help")
    for f in sorted(os.listdir(hd)):
        if f.endswith(".md") and not f.endswith(".en.md") and not os.path.exists(os.path.join(hd, f[:-3] + ".en.md")) and f not in pend:
            missing.append("help/" + f)
    for f in sorted(os.listdir(DIG)):
        if f.startswith("实验") and f.endswith(".md") and f not in pend:
            missing.append(f)
    assert len(missing) <= ALLOW, "这些中文资料既没有英文稿，也不在 web/tools/docs_en_pending.json：{}".format(missing)
    stale = [x for x in P["help_chapters"] if os.path.exists(os.path.join(HELP, x.split("/")[0], "en", x.split("/")[1]))]
    stale += [x for x in P["reference_docs"] if os.path.exists(os.path.join(hd, x[:-3] + ".en.md"))]
    assert not stale, "已经有英文稿，从待译表删掉：{}".format(stale)
    assert len(pend) <= 49, "待译表只许变短（第四批 a 收尾时 93 份，b 第一次推送后 49 份）"
