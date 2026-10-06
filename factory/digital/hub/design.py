# -*- coding: utf-8 -*-
"""网页设计台（数字工厂第 6 轮 W2、W3）：在浏览器里改输出轴参数，由服务器校核、出 STEP / 零件图 / 键槽 G 代码，
经总线发布 design.release 与 design.gcode——消息格式与桌面 FreeCAD 发布宏（freecad/wq_publish.py）完全一致。

STEP 用 build123d（零件库已在用）生成；镜像里没有 build123d 时照样发布，只是不带 STEP（同桌面宏“没装 FreeCAD”的做法）。
"""
import copy
import hashlib
import os
import sys

FREECAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "freecad")
if FREECAD_DIR not in sys.path:
    sys.path.insert(0, FREECAD_DIR)

import wq_cam_keyway  # noqa: E402
import wq_drawing  # noqa: E402
import wq_publish  # noqa: E402
import wq_shaft  # noqa: E402

ITEM = "SH-301"
TOOL = "问渠网页设计台"

# GB/T 1095-2003 普通平键 键槽尺寸（摘）：轴径范围 (d_min, d_max] → 键宽 b、轴槽深 t
GBT1095 = [(6, 8, 2, 1.2), (8, 10, 3, 1.8), (10, 12, 4, 2.5), (12, 17, 5, 3.0), (17, 22, 6, 3.5),
           (22, 30, 8, 4.0), (30, 38, 10, 5.0), (38, 44, 12, 5.0), (44, 50, 14, 5.5), (50, 58, 16, 6.0),
           (58, 65, 18, 7.0), (65, 75, 20, 7.5), (75, 85, 22, 9.0)]

LIMITS = {"segments": (1, 8), "d": (5.0, 48.0), "len": (2.0, 300.0), "chamfer": (0.0, 5.0), "fillet": (0.0, 5.0)}   # 棒料 Ø50


def defaults():
    return copy.deepcopy(wq_shaft.PARAMS)


def gbt1095(d):
    for lo, hi, b, t in GBT1095:
        if lo < d <= hi:
            return {"b": b, "t": t, "range": "{}～{}".format(lo, hi)}
    return None


def normalize(p):
    """前端发来的参数 → 规范格式；格式不对抛 ValueError"""
    try:
        segs = [(float(d), float(l)) for d, l in p["segments"]]
        kw = p.get("keyway")
        kw = None if not kw else {"segment": int(kw["segment"]), "b": float(kw["b"]), "t": float(kw["t"]), "L": float(kw["L"])}
        out = {"segments": segs, "chamfer": float(p.get("chamfer", 0)), "keyway": kw}
        if p.get("fillet"):                       # 台阶过渡圆角（第 11 轮《机械设计》33.2 节 F4）；不写或 0 = 尖角，与旧参数一致
            out["fillet"] = float(p["fillet"])
        return out
    except (KeyError, TypeError, ValueError) as e:
        raise ValueError("参数格式不对：{}".format(e)) from None


