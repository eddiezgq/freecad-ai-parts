# -*- coding: utf-8 -*-
"""第 130 轮：数字工厂英文版——枢纽这边的语言（细则 D-2、D-3）。

网页每个请求带 x-wq-lang（zh / en），直接 fetch 的文件和下载带 cookie wq_lang；都没有就是中文（原来的样子）。
第一批只翻首页看板（/api/overview）里枢纽自己拼的文字、第一批页面会遇到的报错；其余提示与记录第三批再做。
厂名、设备名、物料名：工厂清单里本来就是“中文 English”合写或有 name_en，这里给出 name_en 字段，网页按语言取。
AI 简报、提醒正文、实验任务说明仍是中文（第三批）。
"""
import json
import os
import re

LANGS = ("zh", "en")


def lang_of(request):
    """请求的语言：x-wq-lang 头 → cookie wq_lang → 中文"""
    if request is None:
        return "zh"
    v = (request.headers.get("x-wq-lang") or request.cookies.get("wq_lang") or "").strip().lower()
    return v if v in LANGS else "zh"


_CJK = re.compile(r"[　-〿㐀-鿿＀-￯]")


def has_cjk(s):
    return bool(s) and bool(_CJK.search(str(s)))


def en_part(name):
    """中英合写的名字取英文部分（与网页 lib/i18n-core.js 的 enPart 同一规则）"""
    s = str(name or "").strip()
    if not has_cjk(s):
        return s
    toks = s.split()
    last = max((i for i, t in enumerate(toks) if has_cjk(t)), default=-1)
    rest = toks[last + 1:]
    while len(rest) > 1 and rest[0] in rest[1:]:
        rest = rest[1:]
    return " ".join(rest)


# ---------------------------------------------------------------- 固定文字
EXACT = {
    # 看板：指标
    "准时交付率（本月）": "On-time delivery (month)", "在制品": "Work in progress", "设备综合效率 OEE（今日）": "OEE (today)",
    "一次合格率（本周）": "First-pass yield (week)", "实际成本偏差（本周）": "Cost variance (week)",
    "与标准成本一致": "In line with standard cost", "本周尚无加工": "No machining this week yet", "本周尚未检验": "Nothing inspected this week yet",
    "件": "pcs",
    # 订单
    "待排产": "Unscheduled", "有风险": "At risk", "正常": "On track", "尚未下达工单": "No work order released yet",
    # 物料
    "无库存数据": "No stock data", "低于安全库存": "Below safety stock", "不够本批需求": "Short for this batch",
    # 质量图
    "SH-301 轴承位 Ø35k6": "SH-301 bearing seat Ø35k6",
    # 提醒与待办
    "已完成": "Done", "任务": "Task", "AI 提议": "AI proposal", "质量": "Quality", "紧急": "Urgent", "提醒": "Alert", "提示": "Note",
    "查看": "View", "去做": "Go", "预览并确认": "Preview & confirm", "评审": "Review",
    # 周几
    "周一": "Mon", "周二": "Tue", "周三": "Wed", "周四": "Thu", "周五": "Fri", "周六": "Sat", "周日": "Sun",
    # 报错（第一批页面会遇到的）
    "请先登录": "Please sign in first", "角色或模式不对": "Invalid role or mode",
    "学生只能选学生岗位、用教学模式；老师请勾“我是老师”并输老师密码":
        "Students can only pick student roles in teaching mode; teachers, tick “I'm a teacher” and enter the teacher password",
    "功能测试台只在电路板厂": "The functional test bench is only in the PCB plant",
    "没有这个操作": "No such action", "没有这台设备": "No such machine", "没有这个文件": "No such file",
    "请用一句话说需求，例如：35 mm 轴、1450 r/min、径向载荷为主用什么轴承":
        "Describe the need in one sentence, e.g. which bearing for a 35 mm shaft at 1450 r/min, mainly radial load",
    "需求请写短一些（500 字以内）": "Please keep the request short (under 500 characters)",
}

_DRIVER = {"调整与换刀工时": "setup and tool-change time", "加工超时": "machining overrun"}

