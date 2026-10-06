# -*- coding: utf-8 -*-
"""AI 设计评审员（第 11 轮《机械设计》2.7（4）（5））：按工程任务单的交付物逐项检查，只提意见、给建议分，不批准。

只用规则（与 AI 工艺评审员一样），规则写出的意见本身就是通顺的中文；以后要接模型，模型只改写措辞。
检查的都是“有没有、齐不齐、对不对得上”，设计好不好、每一步算得对不对，由老师判断。

    findings = review(spec, deliverables, get_file=..., get_design=..., get_job=..., get_process=...)
    每条意见：{"rule": 类别, "level": "error" | "warning" | "info", "d": 交付物序号（0 起）或 None, "text": ...}

交付物的数据（任务单提交里的 deliverables，键是序号字符串）：
    文件      {"kind": "文件", "files": [{"name", "url", "size"}]}
    设计发布  {"kind": "设计发布", "plm": 提交编号}
    分析      {"kind": "分析", "job": 作业编号}
    工艺规程  {"kind": "工艺规程", "process": 提交编号}
    更改单    {"kind": "更改单", "rows": [{"item", "change", "reason"}]}
"""
import io
import math
import re

AI_REVIEWER = "AI 设计评审员"

# 62 系列深沟球轴承 GB/T 276：d、B、r_smin（mm），与《机械设计》std/gbt276_6200.yaml 同一来源
BEARINGS = {"6204": (20, 14, 1.0), "6205": (25, 15, 1.0), "6206": (30, 16, 1.0), "6207": (35, 17, 1.1),
            "6208": (40, 18, 1.1), "6209": (45, 19, 1.1), "6210": (50, 20, 1.1), "6211": (55, 21, 1.5),
            "6212": (60, 22, 1.5)}
OPS = {">=": lambda a, b: a >= b, ">": lambda a, b: a > b, "<=": lambda a, b: a <= b, "<": lambda a, b: a < b}
PASS_WORDS = ("合格", "满足", "通过", "pass", "ok", "✓", "√")
FAIL_WORDS = ("不合格", "不满足", "不通过", "fail", "✗", "×")


def suggested_score(findings):
    """100 − 10 × 必改 − 3 × 建议，不低于 0（与工艺评审员同一算法）"""
    e = sum(f["level"] == "error" for f in findings)
    w = sum(f["level"] == "warning" for f in findings)
    return max(0, 100 - 10 * e - 3 * w)


def rubric_split(spec, total):
    """建议分按评分量规各项分值比例分到各项（整数，合计等于 total）"""
    items = spec.get("评分") or []
    raw = [x["分"] * total / 100 for x in items]
    out = [math.floor(v) for v in raw]
    for i in sorted(range(len(raw)), key=lambda i: raw[i] - out[i], reverse=True)[:round(total - sum(out))]:
        out[i] += 1
    return out


def _say(out, rule, level, d, text):
    out.append({"rule": rule, "level": level, "d": d, "text": text})


def _num(s):
    m = re.search(r"[-+]?\d+(?:[.,]\d+)?(?:[eE][-+]?\d+)?", (s or "").replace("，", ","))
    return float(m.group(0).replace(",", ".")) if m else None


# ---------------------------------------------------------------- 计算书（Word，CalcSheet 格式）
def calc_tables(data):
    """读 Word 计算书，返回 (计算行, 校核行)；不是计算书格式返回 None"""
    from docx import Document
    try:
        doc = Document(io.BytesIO(data))
    except Exception:  # noqa: BLE001
        return None
    steps, checks = None, None
    for t in doc.tables:
        head = [c.text.strip() for c in t.rows[0].cells]
        h = " ".join(head)
        rows = [[c.text.strip() for c in r.cells] for r in t.rows[1:]]
        if ("公式" in h or "Formula" in h) and ("结果" in h or "Result" in h) and len(head) >= 5:
            steps = rows
        elif ("要求" in h or "Requirement" in h) and ("计算值" in h or "Value" in h) and len(head) >= 4:
            checks = rows
    if steps is None:
        return None
    return steps, checks or []


