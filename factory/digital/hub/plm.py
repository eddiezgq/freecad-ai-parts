# -*- coding: utf-8 -*-
"""企业版第一期（数字工厂第 8 轮）：通用零件发布、STEP → 网页三维、两版差异、提交—审批—生效。

教学模式：提交即生效（与原来一步发布相同，实验 7 不受影响）。
生产（企业）模式：提交进“待审”（总线 design.submit），审批人看图、批注后批准才发 design.release / design.gcode，
下游（ERPNext 桥接、工单、车间）一行不改；退回、撤回发 design.review。
"""
import hashlib
import io
import os
import tempfile
import uuid

from factory import data as F

UNIT_M_TO_MM = 1000.0
DIFF_TOL_MM = 0.02
DIFF_MAX_FACES = 200000


# ---------------------------------------------------------------- 物料与工艺
def item_info(item, erp_lookup=None):
    """物料是否存在：先查工厂数据，再（线上）查 ERPNext。返回 {item, name, routing_ops} 或 None"""
    if item in F.ITEMS:
        name = F.ITEMS[item][0]
    elif item in getattr(F, "CASE_ITEMS", {}):               # 教材案例件（第 11 轮）
        name = F.CASE_ITEMS[item][0]
    elif erp_lookup:
        name = erp_lookup(item)
        if not name:
            return None
    else:
        return None
    ops = []
    if item in F.BOMS:
        ops = [op for op, _ in F.ROUTINGS[F.BOMS[item][0]]]
    return {"item": item, "name": name, "operations": ops}


def machine_for(operation):
    from sim.engine import OP_UNITS
    units = OP_UNITS.get(operation) or []
    return units[0] if units else None


def erp_item_name(item):
    """线上 ERPNext 里的物料名（用枢纽的管理员钥匙）；查不到返回 None"""
    import urllib.parse
    import requests
    from hub import erp_sso
    c = erp_sso.config()
    if not (c["erp_api"] and c["api_key"]):
        return None
    try:
        r = requests.get("{}/api/resource/Item/{}".format(c["erp_api"], urllib.parse.quote(item, safe="")), timeout=15,
                         headers={"Authorization": "token {}:{}".format(c["api_key"], c["api_secret"])})
        return r.json()["data"].get("item_name") if r.status_code == 200 else None
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------- 文件
def store(db, name, mime, data):
    sha = hashlib.sha256(data).hexdigest()
    db.x("insert into stored_file (sha256, name, mime, size, content) values (%s,%s,%s,%s,%s) "
         "on conflict (sha256) do nothing", (sha, name, mime, len(data), data))
    return {"name": name, "url": "/api/files/" + sha, "sha256": sha, "size": len(data)}


def load_file(db, url):
    sha = url.rsplit("/", 1)[-1]
    r = db.one("select content from stored_file where sha256=%s", (sha,))
    return bytes(r["content"]) if r else None


def step_to_glb(step):
    """STEP → glb（毫米）。返回 (glb 字节, 信息)；读不出来抛 ValueError"""
    import build123d as bd
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "in.step")
        open(src, "wb").write(step)
        try:
            shape = bd.import_step(src)
        except Exception as e:  # noqa: BLE001
            raise ValueError("STEP 文件读不出来：{}".format(str(e)[:120])) from None
        if shape is None or not shape.solids():
            raise ValueError("STEP 文件里没有实体（只有线框或曲面）")
        bb = shape.bounding_box()
        out = os.path.join(tmp, "out.glb")
        diag = max(bb.size.X, bb.size.Y, bb.size.Z, 1.0)
        bd.export_gltf(shape, out, binary=True, linear_deflection=max(diag * 2e-4, 0.005), angular_deflection=0.2)
        glb = open(out, "rb").read()
    info = {"size_mm": [round(bb.size.X, 3), round(bb.size.Y, 3), round(bb.size.Z, 3)],
            "volume_mm3": round(shape.volume, 1), "solids": len(shape.solids())}
    return glb, info


def _mesh(glb):
    import trimesh
    m = trimesh.load(io.BytesIO(glb), file_type="glb", force="mesh")
    m.apply_scale(UNIT_M_TO_MM)
    return m