PATTERNS = [
    (r"^目标 (\d+)% · (\d+) 单延期风险$", lambda m: "Target {}% · {} order(s) at risk".format(m[1], m[2])),
    (r"^本月尚无交付 · (\d+) 单延期风险$", lambda m: "No deliveries this month · {} order(s) at risk".format(m[1])),
    (r"^比昨天 ([+-]?\d+)（(\S+) 前排队 (\d+) 件）$", lambda m: "{} vs yesterday ({} queued at {})".format(m[1], m[3], m[2])),
    (r"^比昨天 ([+-]?\d+)$", lambda m: "{} vs yesterday".format(m[1])),
    (r"^目标 (\d+)% · (\S+) 仅 (\d+)%$", lambda m: "Target {}% · {} only {}%".format(m[1], m[2], m[3])),
    (r"^目标 (\d+)% · 今日尚未开机$", lambda m: "Target {}% · no machine running yet today".format(m[1])),
    (r"^目标 (\d+)% · (达标|未达标) · (\d+) 件$",
     lambda m: "Target {}% · {} · {} pcs".format(m[1], "met" if m[2] == "达标" else "not met", m[3])),
    (r"^本周完工 (\S+)$", lambda m: "Completed this week: {}".format(m[1])),
    (r"^计划到今天 (\d+) 件$", lambda m: "Planned to date: {} pcs".format(m[1])),
    (r"^每件高 \$(\d+) · 主要是(.+)$", lambda m: "${} over per unit · mainly {}".format(m[1], _DRIVER.get(m[2], m[2]))),
    (r"^预计晚 (\d+) 天$", lambda m: "Projected {} day(s) late".format(m[1])),
    (r"^待排产，缺 (\S+)$", lambda m: "Unscheduled, short {}".format(m[1])),
    (r"^(\S+) 到货$", lambda m: "Arriving {}".format(m[1])),
    (r"^约 (\d+) 天$", lambda m: "About {} days".format(m[1])),
    (r"^任务 · 得 (\d+) 分$", lambda m: "Task · {} points".format(m[1])),
    (r"^实验 7 · (.+)$", lambda m: "Lab 7 · {}".format(m[1])),
    (r"^不合格品 (\S+)：(\S+) (.+) 超差$", lambda m: "Nonconformance {}: {} {} out of tolerance".format(m[1], m[2], m[3])),
    (r"^没有这块板的功能测试记录：(.+)$", lambda m: "No functional test record for this board: {}".format(m[1])),
]
PATTERNS = [(re.compile(p), f) for p, f in PATTERNS]


# 第三批（细则 D-9）：各接口的报错，表在 hub/i18n_en.json：{"exact": {中文: 英文}, "templates": [[中文句型, 英文句型], …]}
# 句型里变的部分写 {a} {b} …，整句对上后占位里的中文再换一遍（与网页 lib/i18n-core.js 的句型表同一规则）
_TABLE = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "i18n_en.json"), encoding="utf-8"))
EXACT.update(_TABLE.get("exact", {}))


def _compile(lst):
    out = []
    for zh, en in lst:
        lits = re.split(r"\{[a-z]\}", zh)
        names = re.findall(r"\{([a-z])\}", zh)
        if not names:
            EXACT.setdefault(zh, en)
            continue
        src = re.escape(lits[0]) + "".join(r"([\s\S]*?)" + re.escape(lits[i + 1]) for i in range(len(names)))
        out.append(((re.compile("^" + src + "$"), re.compile("^" + src.replace("*?)", "\0", 1).replace("*?)", "*)").replace("\0", "*?)") + "$"),
                     re.compile("^" + src.replace("*?)", "*)") + "$")), names, en, max(lits, key=len), len("".join(lits))))
    return sorted(out, key=lambda x: -x[4])


TEMPLATES = _compile(_TABLE.get("templates", []))


def tr(s, lang="en", _depth=0):
    """一句话译成英文；没有对照的原样返回（中文）"""
    if lang != "en" or not isinstance(s, str) or not has_cjk(s):
        return s
    if s in EXACT:
        return EXACT[s]
    for rx, f in PATTERNS:
        m = rx.match(s)
        if m:
            return f(m)
    if _depth < 4:
        for rxs, names, en, key, _w in TEMPLATES:
            if key and key not in s:
                continue
            for rx in rxs:                  # 先最短、再最长地分占位
                m = rx.match(s)
                if not m:
                    continue
                vals = {n: tr(m.group(i + 1), "en", _depth + 1) for i, n in enumerate(names)}
                if any(has_cjk(v) for v in vals.values()):
                    continue
                return re.sub(r"\{([a-z])\}", lambda mm: vals.get(mm.group(1), mm.group(0)), en)
    return s