def check_calc(data, d, out, name="计算书"):
    t = calc_tables(data)
    if t is None:
        _say(out, "计算书", "error", d, "{}不是任务单发的计算书格式（找不到“公式、代入、结果、出处”表），请用空白计算书填写。".format(name))
        return
    steps, checks = t
    blank_res, blank_sub, no_src = [], [], []
    for r in steps:
        item, formula, subst, result, src = (r + [""] * 5)[:5]
        label = item or formula[:20]
        rhs = result.split("=", 1)[1].strip() if "=" in result else result.strip()
        if not rhs:
            blank_res.append(label)
        elif not subst and "查表" not in formula:
            blank_sub.append(label)
        if "查表" in formula and not src:
            no_src.append(label)
    if blank_res:
        _say(out, "计算书", "error", d, "{} 项计算没有结果：{}。".format(len(blank_res), "、".join(blank_res[:6]) + ("……" if len(blank_res) > 6 else "")))
    if blank_sub:
        _say(out, "计算书", "warning", d, "{} 项计算只写了结果、没写代入过程：{}。代入要写出来，审核的人才能核对。".format(
            len(blank_sub), "、".join(blank_sub[:6]) + ("……" if len(blank_sub) > 6 else "")))
    if no_src:
        _say(out, "计算书", "error", d, "查表得到的数值没有写出处（标准号、表号或书名章节）：{}。".format("、".join(no_src[:6])))
    if not checks:
        _say(out, "计算书", "error", d, "没有“校核与结论”表，任务单要求的校核项一项也没有。")
    for r in checks:
        what, req, val, res = (r + [""] * 4)[:4]
        if not val:
            _say(out, "计算书", "error", d, "校核“{}”没有填计算值。".format(what))
            continue
        m = re.match(r"\s*(.+?)\s*(>=|<=|>|<|≥|≤)\s*([-+\d.eE]+)", req)
        v = _num(val)
        verdict = res.strip().lower()
        if not verdict:
            _say(out, "计算书", "warning", d, "校核“{}”没有写结论（合格 / 不合格）。".format(what))
        if not m or v is None:
            continue
        op = {"≥": ">=", "≤": "<="}.get(m.group(2), m.group(2))
        ok = OPS[op](v, float(m.group(3)))
        says_pass = any(w in verdict for w in PASS_WORDS) and not any(w in verdict for w in FAIL_WORDS)
        says_fail = any(w in verdict for w in FAIL_WORDS)
        if says_pass and not ok:
            _say(out, "计算书", "error", d, "校核“{}”：计算值 {} 不满足 {}，结论却写“{}”。".format(what, val, req.split("（")[0], res))
        elif says_fail and ok:
            _say(out, "计算书", "warning", d, "校核“{}”：计算值 {} 满足 {}，结论却写“{}”，请核对。".format(what, val, req.split("（")[0], res))
        elif not ok and not says_fail and verdict:
            _say(out, "计算书", "warning", d, "校核“{}”：计算值 {} 不满足 {}，结论里要写明不合格并给出改法。".format(what, val, req.split("（")[0]))


# ---------------------------------------------------------------- 零件图（PDF 文字）
DRAWING_ITEMS = [
    ("配合代号或尺寸公差", r"[a-zA-Z]{1,2}\d{1,2}\b|[±]\s*\d|[+\-]0[.,]\d"),
    ("表面粗糙度", r"Ra\s*\d|√"),
    ("热处理与硬度", r"调质|淬火|正火|渗碳|HB[WS]?|HRC|硬度|quench|temper"),
    ("圆跳动（轴承位、齿轮位）", r"跳动|↗|⌰|run.?out"),
    ("键槽对称度", r"对称|⌯|symmetr"),
    ("技术要求", r"技术要求|technical requirement|notes?\b"),
]


# 国标图面检查（第 11 轮《机械设计》第 3 章 F5）：从 PDF 读出的文字核对
SCALES = {"1:1", "2:1", "5:1", "10:1", "20:1", "50:1", "100:1", "1:2", "1:5", "1:10", "1:20", "1:50", "1:100", "1:200", "1:500", "1:1000",
          "4:1", "2.5:1", "40:1", "25:1", "1:1.5", "1:2.5", "1:3", "1:4", "1:6", "1:15", "1:25", "1:30", "1:40", "1:60",
          "1:150", "1:250", "1:300", "1:400", "1:600"}                                  # GB/T 14690 优先与允许的比例（n ≤ 2）