def diff_glb(old_glb, new_glb, tol=DIFF_TOL_MM):
    """两版差异：新版里离旧版表面超过 tol 的面标红（新增/改动），旧版里离新版表面超过 tol 的面标蓝（去掉的）。
    返回 (差异 glb 字节, 统计)；网格太大时只给统计"""
    import numpy as np
    import trimesh
    a, b = _mesh(old_glb), _mesh(new_glb)
    stats = {"volume_old_mm3": round(float(abs(a.volume)), 1), "volume_new_mm3": round(float(abs(b.volume)), 1),
             "size_old_mm": [round(float(x), 3) for x in a.extents], "size_new_mm": [round(float(x), 3) for x in b.extents]}
    if len(a.faces) + len(b.faces) > DIFF_MAX_FACES:
        stats["note"] = "模型太大，只比较了体积和外形尺寸"
        return None, stats

    def far(src, dst):
        _, d, _ = trimesh.proximity.closest_point(dst, src.triangles_center)
        return d > tol
    added, removed = far(b, a), far(a, b)
    stats.update({"changed_area_mm2": round(float(b.area_faces[added].sum()), 1),
                  "removed_area_mm2": round(float(a.area_faces[removed].sum()), 1),
                  "changed": bool(added.any() or removed.any())})
    grey, red, blue = [190, 196, 202, 255], [214, 69, 65, 255], [52, 120, 220, 160]
    nb = b.copy()
    nb.visual = trimesh.visual.ColorVisuals(nb, face_colors=np.where(added[:, None], red, grey).astype(np.uint8))
    scene = trimesh.Scene()
    scene.add_geometry(nb, node_name="new")
    if removed.any():
        gone = a.submesh([np.nonzero(removed)[0]], append=True)
        gone.visual = trimesh.visual.ColorVisuals(gone, face_colors=np.tile(blue, (len(gone.faces), 1)).astype(np.uint8))
        scene.add_geometry(gone, node_name="removed")
    scene.apply_scale(1 / UNIT_M_TO_MM)
    return scene.export(file_type="glb"), stats


# ---------------------------------------------------------------- 版本
def current_revision(db, mode, item):
    rel = db.messages(["design.release"], mode=mode, order="desc", limit=500)
    return max([r["data"]["revision"] for r in rel if r["data"]["item"] == item] + [1])


def current_glb(db, mode, item):
    """现行版的网页模型：最近批准的提交；否则最近发布消息里的 STEP（转换后缓存）；SH-301 没发布过用工厂数据第 1 版"""
    r = db.one("select files from design_submission where mode=%s and item=%s and status='approved' order by decided_at desc limit 1",
               (mode, item))
    if r:
        g = next((f for f in r["files"] if f["kind"] == "glb"), None)
        if g:
            return load_file(db, g["url"]), g
    step = None
    for m in db.messages(["design.release"], mode=mode, order="desc", limit=200):
        if m["data"]["item"] == item:
            f = next((f for f in m["data"].get("files") or [] if f.get("kind") == "step"), None)
            if f:
                step = load_file(db, f["url"])
            break
    if step is None and item == "SH-301":
        from hub import design as D
        step = D.step_bytes(D.normalize(D.defaults()))
    if not step:
        return None, None
    key = hashlib.sha256(step).hexdigest()
    cached = db.one("select sha256 from stored_file where name=%s", ("cache-" + key + ".glb",))
    if cached:
        g = {"kind": "glb", "url": "/api/files/" + cached["sha256"]}
        return load_file(db, g["url"]), g
    try:
        glb, _ = step_to_glb(step)
    except ValueError:
        return None, None
    g = dict(store(db, "cache-" + key + ".glb", "model/gltf-binary", glb), kind="glb")
    return glb, g


def current_step(db, mode, item):
    """现行版 STEP（有限元用，第 11 轮）：最近批准的提交 → 最近发布消息 → 第 1 版（SH-301、教材案例件）"""
    r = db.one("select files from design_submission where mode=%s and item=%s and status='approved' order by decided_at desc limit 1",
               (mode, item))
    if r:
        f = next((f for f in r["files"] if f["kind"] == "step"), None)
        if f:
            return load_file(db, f["url"])
    for m in db.messages(["design.release"], mode=mode, order="desc", limit=200):
        if m["data"]["item"] == item:
            f = next((f for f in m["data"].get("files") or [] if f.get("kind") == "step"), None)
            if f:
                return load_file(db, f["url"])
            break
    if item == "SH-301":
        from hub import design as D
        return D.step_bytes(D.normalize(D.defaults()))
    from hub import case_parts
    return case_parts.step_bytes(item)                       # 教材案例件 RJ-201、LS-101 的第 1 版（第 11 轮）