def _wo_text(s):
    """“WO-… SH-301 已完工 3/10；…” → “WO-… SH-301 done 3/10; …”"""
    if s == "尚未下达工单":
        return EXACT[s]
    return "; ".join(re.sub(r" 已完工 ", " done ", x) for x in s.split("；"))


def _qty_text(s):
    s = re.sub(r" 件( |$)", r" pcs\1", s)
    return s.replace(" · 在途 ", " · in transit ")


def localize_overview(ov, lang, units=None):
    """首页看板：英文时把枢纽拼的文字换成英文，并给设备、物料加 name_en（原字段不动，网页按语言取）"""
    units = units or {}
    for m in ov.get("machines", []):
        u = units.get(m.get("unit"))
        if u:
            m["name_en"] = u[2]
    wk = ov.get("week") or {}
    if wk.get("bottleneck") and units.get(wk["bottleneck"]):
        wk["bottleneck_name_en"] = units[wk["bottleneck"]][2]
    if lang != "en":
        return ov
    for k in ov.get("kpis", []):
        k["label"] = tr(k.get("label"))
        k["note"] = tr(k.get("note"))
        if k.get("unit"):
            k["unit"] = tr(k["unit"])
    for o in ov.get("orders", []):
        o["risk"] = tr(o.get("risk"))
        if isinstance(o.get("work_orders"), str):
            o["work_orders"] = _wo_text(o["work_orders"])
    for x in ov.get("materials", []):
        x["status"] = tr(x.get("status"))
        if isinstance(x.get("qty_text"), str):
            x["qty_text"] = _qty_text(x["qty_text"])
        if x.get("uom"):
            x["uom"] = tr(x["uom"])
    for d in wk.get("days", []):
        d["day"] = tr(d.get("day"))
    if "weekday" in ov:
        ov["weekday"] = tr(ov["weekday"])
    ch = (ov.get("quality") or {}).get("chart") or {}
    if ch.get("title"):
        ch["title"] = tr(ch["title"])
    for t in ov.get("todos", []):
        for f in ("kind", "act", "src", "text"):
            if isinstance(t.get(f), str):
                t[f] = tr(t[f])
    return ov


def localize_detail(detail, lang):
    """HTTPException 的 detail（报错文字）"""
    return tr(detail, lang) if isinstance(detail, str) else detail


# ---------------------------------------------------------------- 实验作答的关键词（第三批）
# 实验 7、15–22 的“理由”按关键词给分；英文界面的学生用英文写，同一个意思的英文词也认
KW_EN = {
    "交期": ("due", "deliver", "schedule", "lead time"), "按时": ("on time", "on-time"), "晚": ("late", "delay"),
    "成本": ("cost",), "钱": ("money", "$", "cost", "spend"), "费": ("fee", "cost", "expens", "pay"),
    "风险": ("risk",), "客户": ("customer", "client"), "保修": ("warranty",), "安全": ("safe",), "伤": ("injur", "hurt"),
    "概率": ("probab", "chance"), "可能": ("likel", "possib", "probab"), "损失": ("loss", "lose"),
    "订单": ("order",), "产量": ("output", "throughput", "volume"), "少做": ("fewer", "less output", "lost parts"), "件": ("part", "pcs", "piece"),
    "加班": ("overtime",), "班": ("shift",), "到料": ("arriv", "material"), "等": ("wait",), "贵": ("expensive", "pricier", "premium"),
    "质量": ("quality",), "度": ("kwh",), "电": ("electric", "energy", "power"), "预热": ("warm",), "慢": ("slow",),
    "现金": ("cash",), "收": ("collect", "receiv"), "款": ("payment", "invoice"), "关系": ("relationship", "relation"),
    "发货": ("ship",), "调整": ("setup", "set-up", "adjust"), "换刀": ("tool change", "tool-change"), "准备": ("prepar",), "装夹": ("clamp", "fixtur"),
}


def has_kw(text, words):
    """作答里有没有这些关键词之一（中文原词，或它的英文说法，不分大小写）"""
    t = str(text or "")
    low = t.lower()
    return any(w in t or any(e in low for e in KW_EN.get(w, ())) for w in words)