RA_SERIES = (0.012, 0.025, 0.05, 0.1, 0.2, 0.4, 0.8, 1.6, 3.2, 6.3, 12.5, 25, 50, 100)   # GB/T 1031 Ra 的第一系列
DIA = r"[ØøΦφ⌀∅][ \t]?(\d+(?:[.,]\d+)?)"            # 直径符号与数字之间最多一个空格，不跨行
# 材料：查牌号，不查“材料”这个标签（标题栏里本来就印着“材料”二字）；“45°”不算 45 钢
MATERIAL = (r"(?:不锈|碳素|合金|结构|弹簧|轴承)?钢|铸铁|铝合金|黄铜|青铜|"
            r"(?<![\d.])(?:45|40Cr|42CrMo4?|20CrMnTi|35CrMo|GCr15|Q235[A-D]?|Q345[A-D]?|Q355[A-D]?|HT\d{3}|QT\d{3}-\d+|"
            r"6061(?:-T6)?|7075(?:-T6)?|2A12|ZL\d{3}|POM|PA6{1,2}|C45E?|S355\w*|AISI ?\d{4})(?![\d°.])")


def _pdf_text(data):
    from pypdf import PdfReader
    return "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages)


def check_drawing(data, d, out, item=None, feats=None):
    """零件图（PDF）：技术内容有没有（配合、粗糙度、热处理……），再按国标核对图面——标题栏、比例、粗糙度取值、
    轴上配合代号的大小写、公差等级、旧符号；同一次提交有三维模型时，模型的每个外径都应在图上标出。"""
    try:
        text = _pdf_text(data)
    except Exception:  # noqa: BLE001
        _say(out, "零件图", "warning", d, "零件图读不出来（不是有效的 PDF），由老师直接看。")
        return
    if len(text.strip()) < 20:
        _say(out, "零件图", "info", d, "零件图里读不出文字（可能是扫描件或文字转成了线条），图面由老师检查。")
        return
    missing = [name for name, pat in DRAWING_ITEMS if not re.search(pat, text, re.I)]
    for name in missing:
        _say(out, "零件图", "warning", d, "零件图上没找到“{}”。若已标注，可能是导出 PDF 时文字转成了线条，请在回复里说明。".format(name))
    check_drawing_gb(text, d, out, item, feats)