def items_with_step(db, mode):
    """有现行 STEP 的物料（有限元选零件用）"""
    from hub import case_parts
    out = {"SH-301", *case_parts.CASES}
    for r in db.q("select distinct item from design_submission where mode=%s and status='approved'", (mode,)):
        out.add(r["item"])
    for m in db.messages(["design.release"], mode=mode, order="desc", limit=500):
        if any(f.get("kind") == "step" for f in m["data"].get("files") or []):
            out.add(m["data"]["item"])
    return ["SH-301"] + sorted(out - {"SH-301"})                # 主线零件 SH-301 排第一


# ---------------------------------------------------------------- 提交、审批
def submit(db, emit, mode, author, author_uid, item, step=None, step_name=None, drawing=None, drawing_name=None,
           gcode=None, operation=None, note="", params=None, extra_files=None, gcode_info=None, hold=False):
    """提交一个新版本。教学模式直接生效；生产模式进待审。hold=True（工程任务单里的提交，第 11 轮 2.7（5））：
    教学模式也进待审，任务单批准时一并批准。返回提交记录"""
    from psycopg.types.json import Jsonb
    sid = uuid.uuid4().hex[:12]
    base = current_revision(db, mode, item)
    tag = "{}-{}".format(item, sid)
    files = list(extra_files or [])
    if step:
        files.append(dict(store(db, step_name or tag + ".step", "application/step", step), kind="step"))
        glb, info = step_to_glb(step)
        files.append(dict(store(db, tag + ".glb", "model/gltf-binary", glb), kind="glb", info=info))
    if drawing:
        mime = "application/pdf" if drawing[:4] == b"%PDF" else "image/svg+xml"
        files.append(dict(store(db, drawing_name or tag + ("-drawing.pdf" if mime.endswith("pdf") else "-drawing.svg"), mime, drawing),
                          kind="drawing"))
    g = None
    if gcode:
        if not operation:
            raise ValueError("上传了加工程序，要写明是哪道工序")
        machine = machine_for(operation)
        if not machine:
            raise ValueError("工序“{}”找不到对应设备".format(operation))
        gf = store(db, "{}-{}.nc".format(tag, operation.split(" ")[0]), "text/plain", gcode)
        g = dict(gcode_info or {}, operation=operation, machine=machine, url=gf["url"], sha256=gf["sha256"])
    if not any(f["kind"] in ("step", "drawing") for f in files):
        raise ValueError("至少要有 STEP 模型或图纸")
    diff = None
    glb_new = next((f for f in files if f["kind"] == "glb"), None)
    if glb_new:
        old, _ = current_glb(db, mode, item)
        if old:
            try:
                dglb, diff = diff_glb(old, load_file(db, glb_new["url"]))
                if dglb:
                    files.append(dict(store(db, tag + "-diff.glb", "model/gltf-binary", dglb), kind="diff"))
            except Exception as e:  # noqa: BLE001 —— 差异算不出来不影响提交
                diff = {"note": "差异没算出来：{}".format(str(e)[:100])}
    db.x("insert into design_submission (id, mode, item, status, author, author_uid, note, files, gcode, params, base_rev, diff) "
         "values (%s,%s,%s,'pending',%s,%s,%s,%s,%s,%s,%s,%s)",
         (sid, mode, item, author, author_uid, note, Jsonb(files), Jsonb(g) if g else None, Jsonb(params) if params else None,
          base, Jsonb(diff) if diff else None))
    if mode == "teach" and not hold:                      # 教学模式：一步生效
        return approve(db, emit, sid, author, "教学模式自动生效", check_self=False)

    emit("wq/gearbox/design/{}/submit".format(item.lower()), "design.submit",
         {"item": item, "submission": sid, "author": author, "base_revision": base, "note": note,
          "files": [{"kind": f["kind"], "name": f["name"]} for f in files]})
    return get(db, sid)


def attach_gcode(db, mode, item, author_uid, gdata):
    """桌面发布宏在生产模式先发 design.release 再发 design.gcode：把程序挂到此人最近的待审提交上"""
    from psycopg.types.json import Jsonb
    r = db.one("select id from design_submission where mode=%s and item=%s and author_uid=%s and status='pending' "
               "and ts > now() - interval '30 minutes' order by ts desc limit 1", (mode, item, author_uid))
    if not r:
        raise ValueError("没有找到你刚提交的待审版本，加工程序无处挂")
    g = {k: v for k, v in gdata.items() if k not in ("item", "revision", "gcode_ref", "gcode_url")}
    g["url"] = gdata.get("gcode_url") or gdata.get("gcode_ref")
    db.x("update design_submission set gcode=%s where id=%s", (Jsonb(g), r["id"]))
    return r["id"]