def check(params):
    """校核：errors 不能发布；warnings 只提示（如键宽与 GB/T 1095 推荐不同）"""
    errors, warnings = [], []
    segs = params["segments"]
    if not LIMITS["segments"][0] <= len(segs) <= LIMITS["segments"][1]:
        errors.append("轴段数要在 1～8 段之间")
    for i, (d, l) in enumerate(segs):
        if not LIMITS["d"][0] <= d <= LIMITS["d"][1]:
            errors.append("第 {} 段直径 {} mm 超出范围 {}～{} mm（棒料 Ø50）".format(i + 1, d, *LIMITS["d"]))
        if not LIMITS["len"][0] <= l <= LIMITS["len"][1]:
            errors.append("第 {} 段长度 {} mm 超出范围 {}～{} mm".format(i + 1, l, *LIMITS["len"]))
    c = params["chamfer"]
    if not LIMITS["chamfer"][0] <= c <= LIMITS["chamfer"][1]:
        errors.append("倒角 {} mm 超出范围 0～5 mm".format(c))
    elif segs and c >= min(segs[0][0], segs[-1][0]) / 2:
        errors.append("倒角不能大于端面半径")
    r = params.get("fillet", 0.0)
    if not LIMITS["fillet"][0] <= r <= LIMITS["fillet"][1]:
        errors.append("台阶圆角 {} mm 超出范围 0～5 mm".format(r))
    elif r > 0:
        for i, ((da, _), (db, _)) in enumerate(zip(segs, segs[1:])):
            h = abs(da - db) / 2
            if h > 0 and r >= h:
                errors.append("第 {}、{} 段之间的台阶高只有 {:g} mm，圆角 {:g} mm 做不出来（圆角要小于台阶高）".format(i + 1, i + 2, h, r))
    if not errors:
        errors += wq_shaft.check_keyway(segs, params["keyway"])
    kw = params["keyway"]
    rec = None
    if kw and 0 <= kw["segment"] < len(segs):
        d = segs[kw["segment"]][0]
        rec = gbt1095(d)
        if rec and (abs(kw["b"] - rec["b"]) > 1e-6 or abs(kw["t"] - rec["t"]) > 1e-6):
            warnings.append("GB/T 1095：轴径 {} mm（{} mm 档）推荐键宽 b={}、轴槽深 t={}，当前 b={}、t={}".format(
                d, rec["range"], rec["b"], rec["t"], kw["b"], kw["t"]))
    total = sum(l for _, l in segs)
    return {"ok": not errors, "errors": errors, "warnings": warnings, "recommended": rec,
            "total_length_mm": total, "bom": wq_publish.bom(params) if not errors else None}


def step_bytes(params):
    """build123d 生成 STEP；没装 build123d 返回 None"""
    try:
        import build123d as bd
    except ImportError:
        return None
    import tempfile
    layout, total = wq_shaft.shaft_layout(params["segments"])
    shaft = None
    for z0, z1, d in layout:
        cyl = bd.Pos(0, 0, z0) * bd.Cylinder(d / 2, z1 - z0, align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN))
        shaft = cyl if shaft is None else shaft + cyl
    r = params.get("fillet", 0.0)
    if r > 0:                                     # 台阶的内角（小直径一侧的圆）倒圆角
        inner = []
        for (z0, z1, d), (_, _, d2) in zip(layout, layout[1:]):
            if abs(d - d2) > 1e-6:
                rr = min(d, d2) / 2
                inner += [e for e in shaft.edges().filter_by(bd.GeomType.CIRCLE)
                          if abs(e.center().Z - z1) < 1e-6 and abs(e.radius - rr) < 1e-6]
        if inner:
            shaft = bd.fillet(inner, r)
    c = params["chamfer"]
    if c > 0:
        ends = [e for e in shaft.edges().filter_by(bd.GeomType.CIRCLE)                 # 两端面外圆
                if (abs(e.center().Z) < 1e-6 and abs(e.radius - layout[0][2] / 2) < 1e-6)
                or (abs(e.center().Z - total) < 1e-6 and abs(e.radius - layout[-1][2] / 2) < 1e-6)]
        try:
            shaft = bd.chamfer(ends, c)
        except Exception:  # noqa: BLE001 —— 倒角失败不影响发布
            pass
    kw = params["keyway"]
    if kw:
        z0, z1, d = layout[kw["segment"]]
        b, t, L = kw["b"], kw["t"], kw["L"]
        zc = (z0 + z1) / 2
        h = t + 1.0
        y0 = d / 2 - t
        slot = bd.Pos(0, y0 + h / 2, zc) * bd.Box(b, h, L - b)
        for dz in (-(L - b) / 2, (L - b) / 2):
            slot += bd.Pos(0, y0 + h / 2, zc + dz) * bd.Rot(90, 0, 0) * bd.Cylinder(b / 2, h)
        shaft = shaft - slot
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "shaft.step")
        bd.export_step(shaft, path)
        return open(path, "rb").read()