def check_drawing_gb(text, d, out, item=None, feats=None):
    """国标图面检查（只看文字，图形由老师看）"""
    t = text.replace("，", ",")
    # 标题栏：图号、材料、比例（GB/T 10609.1、GB/T 14690）
    if item and item not in t:
        _say(out, "图面", "warning", d, "标题栏里没找到图号 {}（GB/T 10609.1：标题栏要写图样代号）。".format(item))
    if not re.search(MATERIAL, t, re.I):
        _say(out, "图面", "warning", d, "标题栏里没找到材料（GB/T 10609.1）。")
    # 比例：先在“比例 / Scale”后面找；没有这个标签时，只认一边是 1 的写法（如 1:2、5:1），免得把“9:30”这类时间当成比例
    scales = re.findall(r"(?:比例|scale)[ \t]*[:：]?[ \t]*(\d+(?:\.\d+)?)[ \t]*:[ \t]*(\d+(?:\.\d+)?)", t, re.I)
    if not scales:
        scales = [(a, b) for a, b in re.findall(r"(?<![\d.:])(\d+(?:\.\d+)?)[ \t]?:[ \t]?(\d+(?:\.\d+)?)(?![\d.:])", t) if "1" in (a, b)]
    scales = ["{}:{}".format(a, b) for a, b in scales]
    if not scales:
        _say(out, "图面", "warning", d, "图上没找到比例（如 1:1、2:1），标题栏要写比例（GB/T 14690）。")
    for sc in sorted(set(scales)):
        if sc not in SCALES:
            _say(out, "图面", "warning", d, "比例 {} 不是 GB/T 14690 规定的比例；优先用 1:1、1:2、2:1、1:5 等。".format(sc))
    # 表面粗糙度（GB/T 131、GB/T 1031）
    for v in sorted({float(x.replace(",", ".")) for x in re.findall(r"Ra\s*(\d+(?:[.,]\d+)?)", t)}):
        if not any(abs(v - r) < 1e-6 for r in RA_SERIES):
            _say(out, "图面", "warning", d, "Ra {:g} 不是 GB/T 1031 的第一系列值；取 0.4、0.8、1.6、3.2、6.3、12.5 等。".format(v))
    if re.search(r"[▽∇]", t):
        _say(out, "图面", "error", d, "图上有“▽”：这是旧标准的光洁度符号，现行标准（GB/T 131-2006）用 √ 形符号加 Ra 值。")
    # 尺寸公差代号：轴（物料号 SH-、RJ-、LS-，或任务单写明是轴）上的配合代号应为小写；公差等级 IT01–IT18
    # 公差带代号紧跟在直径后面（中间最多一个空格、不换行）。轴类零件上，和模型某段外径相同的直径若用了大写（孔）代号，提醒一下；
    # 不等于任何外径的（如空心轴的内孔）不提醒
    shaft = bool(item and re.match(r"(SH|RJ|LS)-", item)) or bool(feats)
    outer = {round(sg[2], 1) for sg in (feats or {}).get("segments") or []}
    for m in re.finditer(DIA + r"[ \t]?([A-Za-z]{1,2})(\d{1,2})(?![\d.])", t):
        dia, code, grade = round(float(m.group(1).replace(",", ".")), 1), m.group(2), int(m.group(3))
        if code.upper() in ("EQS", "M", "R", "C", "A", "B", "IT") or not re.fullmatch(r"[A-Za-z]{1,2}", code):
            continue
        if grade > 18:
            _say(out, "图面", "error", d, "Ø{:g}{}{}：公差等级只有 IT01–IT18。".format(dia, code, grade))
        elif shaft and code.isupper() and (not outer or any(abs(dia - o) < 0.06 for o in outer)):
            _say(out, "图面", "warning", d, "Ø{:g}{}{}：大写字母是孔的基本偏差；这一段是轴的外圆，公差带应为小写（如 k6、r6）。"
                 "若这一处确实是内孔，请在回复里说明。".format(dia, code, grade))
    # 与三维模型对照：每个外径都应在图上有直径尺寸
    if feats and feats.get("segments"):
        shown = {round(float(x.replace(",", ".")), 1) for x in re.findall(DIA, t)}
        want = sorted({round(s[2], 1) for s in feats["segments"]})
        lost = [w for w in want if not any(abs(w - s) < 0.06 for s in shown)]
        for w in lost:
            _say(out, "图面", "warning", d, "三维模型上有 Ø{:g} 的轴段，零件图上没找到这个直径尺寸。".format(w))


# ---------------------------------------------------------------- 三维模型（STEP，轴类）
def shaft_features(step):
    """读 STEP，按轴类零件提取：轴线、各段外圆 [(z0, z1, d)]、圆角 [(z, r)]、键槽底面的方位角（度）。
    读不出来抛 ValueError。"""
    import tempfile
    import os
    import build123d as bd
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "m.step")
        open(p, "wb").write(step)
        try:
            shape = bd.import_step(p)
        except Exception as e:  # noqa: BLE001
            raise ValueError("STEP 读不出来：{}".format(str(e)[:100])) from None
    faces = shape.faces()
    cyl = [f for f in faces if f.geom_type == bd.GeomType.CYLINDER]
    if not cyl:
        raise ValueError("模型里没有圆柱面，不像轴类零件")
    # 轴线：面积最大的圆柱面的轴向
    big = max(cyl, key=lambda f: f.area)
    ax = _axis_of(big)
    o, a = ax
    segs, fillets, floors = [], [], []
    for f in faces:
        z = [(_dot(_sub(v, o), a)) for v in _verts(f)]
        if not z:
            continue
        if f.geom_type == bd.GeomType.CYLINDER:
            co, ca = _axis_of(f)
            if abs(abs(_dot(ca, a)) - 1) > 1e-3 or _dist_to_axis(co, o, a) > 1e-3:
                continue                                   # 不同轴的圆柱面（如键槽端部的圆弧）
            segs.append((round(min(z), 3), round(max(z), 3), round(2 * _radius(f), 3)))
        elif f.geom_type == bd.GeomType.TORUS:
            fillets.append((round(sum(z) / len(z), 2), round(_minor_radius(f), 3)))
        elif f.geom_type == bd.GeomType.PLANE:
            n = _normal(f)
            if abs(_dot(n, a)) > 1e-3:
                continue                                   # 端面、轴肩面
            c = _center(f)
            rv = _sub(_sub(c, o), _mul(a, _dot(_sub(c, o), a)))
            rl = math.sqrt(_dot(rv, rv))
            if rl < 1e-6:
                continue
            rv = _mul(rv, 1 / rl)
            if abs(_dot(n, rv)) > 0.99:                    # 法向沿半径：键槽底面
                floors.append(_angle(rv, a))
    segs = _merge(sorted(segs))
    return {"segments": segs, "fillets": sorted(fillets), "keyseat_floors": floors}