def get(db, sid):
    r = db.one("select * from design_submission where id=%s", (sid,))
    if not r:
        return None
    r = dict(r)
    r["comments"] = [dict(c) for c in db.q("select * from design_comment where sub_id=%s order by id", (sid,))]
    return r


def approve(db, emit, sid, approver, note="", check_self=True, approver_uid=None):
    s = get(db, sid)
    if not s:
        raise KeyError("没有这次提交")
    if s["status"] != "pending":
        raise ValueError("这次提交已经{}，不能再批准".format(STATUS_ZH[s["status"]]))
    if check_self and (s["author_uid"] or s["author"]) == (approver_uid or approver):
        raise PermissionError("不能批准自己的提交，请另一位审批人批准")
    if check_self and any(not c["resolved"] for c in s["comments"]):
        raise ValueError("还有没处理的批注，先标为“已处理”再批准")
    rev = current_revision(db, s["mode"], s["item"]) + 1
    db.x("update design_submission set status='approved', revision=%s, decided_by=%s, decided_at=now(), decision=%s where id=%s",
         (rev, approver, note, sid))
    files = [{k: f[k] for k in ("name", "url", "sha256", "size", "kind") if k in f} for f in s["files"] if f["kind"] in ("step", "drawing")]
    data = {"item": s["item"], "revision": rev, "files": files, "author": s["author"], "change_note": s["note"] or "",
            "submission": sid, "approved_by": approver, "tool": "问渠设计发布"}
    if s["params"]:
        data["params"] = s["params"]
        if s["item"] == "SH-301":
            from hub import design as D
            data["bom"] = D.wq_publish.bom(s["params"])
            data["total_length_mm"] = sum(l for _, l in s["params"]["segments"])
    emit("wq/gearbox/design/{}/release".format(s["item"].lower()), "design.release", data)
    if s["gcode"]:
        g = s["gcode"]
        emit("wq/gearbox/design/{}/gcode".format(s["item"].lower()), "design.gcode",
             dict({k: v for k, v in g.items() if k not in ("url",)}, item=s["item"], revision=rev,
                  gcode_ref=g["url"], gcode_url=g["url"]))
    if s["mode"] != "teach":
        emit("wq/gearbox/design/{}/review".format(s["item"].lower()), "design.review",
             {"item": s["item"], "submission": sid, "decision": "approved", "by": approver, "revision": rev, "note": note})
    return get(db, sid)


def decide(db, emit, sid, who_, decision, note=""):
    """退回（审批人）或撤回（提交人）"""
    s = get(db, sid)
    if not s:
        raise KeyError("没有这次提交")
    if s["status"] != "pending":
        raise ValueError("这次提交已经{}".format(STATUS_ZH[s["status"]]))
    if decision == "rejected" and not note.strip():
        raise ValueError("退回要写明原因")
    if decision == "withdrawn" and s["author"] != who_:
        raise PermissionError("只有提交人能撤回")
    db.x("update design_submission set status=%s, decided_by=%s, decided_at=now(), decision=%s where id=%s",
         (decision, who_, note, sid))
    emit("wq/gearbox/design/{}/review".format(s["item"].lower()), "design.review",
         {"item": s["item"], "submission": sid, "decision": decision, "by": who_, "note": note})
    return get(db, sid)


def comment(db, sid, author, body, anchor=None):
    from psycopg.types.json import Jsonb
    s = get(db, sid)
    if not s:
        raise KeyError("没有这次提交")
    body = (body or "").strip()[:2000]
    if not body:
        raise ValueError("意见不能为空")
    if anchor is not None:
        anchor = {k: float(anchor[k]) for k in ("x", "y", "z")}
    db.x("insert into design_comment (sub_id, author, body, anchor) values (%s,%s,%s,%s)",
         (sid, author, body, Jsonb(anchor) if anchor else None))
    return get(db, sid)


def resolve_comment(db, sid, cid, resolved=True):
    db.x("update design_comment set resolved=%s where sub_id=%s and id=%s", (resolved, sid, cid))
    return get(db, sid)


STATUS_ZH = {"pending": "待审", "approved": "批准", "rejected": "退回", "withdrawn": "撤回"}