def store(db, name, mime, data):
    sha = hashlib.sha256(data).hexdigest()
    db.x("insert into stored_file (sha256, name, mime, size, content) values (%s,%s,%s,%s,%s) "
         "on conflict (sha256) do nothing", (sha, name, mime, len(data), data))
    return {"name": name, "url": "/api/files/" + sha, "sha256": sha, "size": len(data)}


def current_revision(db, mode):
    rel = db.messages(["design.release"], mode=mode, order="desc", limit=200)
    return max([r["data"]["revision"] for r in rel if r["data"]["item"] == ITEM] + [1])


def publish(db, emit, params, author, mode, change_note=""):
    """emit(topic, type, data) 负责上总线并写历史库。返回与 wq_publish.publish 相同结构"""
    res = check(params)
    if not res["ok"]:
        raise ValueError("；".join(res["errors"]))
    cfg = wq_publish.CONFIG
    rev = current_revision(db, mode) + 1
    tag = "{}-rev{}".format(ITEM, rev)
    files = []
    step = step_bytes(params)
    if step:
        files.append(dict(store(db, tag + ".step", "application/step", step), kind="step"))
    drawing = wq_drawing.svg(params, ITEM, cfg["title"], rev, author).encode("utf-8")
    files.append(dict(store(db, tag + "-drawing.svg", "image/svg+xml", drawing), kind="drawing"))
    gcode, info = wq_cam_keyway.generate(params, item=ITEM, revision=rev)
    gfile = store(db, tag + "-keyway.nc", "text/plain", gcode.encode("utf-8"))
    data = {"item": ITEM, "revision": rev, "params": params, "bom": res["bom"], "files": files,
            "author": author, "change_note": change_note, "total_length_mm": res["total_length_mm"], "tool": TOOL}
    emit("wq/gearbox/design/{}/release".format(ITEM.lower()), "design.release", data)
    g = {"item": ITEM, "revision": rev, "operation": "铣键槽 Keyway milling", "machine": "key-01",
         "gcode_ref": gfile["url"], "gcode_url": gfile["url"], "sha256": gfile["sha256"],
         "tools": info["tools"], "est_time_s": info["est_time_s"], "cut_length_mm": info["cut_length_mm"],
         "slot": info["slot"]}
    emit("wq/gearbox/design/{}/gcode".format(ITEM.lower()), "design.gcode", g)
    return {"revision": rev, "files": files, "gcode": gfile, "gcode_lines": gcode.count("\n"), "bom": res["bom"],
            "step": bool(step), "warnings": res["warnings"]}


def submit_prod(db, emit, params, author, author_uid, change_note=""):
    """企业版（第 8 轮）：生产模式下网页设计台的发布先进待审；文件与一步发布相同"""
    from hub import plm
    res = check(params)
    if not res["ok"]:
        raise ValueError("；".join(res["errors"]))
    rev = plm.current_revision(db, "prod", ITEM) + 1                   # 图纸上写预定版本号
    drawing = wq_drawing.svg(params, ITEM, wq_publish.CONFIG["title"], rev, author).encode("utf-8")
    gcode, info = wq_cam_keyway.generate(params, item=ITEM, revision=rev)
    gi = {k: info[k] for k in ("tools", "est_time_s", "cut_length_mm", "slot")}
    return plm.submit(db, emit, "prod", author, author_uid, ITEM, step=step_bytes(params), step_name="{}-rev{}.step".format(ITEM, rev),
                      drawing=drawing, drawing_name="{}-rev{}-drawing.svg".format(ITEM, rev), gcode=gcode.encode("utf-8"),
                      operation="铣键槽 Keyway milling", note=change_note, params=params, gcode_info=gi)