def _verts(f):
    return [(v.X, v.Y, v.Z) for v in f.vertices()] or [tuple(f.center())]


def _axis_of(f):
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    s = BRepAdaptor_Surface(f.wrapped)
    c = s.Cylinder().Axis()
    return (c.Location().X(), c.Location().Y(), c.Location().Z()), (c.Direction().X(), c.Direction().Y(), c.Direction().Z())


def _radius(f):
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    return BRepAdaptor_Surface(f.wrapped).Cylinder().Radius()


def _minor_radius(f):
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    return BRepAdaptor_Surface(f.wrapped).Torus().MinorRadius()


def _normal(f):
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    d = BRepAdaptor_Surface(f.wrapped).Plane().Axis().Direction()
    return (d.X(), d.Y(), d.Z())


def _center(f):
    c = f.center()
    return (c.X, c.Y, c.Z)


def _sub(p, q):
    return (p[0] - q[0], p[1] - q[1], p[2] - q[2])


def _mul(p, k):
    return (p[0] * k, p[1] * k, p[2] * k)


def _dot(p, q):
    return p[0] * q[0] + p[1] * q[1] + p[2] * q[2]


def _dist_to_axis(p, o, a):
    v = _sub(p, o)
    w = _sub(v, _mul(a, _dot(v, a)))
    return math.sqrt(_dot(w, w))


def _angle(rv, a):
    """半径方向绕轴线的方位角（度）：取一个与轴线垂直的参考方向"""
    ref = (1, 0, 0) if abs(a[0]) < 0.9 else (0, 1, 0)
    e1 = _sub(ref, _mul(a, _dot(ref, a)))
    e1 = _mul(e1, 1 / math.sqrt(_dot(e1, e1)))
    e2 = (a[1] * e1[2] - a[2] * e1[1], a[2] * e1[0] - a[0] * e1[2], a[0] * e1[1] - a[1] * e1[0])
    return math.degrees(math.atan2(_dot(rv, e2), _dot(rv, e1))) % 360


def _merge(segs):
    """同一直径、首尾相接（被键槽或分面切开）的圆柱面合成一段"""
    out = []
    for z0, z1, d in segs:
        for i, (a0, a1, ad) in enumerate(out):
            if abs(ad - d) < 0.01 and z0 <= a1 + 0.01 and z1 >= a0 - 0.01:
                out[i] = (min(a0, z0), max(a1, z1), d)
                break
        else:
            out.append((z0, z1, d))
    return sorted(out)


