# -*- coding: utf-8 -*-
"""数控编程的 AI（第 13 轮 C7）：一句话编程（只改编程单，人确认后才生成）、逐段讲解 G 代码、指出风险。
和第 11、12 轮一样：有模型时由模型理解（国内 DeepSeek，美国 Claude），没有或出错时用规则兜底；规则保证每一段都有讲解。"""
import json
import math
import re

NUM = r"(\d+(?:\.\d+)?)"
CN_NUM = {"一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}

# 一句话能改的项：路径 → 中文名（网页按路径写回编程单）
PATHS = {
    "turn": {"cut.vc": "切削速度 vc（m/min）", "cut.f": "进给量 f（mm/r）", "cut.ap": "每刀切深 ap（mm）", "cut.max_rpm": "限速 G50（r/min）",
             "cut.axial_allow": "轴肩留余量（mm）", "cut.radial_allow": "外圆再留余量（单边 mm）", "setups": "装夹"},
    "slot": {"cut.vc": "切削速度 vc（m/min）", "cut.fz": "每齿进给 fz（mm）", "cut.z": "齿数", "cut.ap": "每层切深（mm）", "depth": "槽深（mm）"},
    "mill25": {"ops.*.cut.vc": "各工步切削速度 vc（m/min）", "ops.*.cut.fz": "各铣削工步每齿进给 fz（mm）", "ops.*.cut.ap": "各铣削工步每层切深（mm）",
               "ops.pocket.tool.d": "型腔刀具直径（mm）", "ops.pocket.cut.stepover": "型腔行距（×刀径）", "ops.drill.peck": "啄钻每次深度（mm）"},
}


def _n(s):
    m = re.search(NUM, s)
    if m:
        return float(m.group(1))
    for w, v in CN_NUM.items():
        if w in s:
            return float(v)
    return None


def rules_setup(text, spec):
    kind = spec.get("kind")
    out, notes, miss = [], [], []

    def put(path, value, clause):
        out.append({"path": path, "value": value, "label": PATHS[kind].get(path, path)})
        notes.append("“{}” → {} = {:g}".format(clause, PATHS[kind].get(path, path), value) if not isinstance(value, list)
                     else "“{}” → {} = {}".format(clause, PATHS[kind].get(path, path), "、".join(value)))

    t = text.replace("：", ":").replace("（", "(").replace("）", ")").replace("Φ", "Ø").replace("φ", "Ø")
    for clause in [c.strip() for c in re.split(r"[，,；;。\n]", t) if c.strip()]:
        c = clause.replace(" ", "")
        hit = False
        m = re.search(r"分" + r"(\d+|[一两二三四五六七八九十])" + r"层", c)
        if m and kind == "slot":
            n = _n(m.group(1))
            put("cut.ap", round(spec["depth"] / n + 1e-4, 4), clause)
            hit = True
        m = re.search(r"(?:每刀|每层|切深|背吃刀量|吃刀|ap)(?:为|=|:)?" + NUM, c, re.I)
        if m:
            v = float(m.group(1))
            put("ops.*.cut.ap" if kind == "mill25" else "cut.ap", v, clause)
            hit = True
        m = re.search(r"(?:每齿进给|每齿|fz)(?:为|=|:)?" + NUM, c, re.I)
        if m and kind in ("slot", "mill25"):
            put("ops.*.cut.fz" if kind == "mill25" else "cut.fz", float(m.group(1)), clause)
            hit = True
        m = re.search(r"(?:进给量|走刀量|进给|f)(?:为|=|:)?" + NUM + r"(mm/r|mm/min)?", c, re.I)
        if m and not re.search(r"每齿|fz", c, re.I) and kind == "turn":
            if m.group(2) == "mm/min":
                miss.append(clause + "（车削进给按每转 mm/r 写，例如“进给 0.2”）")
            else:
                put("cut.f", float(m.group(1)), clause)
            hit = True
        m = re.search(r"(?:线速度|切削速度|vc)(?:为|=|:)?" + NUM, c, re.I)
        if m:
            put("ops.*.cut.vc" if kind == "mill25" else "cut.vc", float(m.group(1)), clause)
            hit = True
        m = re.search(r"(?:限速|最高转速|G50)(?:为|=|:|S)?" + NUM, c, re.I)
        if m and kind == "turn":
            put("cut.max_rpm", float(m.group(1)), clause)
            hit = True
        elif re.search(r"转速(?:为|=|:)?" + NUM, c) and not hit:
            n = float(re.search(r"转速(?:为|=|:)?" + NUM, c).group(1))
            d = spec.get("tool", {}).get("d") if kind == "slot" else None
            if d:
                put("cut.vc", round(math.pi * d * n / 1000, 1), clause)
            else:
                miss.append(clause + "（车削用恒线速 G96，请说切削速度，例如“线速度 150”）")
            hit = True
        m = re.search(r"轴肩(?:留|余量)" + NUM, c)
        if m and kind == "turn":
            put("cut.axial_allow", float(m.group(1)), clause)
            hit = True
        elif kind == "turn" and re.search(r"留" + NUM + r"(?:mm)?(?:的)?(?:精车|精加工)?余量|(?:单边|直径)留" + NUM, c):
            mm = re.search(r"留" + NUM, c)
            v = float(mm.group(1)) / (2 if "直径" in c else 1)
            if spec.get("mode") == "finish":
                miss.append(clause + "（精车不留余量；要给磨削留量请改工艺规程的精车尺寸）")
            else:
                put("cut.radial_allow", v, clause)
                notes.append("说明：工艺规程的粗车尺寸已经含精车余量，这里是在它之外再留 {:g} mm（单边），提交时会提示与工艺规程不一致".format(v))
            hit = True
        if kind == "turn" and re.search(r"只(?:车|编|加工)?右", c):
            put("setups", ["right"], clause)
            hit = True
        elif kind == "turn" and re.search(r"只(?:车|编|加工)?左|只(?:编)?调头", c):
            put("setups", ["left"], clause)
            hit = True
        m = re.search(r"(?:Ø|直径|D)" + NUM + r"(?:mm)?(?:的)?(?:立铣刀|铣刀|刀)", c) or re.search(r"(?:刀具|铣刀|立铣刀)(?:用|换成|为)?Ø?" + NUM, c)
        if m and kind == "mill25":
            put("ops.pocket.tool.d", float(m.group(1)), clause)
            hit = True
        m = re.search(r"行距" + NUM + r"(%)?", c)
        if m and kind == "mill25":
            v = float(m.group(1))
            put("ops.pocket.cut.stepover", v / 100 if m.group(2) or v > 1 else v, clause)
            hit = True
        m = re.search(r"啄钻(?:每次)?" + NUM, c)
        if m and kind == "mill25":
            put("ops.drill.peck", float(m.group(1)), clause)
            hit = True
        if not hit:
            if re.search(r"粗车|精车|车外圆|铣键槽|铣槽|型腔|钻孔|编程|外轮廓", c):
                notes.append("“{}” → 工序 / 工步已由编程单确定".format(clause))
            else:
                miss.append(clause)
    return {"patch": out, "notes": notes, "unmatched": miss}


SETUP_TOOL = {
    "name": "fill_cam_setup",
    "description": "把一句话变成对编程单的修改",
    "input_schema": {"type": "object", "required": ["patch"], "properties": {
        "patch": {"type": "array", "items": {"type": "object", "required": ["path", "value"], "properties": {
            "path": {"type": "string", "description": "只能用给出的可改项路径"},
            "value": {"description": "数字；setups 是 [\"right\"] / [\"left\"] / [\"right\",\"left\"]"}}}},
        "notes": {"type": "array", "items": {"type": "string"}, "description": "每条说明哪句话改成了哪一项"},
        "unmatched": {"type": "array", "items": {"type": "string"}, "description": "没看懂或不能改的话"}}},
}


def setup(llm, text, spec):
    text = (text or "").strip()[:500]
    if not text:
        raise ValueError("请写一句话，例如“每刀 2.5，留 0.3 精车余量”")
    kind = spec.get("kind")
    if kind not in PATHS:
        raise ValueError("请先排好编程单")
    if llm is not None and llm.available():
        got = {}

        def call_tool(name, args):
            got.update(args)
            return {"ok": True}
        ctx = {"sentence": text, "kind": kind, "mode": spec.get("mode"), "editable": PATHS[kind], "current": {
            "cut": spec.get("cut"), "depth": spec.get("depth"), "setups": spec.get("setups"),
            "ops": [{"type": o["type"], "tool_d": o["tool"]["d"], "cut": o["cut"]} for o in spec.get("ops") or []]}}
        system = ("你是数控编程助手。把用户的一句话变成对编程单的修改，调用 fill_cam_setup 一次。只能改 editable 里列的项，"
                  "车削进给用 mm/r、切削速度 m/min；“分 N 层”是每层切深 = 槽深 / N；“留 x 精车余量”是 cut.radial_allow（单边）。"
                  "说到工序名称（粗车、铣键槽）不用改任何项；不确定的写进 unmatched，不要猜。")
        try:
            llm.run(system, [{"role": "user", "content": json.dumps(ctx, ensure_ascii=False)}], [SETUP_TOOL], call_tool, max_turns=2)
            ok = []
            for p in got.get("patch") or []:
                if p.get("path") in PATHS[kind]:
                    v = p["value"]
                    if p["path"] == "setups":
                        v = [x for x in (v if isinstance(v, list) else [v]) if x in ("right", "left")]
                        if not v:
                            continue
                    else:
                        try:
                            v = float(v)
                        except (TypeError, ValueError):
                            continue
                        if not 0 < v < 1e5:
                            continue
                    ok.append({"path": p["path"], "value": v, "label": PATHS[kind][p["path"]]})
            if ok or got.get("unmatched"):
                return {"patch": ok, "notes": got.get("notes") or [], "unmatched": got.get("unmatched") or [], "engine": llm.name}
        except Exception as e:  # noqa: BLE001
            return dict(rules_setup(text, spec), engine="rules", note="模型暂时不可用（{}），已用规则理解".format(str(e)[:60]))
    return dict(rules_setup(text, spec), engine="rules")


# ---------------------------------------------------------------- 逐段讲解 G 代码
G_MEAN = {"G00": "快速移动（不切削）", "G01": "直线切削", "G02": "顺时针圆弧", "G03": "逆时针圆弧", "G17": "XY 平面", "G18": "ZX 平面（车床）",
          "G21": "公制（mm）", "G40": "取消刀具半径补偿", "G43": "刀具长度补偿", "G49": "取消长度补偿", "G50": "限制最高转速（车床）",
          "G54": "工件坐标系 1", "G80": "取消钻孔循环", "G81": "钻孔循环（一次钻到底）", "G83": "啄式钻孔循环（分次钻、退刀排屑）",
          "G90": "绝对坐标", "G91": "增量坐标", "G94": "每分钟进给（mm/min）", "G96": "恒线速（m/min，直径变小转速自动升高）",
          "G97": "恒转速（r/min）", "G98": "车床：每分钟进给；铣床：钻孔后回到起始平面", "G99": "车床：每转进给（mm/r）；铣床：钻孔后回到 R 平面",
          "G28": "回参考点（机床原点）", "M03": "主轴正转", "M05": "主轴停", "M06": "换刀", "M08": "开冷却液", "M09": "关冷却液", "M30": "程序结束并返回开头"}
STEP_WORDS = ("车端面", "分层粗车", "沿留余量", "精车轮廓", "切槽", "铣槽", "铣型腔", "铣外轮廓", "钻孔")


def _codes(line):
    return [w for w in re.findall(r"[GM]\d+", line.split("(")[0].upper())]


def blocks(nc):
    """按程序结构分段：程序头、安全行、每把刀（换刀与主轴）、每个工步（注释开头）、结尾。每一行都落在某一段里"""
    lines = nc.rstrip("\n").split("\n")
    marks = []
    for i, l in enumerate(lines):
        s = l.strip()
        if i == 0:
            marks.append((i, "head"))
        elif re.match(r"G21\b", s):
            marks.append((i, "safety"))
        elif s.startswith("(") and i + 1 < len(lines) and (re.match(r"G00 X[\d.]+ Z[\d.]+$", lines[i + 1].strip()) or re.match(r"T\d+ M06", lines[i + 1].strip())):
            marks.append((i, "tool"))                    # 每把刀的标题（后面紧跟回换刀点或换刀）
        elif s.startswith("(") and any(w in s for w in STEP_WORDS):
            marks.append((i, "step"))
        elif re.match(r"G00 X[\d.]+ Z[\d.]+ M09|G00 Z[\d.]+ M09", s):
            marks.append((i, "end"))
    marks.sort()
    out = []
    for k, (i, kind) in enumerate(marks):
        j = marks[k + 1][0] - 1 if k + 1 < len(marks) else len(lines) - 1
        if j >= i:
            out.append({"from": i + 1, "to": j + 1, "kind": kind, "lines": lines[i:j + 1]})
    return out


def _rules_text(b, spec):
    L = b["lines"]
    body = "\n".join(L)
    kind = b["kind"]
    lathe = spec.get("kind") == "turn"
    if kind == "head":
        num = next((x for x in L if x.startswith("O")), "")
        return ("程序头：% 是程序的开始符；{} 是程序号和名称。括号里是注释，机床不执行，写明零件、版本、工序、机床和刀具表，"
                "操作工对照它装刀、对刀。".format(num.split(" ")[0] if num else "O 后面"))
    if kind == "safety":
        codes = _codes(L[0])

        def mean(c):
            m = G_MEAN.get(c, "")
            return m.split("；")[0 if lathe else 1].split("：", 1)[-1] if "；" in m else m
        return "安全行：" + "，".join("{} {}".format(c, mean(c)) for c in codes) + "。每个程序开头都把这些模态指令设一遍，避免沿用上一个程序留下的状态。"
    if kind == "tool":
        t = []
        for x in L:
            s = x.strip()
            if re.match(r"T\d{4}", s):
                t.append("{}：换 {} 号刀、用 {} 号刀补（刀尖位置的补偿值）".format(s, int(s[1:3]), int(s[3:5])))
            elif re.match(r"T\d+ M06", s):
                t.append("{}：换 {} 号刀".format(s, re.match(r"T(\d+)", s).group(1)))
            elif s.startswith("G50 S"):
                t.append("{}：主轴最高转速限制在 {} r/min——恒线速切到小直径时转速会升高，卡盘夹持的工件不能转太快".format(s, s.split("S")[1]))
            elif s.startswith("G96"):
                m = re.search(r"S(\d+)", s)
                t.append("{}：恒线速 {} m/min，主轴正转。转速 n = 1000·vc/(π·D)，随刀尖所在直径自动变化".format(s, m.group(1) if m else ""))
            elif re.match(r"S\d+ M03", s):
                t.append("{}：主轴 {} r/min 正转".format(s, s.split()[0][1:]))
            elif s.startswith("G00 X") and lathe:
                t.append("{}：先回到换刀点（离工件足够远）再换刀".format(s))
            elif s.startswith("G43"):
                t.append("{}：调用长度补偿 H，刀尖停在工件上表面上方 {} mm".format(s, re.search(r"Z([\d.]+)", s).group(1)))
            elif s == "G54":
                t.append("G54：使用工件坐标系 1（对刀时设在工件上表面、键槽中心或零件原点）")
        return "；".join(t) + "。" if t else "换刀与主轴。"
    if kind == "end":
        if not any(x.strip().startswith("M30") for x in L):
            return "这把刀的工步做完：退到安全位置、关冷却液（M09）、主轴停（M05），准备换下一把刀。"
        return ("结尾：退回安全位置并关冷却液（M09），主轴停（M05）；" + ("铣床用 G91 G28 Z0.0 让 Z 轴回参考点，" if not lathe else "") +
                "M30 程序结束、光标回到开头，% 是结束符。")
    title = L[0].strip("() ")
    n_feed = sum(1 for x in L if "G01" in x or (re.match(r"[XYZ]", x.strip()) and "G00" not in x))
    if "车端面" in title:
        k = sum(1 for x in L if "X-1.0" in x)
        return ("{}：刀从外圆外 X 处进到端面位置，G01 横向车过中心（X-1.0，过中心 0.5 mm 不留小凸台），快退。共 {} 刀，"
                "每刀往左一层，最后一刀在 Z0（本次装夹的端面）。".format(title, k))
    if "分层粗车" in title:
        k = sum(1 for x in L if re.match(r"G01 X[\d.]+ Z-", x.strip()) or (re.match(r"G01 Z-", x.strip())))
        return ("{}：每层先快移到 Z2.0（端面外 2 mm）、对准这一层的直径 X，再 G01 沿 Z 向左车到轴肩为止，45° 斜退 0.5 mm 防止刀尖划伤已加工面，"
                "快退回右边；直径每层减 2×ap。和 FANUC 的 G71 循环效果一样，这里展开成直线段，方便看懂。约 {} 层。".format(title, max(k, 1)))
    if "沿留余量" in title:
        return "{}：分层车完，台阶处还留着三角形的残料；沿着本工序轮廓走一刀，把它们去掉，得到均匀的余量。".format(title)
    if "精车轮廓" in title:
        ds = sorted({float(m) for m in re.findall(r"X([\d.]+)", body) if 5 < float(m) < 120})
        return "{}：从端面倒角开始，沿轮廓一刀车出各外圆和轴肩，直径依次 {}（公差带中间）。精车切深小、进给小，表面粗糙度由进给量和刀尖圆弧决定。".format(
            title, "、".join("Ø{:g}".format(d) for d in ds[:6]))
    if "切槽" in title:
        return "{}：切槽刀径向切入到槽底直径，再退出；槽比刀宽时左移一刀宽的 80% 再切一次。".format(title)
    if "铣槽" in title:
        k = sum(1 for x in L if re.match(r"X[-\d.]+ Z-", x.strip()) or re.match(r"G01 X[-\d.]+ Z-", x.strip()))
        return ("{}：先快移到槽一端上方，再一边沿槽长方向走、一边往下（斜线下刀，键槽铣刀不垂直扎刀），到另一端时正好下了一层，"
                "再走回来把这一层铣平。共 {} 层，最后一层到槽深。".format(title, max(k, 1)))
    if "铣型腔" in title:
        return ("{}：每层在型腔中间斜线下刀，然后一圈一圈由里往外铣（刀心沿型腔边界的偏置线走），最外一圈贴着型腔壁；"
                "中间有岛时两圈之间如果直线会碰到岛就抬刀绕过去。".format(title))
    if "铣外轮廓" in title:
        return "{}：刀心在轮廓外偏一个刀具半径，顺铣（主轴正转、刀沿顺时针绕工件），从外面沿法线切入、切出，分层铣到深度。".format(title)
    if "钻孔" in title:
        return ("{}：G98 G83（或 G81）是钻孔循环，一行就是一个孔：快移到 R 平面，钻到 Z 深，G83 每钻 Q 深退回 R 平面排屑；"
                "后面只写 X Y 的行是同样参数的下一个孔，G80 取消循环。".format(title))
    return "{}：{} 行切削。".format(title, n_feed)


def rules_explain(job, k, nc):
    spec = job["spec"]
    p = job["programs"][k]
    bs = blocks(nc)
    out = [{"from": b["from"], "to": b["to"], "title": b["lines"][0].strip()[:60], "text": _rules_text(b, spec)} for b in bs]
    risks = []
    for c in p.get("checks") or []:
        risks.append(("第 {} 行：".format(c["line"]) if c.get("line") else "") + c["text"])
    if spec.get("kind") == "turn":
        risks.append("刀尖圆弧按 0 编程（没用 G41/G42 刀尖半径补偿）：车锥面、倒角时实际轮廓会差一点；精车倒角要求高时加刀尖半径补偿。")
    risks.append("首件试切：快移倍率调到 25%，单段运行走第一刀，确认对刀和坐标系；铣床先在工件上方空走一遍（Z 抬高）。")
    if p.get("sim", {}).get("ap_max") and spec.get("cut", {}).get("ap") and p["sim"]["ap_max"] > float(spec["cut"]["ap"]) + 0.05:
        risks.append("仿真里实际最大切深 {} mm，比编程单的 {} mm 大（多半是端面或轴肩处）：注意那一刀的切削力。".format(
            p["sim"]["ap_max"], spec["cut"]["ap"]))
    return {"blocks": out, "risks": risks, "engine": "rules"}


EXPLAIN_TOOL = {
    "name": "explain_program",
    "description": "逐段讲解数控程序",
    "input_schema": {"type": "object", "required": ["blocks"], "properties": {
        "blocks": {"type": "array", "items": {"type": "object", "required": ["index", "text"], "properties": {
            "index": {"type": "integer"}, "text": {"type": "string", "description": "1–3 句中文：这段在干什么、为什么这样写（指令含义、参数从哪来）"}}}},
        "risks": {"type": "array", "items": {"type": "string"}, "description": "这个程序上机要注意的风险，没有就空"}}},
}


def explain(llm, job, k, nc):
    base = rules_explain(job, k, nc)
    if llm is None or not llm.available():
        return base
    got = {}

    def call_tool(name, args):
        got.update(args)
        return {"ok": True}
    bs = blocks(nc)
    ctx = {"machine": job["spec"].get("machine"), "kind": job["spec"].get("kind"), "mode": job["spec"].get("mode"),
           "cut": job["spec"].get("cut"), "checks": job["programs"][k].get("checks"),
           "blocks": [{"index": i, "lines": "\n".join(b["lines"][:40]) + ("\n…（共 {} 行）".format(len(b["lines"])) if len(b["lines"]) > 40 else ""),
                       "rule_note": base["blocks"][i]["text"]} for i, b in enumerate(bs)]}
    try:
        llm.run("你是数控加工课的老师，给学生逐段讲解 FANUC 数控程序。每一段都要讲（index 对应），只根据给出的程序和参数；调用 explain_program 一次。",
                [{"role": "user", "content": json.dumps(ctx, ensure_ascii=False)[:14000]}], [EXPLAIN_TOOL], call_tool, max_turns=2)
    except Exception:  # noqa: BLE001
        return base
    texts = {int(b.get("index", -1)): str(b.get("text") or "").strip() for b in got.get("blocks") or []}
    if not texts:
        return base
    for i, b in enumerate(base["blocks"]):
        if texts.get(i):
            b["text"] = texts[i]
    risks = [r for r in got.get("risks") or [] if isinstance(r, str) and r.strip()]
    return {"blocks": base["blocks"], "risks": base["risks"][:len(job["programs"][k].get("checks") or [])] + risks or base["risks"],
            "engine": llm.name}