def check_model(step, d, out, bearings=()):
    try:
        g = shaft_features(step)
    except ValueError as e:
        _say(out, "模型", "warning", d, "{}；模型由老师检查。".format(e))
        return
    segs = g["segments"]
    outer = sorted(segs, key=lambda s: s[0])
    # 台阶：相邻两段直径不同的位置
    for (a0, a1, da), (b0, b1, db) in zip(outer, outer[1:]):
        if abs(da - db) < 0.01:
            continue
        z = (a1 + b0) / 2
        near = [r for zf, r in g["fillets"] if abs(zf - z) <= max(abs(da - db), 2.0)]
        if not near:
            _say(out, "模型", "error", d, "台阶 Ø{:g} → Ø{:g}（距轴端 {:.0f} mm）没有过渡圆角。".format(da, db, z - outer[0][0]))
            continue
        for code in sorted(set(map(str, bearings))):
            bd_, B, rs = BEARINGS.get(code, (None, None, None))
            if bd_ and abs(min(da, db) - bd_) < 0.01 and max(near) >= rs:
                _say(out, "模型", "warning", d, "Ø{:g} → Ø{:g} 轴肩的圆角 r = {:g} mm，不小于轴承 {} 内圈倒角 r_s,min = {:g} mm；"
                     "如果轴承靠在这个轴肩上，会靠不紧（套筒、隔圈处不受此限）。".format(da, db, max(near), code, rs))
    for code in sorted(set(map(str, bearings))):
        if code not in BEARINGS:
            continue
        bd_, B, _ = BEARINGS[code]
        need = list(map(str, bearings)).count(code)
        seats = [s for s in segs if abs(s[2] - bd_) < 0.01]
        long_ = [s for s in seats if s[1] - s[0] >= B - 0.01]
        if not seats:
            _say(out, "模型", "error", d, "任务单的轴承是 {}（内径 {} mm），模型里没有 Ø{} 的轴段。".format(code, bd_, bd_))
        elif len(long_) < need:
            short = min(seats, key=lambda s: s[1] - s[0])
            _say(out, "模型", "error", d, "轴承 {} 宽 {} mm，Ø{} 轴段只有 {:.0f} mm 长，轴承装不下。".format(code, B, bd_, short[1] - short[0]))
    fl = g["keyseat_floors"]
    if len(fl) >= 2:
        spread = max(min(abs(x - fl[0]), 360 - abs(x - fl[0])) for x in fl)
        if spread > 2:
            _say(out, "模型", "warning", d, "{} 个键槽不在同一条母线上（方位相差约 {:.0f}°），铣键槽要多一次装夹找正。".format(len(fl), spread))


# ---------------------------------------------------------------- 更改单
def check_change(rows, need, d, out):
    rows = [r for r in rows or [] if any((r.get(k) or "").strip() for k in ("item", "change", "reason"))]
    if not rows:
        _say(out, "更改单", "error", d, "工程更改申请是空的。")
        return
    text = " ".join("{} {}".format(r.get("item", ""), r.get("change", "")) for r in rows)
    for kw in need or []:
        if not re.search("|".join(re.escape(k.strip()) for k in kw.split("|")), text, re.I):
            _say(out, "更改单", "error", d, "受影响的物料里没有“{}”。".format(kw.replace("|", " / ")))
    for r in rows:
        if not (r.get("reason") or "").strip():
            _say(out, "更改单", "warning", d, "“{}”没有写更改理由。".format(r.get("item") or r.get("change")))


# ---------------------------------------------------------------- 总入口
def review(spec, deliverables, get_file=None, get_design=None, get_job=None, get_process=None, author_uid=None):
    out = []
    for i, x in enumerate(spec.get("交付物") or []):
        kind = x.get("类型", "文件")
        name = x["名称"][0]
        got = (deliverables or {}).get(str(i)) or {}
        if kind == "文件":
            files = got.get("files") or []
            if not files:
                _say(out, "完整", "error", i, "“{}”还没有上传。".format(name))
                continue
            for f in files:
                data = get_file(f["url"]) if get_file else None
                if data is None:
                    continue
                ext = f["name"].rsplit(".", 1)[-1].lower()
                if ext == "docx" and ("计算书" in name or "calculation" in x["名称"][1].lower()):
                    check_calc(data, i, out, name)
                elif ext == "pdf" and ("图" in name or "drawing" in x["名称"][1].lower()):
                    check_drawing(data, i, out, item=x.get("零件"))
        elif kind == "设计发布":
            sid = got.get("plm")
            s = get_design(sid) if (sid and get_design) else None
            if not s:
                _say(out, "完整", "error", i, "“{}”还没有提交到设计发布。".format(name))
                continue
            if s.get("item") != x.get("零件"):
                _say(out, "模型", "error", i, "提交的物料是 {}，任务单要求 {}。".format(s.get("item"), x.get("零件")))
            step = next((get_file(f["url"]) for f in s.get("files") or [] if f.get("kind") == "step"), None) if get_file else None
            if step:
                check_model(step, i, out, x.get("轴承") or ())
            else:
                _say(out, "模型", "warning", i, "设计发布里只有图纸、没有 STEP 模型，模型检查跳过。")
            pdf = next((get_file(f["url"]) for f in s.get("files") or [] if f.get("kind") == "drawing" and f.get("name", "").lower().endswith(".pdf")), None) \
                if get_file else None
            if pdf:                                              # 设计发布里带的零件图：按国标查图面，并与模型的外径对照
                feats = None
                if step:
                    try:
                        feats = shaft_features(step)
                    except ValueError:
                        feats = None
                check_drawing(pdf, i, out, item=x.get("零件"), feats=feats)
            elif x.get("要图"):
                _say(out, "完整", "error", i, "设计发布里没有零件图（PDF）。")
        elif kind == "分析":
            jid = got.get("job")
            j = None
            if jid and get_job:
                try:
                    j = get_job(jid)
                except Exception:  # noqa: BLE001
                    j = None
            if not j:
                _say(out, "完整", "error", i, "“{}”还没有选“仿真与分析”的作业。".format(name))
                continue
            if author_uid is not None and str(j.get("owner")) != str(author_uid):
                _say(out, "分析", "error", i, "作业 {} 不是你自己算的。".format(jid))
            if j.get("status") != "done":
                _say(out, "分析", "error", i, "作业 {} 还没有算完（状态：{}）。".format(jid, j.get("status")))
            if x.get("零件") and j.get("item") and j["item"] != x["零件"]:
                _say(out, "分析", "warning", i, "作业分析的是 {}，任务单要求 {}。".format(j["item"], x["零件"]))
        elif kind == "工艺规程":
            sid = got.get("process")
            p = get_process(sid) if (sid and get_process) else None
            if not p:
                _say(out, "完整", "error", i, "“{}”还没有提交工艺规程。".format(name))
                continue
            errs = sum(f["level"] == "error" for f in (p.get("review") or {}).get("findings") or [])
            if errs:
                _say(out, "工艺规程", "error", i, "工艺规程还有 {} 条 AI 工艺评审员的“必须改”意见（在工艺规程页处理）。".format(errs))
        elif kind == "更改单":
            check_change(got.get("rows"), x.get("必列"), i, out)
        elif kind == "PLC 程序":
            check_plc(got, x, i, out, get_file)
    return out


# ---------------------------------------------------------------- PLC 程序（第 18 轮第 8 步《PLC 原理及实践》）
def check_plc(got, x, d, out, get_file=None):
    """编译检查与程序检查（与学习平台实验台的“程序检查”同一套规则）：错误记“必改”，提醒记“建议”。
    另查一条第 15 章准则 15.7.1：状态变量不得设为保持型（RETAIN）。"""
    name = x["名称"][0]
    files = got.get("files") or []
    if not files:
        _say(out, "完整", "error", d, "“{}”还没有上传（交 PLCopen XML 或 .st 文件）。".format(name))
        return
    data = get_file(files[0]["url"]) if get_file else None
    if data is None:
        return
    from hub import vplc as V
    unit = got.get("unit") or x.get("设备") or "press-01"
    try:
        st = V.to_st(files[0]["name"], data, unit)
        c = V.check(st, unit)
    except Exception as e:  # noqa: BLE001
        _say(out, "PLC 程序", "error", d, "程序读不出来：{}".format(str(e)[:200]))
        return
    if not c.get("ok"):
        _say(out, "PLC 程序", "error", d, "程序编译不过：{}".format(c.get("error")))
        return
    for r in c.get("review") or []:
        if r["level"] in ("error", "warning"):
            line = "第 {} 行：".format(r["line"]) if r.get("line") else ""
            _say(out, "程序检查", r["level"], d, line + r["msg"][0])
    if any(re.search(r"\bstate\s*:", sec, re.I) for sec in re.findall(r"\bVAR\s+RETAIN\b([\s\S]*?)\bEND_VAR\b", st, re.I)):
        _say(out, "程序检查", "error", d, "状态变量 state 声明成了保持型（RETAIN）：断电再来电后设备会自己动起来（准则 15.7.1）。")
