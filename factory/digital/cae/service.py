# -*- coding: utf-8 -*-
"""计算服务（第 11 轮 F2）：单独的 cae 容器。所有工厂（公共、演示、各班）的枢纽都把任务交到这里排队。

- 同一时间只算 1 个任务；每个任务在单独的子进程里算，超时或内存不够就整个结束掉，不影响服务。
- 只在内部网络可达（不对外开端口），身份由枢纽核对后带过来（owner、factory）。
- 数据放 /data：geo/<sha>/（零件 STEP、面清单、按面分开的模型），jobs/<编号>/（设置、状态、结果）。
"""
import hashlib
import json
import multiprocessing as mp
import os
import queue
import struct
import threading
import time
import urllib.parse
import uuid
import zipfile

import numpy as np
from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response

from cae import materials as M

DATA = os.environ.get("WQ_CAE_DATA", "/data")
TIME_LIMIT_S = int(os.environ.get("WQ_CAE_TIME_LIMIT_S", "300"))
GEO_LIMIT_S = 90
MAX_STEP_BYTES = 30 * 1024 * 1024

app = FastAPI(title="WenQuest CAE")
_Q = queue.Queue()
_RUNNING = {"id": None}
_JLOCK = threading.Lock()


def _p(*a):
    return os.path.join(DATA, *a)


def _write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, path)


def _read_json(path):
    with open(path) as f:
        return json.load(f)


# ------------------------------------------------------------------ 子进程
def _isolated(target, args, timeout):
    """在新进程里跑 target(*args, out_queue)；返回 (ok, 结果或错误文字)"""
    ctx = mp.get_context("spawn")
    q = ctx.Queue()
    p = ctx.Process(target=target, args=(*args, q), daemon=True)
    p.start()
    p.join(timeout)
    if p.is_alive():
        p.kill()
        p.join()
        return False, "超过 {} 秒，已中止：请把网格尺寸调大或简化模型".format(timeout)
    try:
        return q.get(timeout=2)
    except queue.Empty:
        return False, "计算进程异常退出（代码 {}，多半是内存不够）：请把网格尺寸调大".format(p.exitcode)


def _geo_child(step_path, outdir, q):
    try:
        from cae import geometry as G
        faces, glb, solid = G.faces(open(step_path, "rb").read())
        open(os.path.join(outdir, "model.glb"), "wb").write(glb)
        _write_json(os.path.join(outdir, "faces.json"), {"faces": faces, "solid": solid})
        q.put((True, None))
    except Exception as e:  # noqa: BLE001
        q.put((False, str(e) or e.__class__.__name__))


def write_surface(path, surf):
    pos, vm, u = surf["positions"], surf["vm"], surf["u"]
    tri, face = surf["triangles"], surf["face_of_triangle"]
    with open(path, "wb") as f:
        f.write(struct.pack("<4sII", b"WQS1", len(pos), len(tri)))
        for a, dt in ((pos, "<f4"), (vm, "<f4"), (u, "<f4"), (tri, "<u4"), (face, "<u4")):
            f.write(np.ascontiguousarray(a, dtype=dt).tobytes())
        if surf.get("temp") is not None:                  # 第 14 轮：热分析多一段节点温度（旧读法读到 face 为止，不受影响）
            f.write(np.ascontiguousarray(surf["temp"], dtype="<f4").tobytes())


def read_surface(path):
    raw = open(path, "rb").read()
    _, nv, nt = struct.unpack_from("<4sII", raw)
    o = 12
    out = {}
    for name, n, dt in (("positions", nv * 3, "<f4"), ("vm", nv, "<f4"), ("u", nv * 3, "<f4"),
                        ("triangles", nt * 3, "<u4"), ("face_of_triangle", nt, "<u4")):
        out[name] = np.frombuffer(raw, dt, n, o)
        o += 4 * n
    if len(raw) >= o + 4 * nv:
        out["temp"] = np.frombuffer(raw, "<f4", nv, o)
    out["positions"] = out["positions"].reshape(-1, 3)
    out["u"] = out["u"].reshape(-1, 3)
    out["triangles"] = out["triangles"].reshape(-1, 3)
    return out


def _solve_child(step_path, setup, outdir, q):
    try:
        if setup.get("analysis") in ("thermal", "thermo_mech"):
            from cae import thermal as S
        else:
            from cae import solve as S
        stats, surf, _ = S.solve(open(step_path, "rb").read(), setup)
        write_surface(os.path.join(outdir, "surface.bin"), surf)
        q.put((True, stats))
    except Exception as e:  # noqa: BLE001
        q.put((False, str(e) or e.__class__.__name__))


# ------------------------------------------------------------------ 运动与动力分析（第 12 轮）
def model_key(ref):
    src = (ref or {}).get("source")
    if src == "library":
        return str(ref.get("id", "")).replace("/", "")
    if src == "upload":
        return "u-" + str(ref.get("sha", "")).replace("/", "")[:64]
    if src == "mech":
        import json as _j
        return "m-" + hashlib.sha256(_j.dumps([ref.get("id"), ref.get("params") or {}], sort_keys=True).encode()).hexdigest()[:24]
    raise ValueError("模型来源不对")


def load_model_spec(ref):
    """模型引用 → MjSpec"""
    from cae import mbd, mbd_models as MM
    src = ref.get("source")
    if src == "library":
        return mbd.load_spec(path=MM.robot_path(ref.get("id")))
    if src == "upload":
        if ref.get("_main"):                      # 子进程里：主进程已经找好了文件
            return mbd.load_spec(path=ref["_main"])
        meta = _p("mbd", "uploads", model_key(ref)[2:], "meta.json")
        if not os.path.exists(meta):
            raise ValueError("没有这个上传的模型")
        return mbd.load_spec(path=_read_json(meta)["main"])
    if src == "mech":
        from cae import mech_mjcf
        return mbd.load_spec(xml=mech_mjcf.mjcf(ref.get("id"), ref.get("params") or {}))
    raise ValueError("模型来源不对")


def _resolved(ref):
    """交给子进程前把上传模型的文件路径找好（子进程不一定知道数据目录）"""
    if ref.get("source") == "upload":
        meta = _p("mbd", "uploads", model_key(ref)[2:], "meta.json")
        if not os.path.exists(meta):
            raise HTTPException(404, "没有这个上传的模型")
        return dict(ref, _main=_read_json(meta)["main"])
    return ref


def _model_child(ref, outdir, q):
    try:
        from cae import mbd, mbd_models as MM
        model, _ = mbd.build(load_model_spec(ref), {})
        open(os.path.join(outdir, "model.glb"), "wb").write(MM.model_glb(model))
        _write_json(os.path.join(outdir, "info.json"), mbd.info(model))
        q.put((True, None))
    except Exception as e:  # noqa: BLE001
        q.put((False, str(e) or e.__class__.__name__))


def write_series(path, ch):
    names = list(ch)
    head = json.dumps({"names": names, "n": int(len(ch["t"]))}).encode()
    with open(path, "wb") as f:
        f.write(struct.pack("<4sI", b"WQC1", len(head)))
        f.write(head)
        f.write(np.ascontiguousarray(np.stack([ch[n] for n in names], 1), dtype="<f4").tobytes())


def read_series(path):
    raw = open(path, "rb").read()
    _, hl = struct.unpack_from("<4sI", raw)
    head = json.loads(raw[8:8 + hl])
    arr = np.frombuffer(raw, "<f4", offset=8 + hl).reshape(head["n"], len(head["names"]))
    return {n: arr[:, i] for i, n in enumerate(head["names"])}


def write_anim(path, an):
    head = json.dumps({"bodies": an["bodies"], "frames": int(len(an["t"]))}).encode()
    with open(path, "wb") as f:
        f.write(struct.pack("<4sI", b"WQA1", len(head)))
        f.write(head)
        for a in (an["t"], an["pos"], an["quat"]):
            f.write(np.ascontiguousarray(a, dtype="<f4").tobytes())


def _mbd_child(ref, setup, outdir, q):
    try:
        from cae import mbd
        if ref.get("source") == "mech":
            from cae import mech_mjcf
            setup = mech_mjcf.prepare_setup(ref.get("id"), ref.get("params") or {}, setup)
        summ, ch, an = mbd.simulate(load_model_spec(ref), setup)
        write_series(os.path.join(outdir, "series.bin"), ch)
        write_anim(os.path.join(outdir, "anim.bin"), an)
        q.put((True, summ))
    except Exception as e:  # noqa: BLE001
        q.put((False, str(e) or e.__class__.__name__))


# ------------------------------------------------------------------ 队列
def _job_path(jid, *a):
    return _p("jobs", jid, *a)


def _update(jid, **kw):
    with _JLOCK:
        j = _read_json(_job_path(jid, "job.json"))
        j.update(kw)
        _write_json(_job_path(jid, "job.json"), j)
        return j


def _worker():
    while True:
        jid = _Q.get()
        try:
            j = _read_json(_job_path(jid, "job.json"))
            if j["status"] != "queued":
                continue
            _RUNNING["id"] = jid
            _update(jid, status="running", started=time.time())
            if j.get("kind") == "mbd":
                ok, res = _isolated(_mbd_child, (_resolved(j["model"]), j["setup"], _job_path(jid)), TIME_LIMIT_S + 60)
            elif j.get("kind") == "opt":
                ok, res = _isolated(_opt_child, (j["spec"], _job_path(jid)), OPT_LIMIT_S + 120)
            elif j.get("kind") == "cfd":
                ok, res = _isolated(_cfd_child, (_p("geo", j["step_sha"], "part.step"), j["setup"], _job_path(jid)), CFD_LIMIT_S)
            elif j.get("kind") == "cfd_bench":
                ok, res = _isolated(_cfd_bench_child, (_job_path(jid),), CFD_LIMIT_S)
            elif j.get("kind") == "topo":
                ok, res = _isolated(_topo_child, (j["spec"], _job_path(jid)), TOPO_LIMIT_S)
            else:
                setup = dict(j["setup"])
                setup["material"] = M.get(setup["material_id"])
                ok, res = _isolated(_solve_child, (_p("geo", j["step_sha"], "part.step"), setup, _job_path(jid)), TIME_LIMIT_S + 60)
            if ok:
                _update(jid, status="done", finished=time.time(), stats=res)
            else:
                _update(jid, status="failed", finished=time.time(), error=res)
        except Exception as e:  # noqa: BLE001
            try:
                _update(jid, status="failed", finished=time.time(), error=str(e))
            except Exception:  # noqa: BLE001
                pass
        finally:
            _RUNNING["id"] = None


@app.on_event("startup")
def _start():
    os.makedirs(_p("geo"), exist_ok=True)
    os.makedirs(_p("jobs"), exist_ok=True)
    os.makedirs(_p("mbd", "models"), exist_ok=True)
    pending = []
    for jid in os.listdir(_p("jobs")):
        try:
            j = _read_json(_job_path(jid, "job.json"))
        except Exception:  # noqa: BLE001
            continue
        if j["status"] == "running":
            _update(jid, status="failed", error="计算服务重启，任务中断，请重新提交")
        elif j["status"] == "queued":
            pending.append((j["created"], jid))
    for _, jid in sorted(pending):
        _Q.put(jid)
    threading.Thread(target=_worker, daemon=True).start()


def _queued_ids():
    out = []
    for jid in os.listdir(_p("jobs")):
        try:
            j = _read_json(_job_path(jid, "job.json"))
        except Exception:  # noqa: BLE001
            continue
        if j["status"] == "queued":
            out.append((j["created"], jid))
    return [jid for _, jid in sorted(out)]


def _public(j):
    j = dict(j)
    if j["status"] == "queued":
        q = _queued_ids()
        j["position"] = q.index(j["id"]) + 1 if j["id"] in q else None
        j["running_other"] = _RUNNING["id"] is not None
    return j


# ------------------------------------------------------------------ 接口
@app.get("/health")
def health():
    return {"ok": True, "running": _RUNNING["id"], "queued": len(_queued_ids())}


@app.get("/materials")
def materials():
    return {"materials": M.public(), "films": M.FILM}


@app.post("/geometry")
async def geometry(request: Request):
    data = await request.body()
    if not data:
        raise HTTPException(400, "没有收到 STEP 文件")
    if len(data) > MAX_STEP_BYTES:
        raise HTTPException(413, "STEP 文件超过 30 MB，教学版不支持")
    sha = hashlib.sha256(data).hexdigest()
    d = _p("geo", sha)
    if not os.path.exists(os.path.join(d, "faces.json")):
        os.makedirs(d, exist_ok=True)
        open(os.path.join(d, "part.step"), "wb").write(data)
        ok, err = _isolated(_geo_child, (os.path.join(d, "part.step"), d), GEO_LIMIT_S)
        if not ok:
            raise HTTPException(422, "读不了这个 STEP：{}".format(err))
    return dict(_read_json(os.path.join(d, "faces.json")), sha=sha)


@app.get("/geometry/{sha}/faces")
def geometry_faces(sha: str):
    p = _p("geo", sha.replace("/", ""), "faces.json")
    if not os.path.exists(p):
        raise HTTPException(404, "没有这个零件")
    return _read_json(p)


@app.get("/geometry/{sha}/model.glb")
def geometry_glb(sha: str):
    p = _p("geo", sha.replace("/", ""), "model.glb")
    if not os.path.exists(p):
        raise HTTPException(404, "没有这个零件")
    return FileResponse(p, media_type="model/gltf-binary")


@app.post("/jobs")
def submit(body: dict = Body(...)):
    sha = str(body.get("step_sha", "")).replace("/", "")
    if not os.path.exists(_p("geo", sha, "faces.json")):
        raise HTTPException(400, "请先读入零件")
    setup = body.get("setup") or {}
    try:
        M.get(setup.get("material_id"))
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    faces = {f["id"] for f in _read_json(_p("geo", sha, "faces.json"))["faces"]}
    loads = setup.get("loads") or []
    for l in loads:
        if not l.get("faces") or not set(l["faces"]) <= faces:
            raise HTTPException(400, "载荷或约束选的面不对")
    an = setup.get("analysis", "static")
    if an in ("thermal", "thermo_mech"):
        th = setup.get("thermal") or []
        for l in th:
            if l["type"] != "heat_body" and l.get("faces") != "rest" and (not l.get("faces") or not set(l["faces"]) <= faces):
                raise HTTPException(400, "热载荷选的面不对")
        if not any(l["type"] in ("temperature", "convection") for l in th):
            raise HTTPException(400, "至少要有一个固定温度或对流换热的面")
        if an == "thermo_mech" and not any(l["type"] in ("fixed", "cyl_support") for l in loads):
            raise HTTPException(400, "热—结构耦合至少要有一个固定或支承面")
    else:
        if not any(l["type"] in ("fixed", "cyl_support") for l in loads):
            raise HTTPException(400, "至少要有一个固定或支承面")
        if not any(l["type"] not in ("fixed", "cyl_support") for l in loads):
            raise HTTPException(400, "还没有加载荷")
    jid = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
    os.makedirs(_job_path(jid))
    j = {"id": jid, "status": "queued", "created": time.time(), "step_sha": sha, "setup": setup,
         "owner": body.get("owner"), "owner_name": body.get("owner_name"), "factory": body.get("factory"),
         "title": body.get("title") or "", "item": body.get("item")}
    _write_json(_job_path(jid, "job.json"), j)
    _Q.put(jid)
    return _public(j)


@app.get("/mbd/mechs")
def mbd_mechs():
    from cae import mech_mjcf as MC
    return {"mechs": [{"id": k, "name": MC.NAMES[k], "driver": MC.DRIVER[k], "params": MC.DEFAULTS[k], "labels": MC.LABELS,
                       "fea_members": list(MC.STEP_MEMBERS.get(k, {}))}
                      for k in MC.DEFAULTS]}


@app.get("/mbd/robots")
def mbd_robots():
    from cae import mbd_models as MM
    return {"robots": [{"id": k, "name": v[1], "end_body": v[2], "own": k in MM.OWN} for k, v in MM.robots().items()]}


def _model_ready(ref):
    key = model_key(ref)
    d = _p("mbd", "models", key)
    if not os.path.exists(os.path.join(d, "info.json")):
        os.makedirs(d, exist_ok=True)
        ok, err = _isolated(_model_child, (_resolved(ref), d), GEO_LIMIT_S)
        if not ok:
            raise HTTPException(422, "读不了这个模型：{}".format(err))
    return dict(_read_json(os.path.join(d, "info.json")), key=key, ref=ref)


@app.post("/mbd/models/load")
def mbd_model_load(body: dict = Body(...)):
    try:
        model_key(body)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    return _model_ready(body)


@app.post("/mbd/models/upload")
async def mbd_model_upload(request: Request, name: str = "model.xml"):
    from cae import mbd_models as MM
    data = await request.body()
    if not data:
        raise HTTPException(400, "没有收到文件")
    if len(data) > 100 * 1024 * 1024:
        raise HTTPException(413, "文件超过 100 MB")
    sha = hashlib.sha256(data).hexdigest()
    d = _p("mbd", "uploads", sha)
    if not os.path.exists(os.path.join(d, "meta.json")):
        try:
            main = MM.unpack_upload(data, name, os.path.join(d, "files"))
        except (ValueError, zipfile.BadZipFile) as e:
            raise HTTPException(422, str(e)) from None
        _write_json(os.path.join(d, "meta.json"), {"main": main, "name": name})
    return _model_ready({"source": "upload", "sha": sha})


@app.get("/mbd/models/{key}/model.glb")
def mbd_model_glb(key: str):
    p = _p("mbd", "models", key.replace("/", ""), "model.glb")
    if not os.path.exists(p):
        raise HTTPException(404, "没有这个模型")
    return FileResponse(p, media_type="model/gltf-binary")


@app.post("/mbd/jobs")
def mbd_submit(body: dict = Body(...)):
    from cae import mbd
    ref = body.get("model") or {}
    info = _model_ready(ref)
    setup = body.get("setup") or {}
    try:
        dur = float(setup.get("duration_s", 2))
    except (TypeError, ValueError):
        raise HTTPException(400, "仿真时长不对") from None
    if not 0 < dur <= mbd.MAX_DURATION_S:
        raise HTTPException(400, "仿真时长要在 0–{:.0f} 秒之间".format(mbd.MAX_DURATION_S))
    names = {j["name"] for j in info["joints"]}
    bodies = {b["name"] for b in info["bodies"]}
    for d in setup.get("drives") or []:
        if d.get("joint") not in names:
            raise HTTPException(400, "模型里没有关节“{}”".format(d.get("joint")))
    for x in (setup.get("payloads") or []) + (setup.get("forces") or []) + (setup.get("points") or []):
        if x.get("body") not in bodies:
            raise HTTPException(400, "模型里没有构件“{}”".format(x.get("body")))
    jid = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
    os.makedirs(_job_path(jid))
    j = {"id": jid, "kind": "mbd", "status": "queued", "created": time.time(), "model": ref, "model_key": info["key"],
         "setup": setup, "owner": body.get("owner"), "owner_name": body.get("owner_name"), "factory": body.get("factory"),
         "title": body.get("title") or "", "item": body.get("item")}
    _write_json(_job_path(jid, "job.json"), j)
    _Q.put(jid)
    return _public(j)


def _quat_mat(q):
    w, x, y, z = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def _read_anim(path):
    raw = open(path, "rb").read()
    _, hl = struct.unpack_from("<4sI", raw)
    head = json.loads(raw[8:8 + hl])
    f, nb = head["frames"], len(head["bodies"])
    arr = np.frombuffer(raw, "<f4", offset=8 + hl)
    return head["bodies"], arr[:f], arr[f:f + f * nb * 3].reshape(f, nb, 3), arr[f + f * nb * 3:].reshape(f, nb, 4)


def member_load(jid, member):
    """动力学结果里一根杆件的受力（第 12 轮 D6）：B 端受力的时间序列（构件坐标）、最大时刻"""
    from cae import mech_mjcf as MC
    j = _read_json(_job_path(jid, "job.json"))
    if j.get("kind") != "mbd" or j["status"] != "done":
        raise HTTPException(409, "动力学结果还没出来")
    ref = j["model"]
    if ref.get("source") != "mech":
        raise HTTPException(400, "目前只有零件库的连杆机构能把杆件送去有限元")
    try:
        ch_body = MC.member_force_channel(ref["id"], member)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    ser = read_series(_job_path(jid, "series.bin"))
    bodies, at, apos, aquat = _read_anim(_job_path(jid, "anim.bin"))
    F = -np.stack([ser["rf.{}.{}".format(ch_body, a)] for a in "xyz"], 1)        # 世界坐标，B 端受力
    bi = bodies.index(member)
    idx = np.clip(np.searchsorted(at, ser["t"]), 0, len(at) - 1)                  # 每个采样时刻的构件姿态（取最近的动画帧）
    Floc = np.stack([_quat_mat(aquat[k, bi]).T @ F[i] for i, k in enumerate(idx)])
    mag = np.linalg.norm(Floc, axis=1)
    k = int(np.argmax(mag))
    return {"job": j, "member": member, "t": ser["t"], "F_local": Floc, "peak_index": k, "peak_t": float(ser["t"][k]),
            "peak_local": Floc[k], "peak_N": float(mag[k]), "duration_s": float(ser["t"][-1] - ser["t"][0])}


@app.post("/mbd/jobs/{jid}/to-fea")
def mbd_to_fea(jid: str, body: dict = Body(...)):
    """把杆件和它受力最大时刻的力交给有限元：返回零件（同 /geometry）和建议的约束、载荷"""
    from cae import mech_mjcf as MC
    member = str(body.get("member") or "")
    ml = member_load(jid.replace("/", ""), member)
    ref = ml["job"]["model"]
    step = MC.member_step(ref["id"], member, ref.get("params") or {})
    sha = hashlib.sha256(step).hexdigest()
    d = _p("geo", sha)
    if not os.path.exists(os.path.join(d, "faces.json")):
        os.makedirs(d, exist_ok=True)
        open(os.path.join(d, "part.step"), "wb").write(step)
        ok, err = _isolated(_geo_child, (os.path.join(d, "part.step"), d), GEO_LIMIT_S)
        if not ok:
            raise HTTPException(422, "杆件模型生成失败：{}".format(err))
    geo = dict(_read_json(os.path.join(d, "faces.json")), sha=sha)
    holes = sorted([f for f in geo["faces"] if f["kind"] == "cylinder" and f.get("radius_mm") and
                    abs(f["center"][1]) < 1e-3 and abs(f["center"][2]) < 1e-3 and
                    f["radius_mm"] < 0.4 * MC.params(ref["id"], ref.get("params"))["link_width_m"] * 1000],
                   key=lambda f: f["center"][0])
    if len(holes) != 2:
        raise HTTPException(500, "没找到杆件两端的销孔")
    Fv = [round(float(x), 3) for x in ml["peak_local"]]
    name = MC.LABELS.get(member, member)
    return {"geometry": geo, "member": member, "member_name": name, "peak_t": ml["peak_t"], "peak_N": ml["peak_N"],
            "force_local_N": Fv,
            "rows": [{"kind": "fixed", "faces": [holes[0]["id"]]},
                     {"kind": "force", "faces": [holes[1]["id"]], "fx": Fv[0], "fy": Fv[1], "fz": Fv[2]}],
            "title": "{} 的{}（t = {:.3f} s，{:.0f} N）".format(MC.NAMES[ref["id"]], name, ml["peak_t"], ml["peak_N"]),
            "note": "A 端销孔固定、B 端销孔受动力学算出的最大力（构件坐标）；二力杆近似，略去惯性力和自重",
            "source": {"job": ml["job"]["id"], "member": member}}


@app.get("/mbd/jobs/{jid}/motors")
def mbd_motors(jid: str, safety: float = 1.2):
    """电机选型助手：每个转动关节的驱动（给定运动 / 力矩）"""
    from cae import motors as MT
    j = _read_json(_job_path(jid.replace("/", ""), "job.json"))
    if j.get("kind") != "mbd" or j["status"] != "done":
        raise HTTPException(409, "动力学结果还没出来")
    if not 1.0 <= safety <= 3.0:
        raise HTTPException(400, "安全系数要在 1–3 之间")
    ser = read_series(_job_path(j["id"], "series.bin"))
    out = []
    only = None
    if (j.get("model") or {}).get("source") == "mech":            # 机构：只有主动件装电机，从动件上的是工作阻力
        from cae import mech_mjcf as MC
        only = MC.DRIVER.get(j["model"]["id"])
    for d in j["stats"]["drives"]:
        jn = d["joint"]
        if d["kind"] == "coupled" or ("drive." + jn) not in ser or (only and jn != only):
            continue
        if not np.any(np.abs(ser["qd." + jn]) > 0) and not np.any(np.abs(ser["drive." + jn]) > 0):
            continue
        out.append(dict(MT.select(ser["drive." + jn], ser["qd." + jn], ser["qdd." + jn], safety), joint=jn))
    return {"joints": out, "table": MT.table()}


@app.get("/mbd/jobs/{jid}/reducer-life")
def mbd_reducer_life(jid: str):
    """机械臂关节孪生（第 15 轮）：一个循环里每个关节谐波减速器的平均负载力矩、平均输入转速、L10 寿命"""
    from twin import robot as RB
    j = _read_json(_job_path(jid.replace("/", ""), "job.json"))
    if j.get("kind") != "mbd" or j["status"] != "done":
        raise HTTPException(409, "动力学结果还没出来")
    ser = read_series(_job_path(j["id"], "series.bin"))
    joints = [d["joint"] for d in j["stats"]["drives"] if d["kind"] != "coupled" and ("drive." + d["joint"]) in ser
              and np.any(np.abs(ser["qd." + d["joint"]]) > 0)]
    if not joints:
        raise HTTPException(409, "这次计算里没有转动的驱动关节")
    return dict(RB.reducer_life(ser, joints), job=j["id"], title=j.get("title"), model=(j.get("model") or {}).get("id"))


@app.get("/mbd/jobs/{jid}/member-series")
def mbd_member_series(jid: str, member: str, direction: str = ""):
    """疲劳用：杆件 B 端受力在指定方向（构件坐标，默认最大力的方向）上的分量随时间的变化"""
    ml = member_load(jid.replace("/", ""), member)
    u = np.array([float(x) for x in direction.split(",")]) if direction else ml["peak_local"]
    u = u / max(np.linalg.norm(u), 1e-12)
    return {"values": [round(float(x), 4) for x in ml["F_local"] @ u], "duration_s": ml["duration_s"],
            "peak_N": ml["peak_N"], "direction": [float(x) for x in u]}


@app.get("/mbd/jobs/{jid}/joint-series")
def mbd_joint_series(jid: str, joint: str):
    """疲劳用（第 11 轮 F1）：关节驱动力矩（N·m 或 N）随时间的变化——机器人关节轴的载荷谱"""
    p = _job_path(jid.replace("/", ""), "job.json")
    if not os.path.exists(p):
        raise HTTPException(404, "没有这个任务")
    j = _read_json(p)
    if j.get("kind") != "mbd" or j["status"] != "done":
        raise HTTPException(409, "动力学结果还没出来")
    ser = read_series(_job_path(j["id"], "series.bin"))
    key = "drive." + joint
    if key not in ser:
        raise HTTPException(404, "这次计算里没有关节 {} 的驱动力矩".format(joint))
    v, t = ser[key], ser["t"]
    return {"values": [round(float(x), 4) for x in v], "duration_s": float(t[-1] - t[0]) if len(t) > 1 else 1.0,
            "peak": float(np.max(np.abs(v))), "joints": sorted(k[6:] for k in ser if k.startswith("drive."))}


@app.get("/jobs/{jid}/series.bin")
def job_series(jid: str):
    p = _job_path(jid.replace("/", ""), "series.bin")
    if not os.path.exists(p):
        raise HTTPException(404, "结果还没出来")
    return FileResponse(p, media_type="application/octet-stream")


@app.get("/jobs/{jid}/anim.bin")
def job_anim(jid: str):
    p = _job_path(jid.replace("/", ""), "anim.bin")
    if not os.path.exists(p):
        raise HTTPException(404, "结果还没出来")
    return FileResponse(p, media_type="application/octet-stream")


@app.get("/jobs")
def jobs(factory: str = "", owner: str = "", limit: int = 50, kind: str = ""):
    out = []
    for jid in sorted(os.listdir(_p("jobs")), reverse=True):
        try:
            j = _read_json(_job_path(jid, "job.json"))
        except Exception:  # noqa: BLE001
            continue
        if factory and j.get("factory") != factory:
            continue
        if owner and str(j.get("owner")) != owner:
            continue
        if kind and j.get("kind", "fea") != kind:
            continue
        out.append(_public(j))
        if len(out) >= limit:
            break
    return {"jobs": out}


@app.get("/jobs/{jid}")
def job(jid: str):
    p = _job_path(jid.replace("/", ""), "job.json")
    if not os.path.exists(p):
        raise HTTPException(404, "没有这个任务")
    return _public(_read_json(p))


@app.get("/jobs/{jid}/surface.bin")
def surface(jid: str):
    p = _job_path(jid.replace("/", ""), "surface.bin")
    if not os.path.exists(p):
        raise HTTPException(404, "结果还没出来")
    return FileResponse(p, media_type="application/octet-stream")


@app.post("/jobs/{jid}/report")
def report(jid: str, body: dict = Body(default={})):
    """Word 报告：images = [{data: dataURL, caption}]（浏览器截的云图），ai_text 可选"""
    p = _job_path(jid.replace("/", ""), "job.json")
    if not os.path.exists(p):
        raise HTTPException(404, "没有这个任务")
    j = _read_json(p)
    if j["status"] != "done":
        raise HTTPException(409, "结果还没出来")
    if j.get("kind") == "mbd":
        from cae import mbd_report as MR
        ser = read_series(_job_path(j["id"], "series.bin"))
        peaks = []
        for n in ser:
            if n.startswith("rf.") and n.endswith(".abs") and "wq_payload" not in n:
                b = n[3:-4]
                fm, mm = ser[n], ser["rm.{}.abs".format(b)]
                i, k = int(np.argmax(fm)), int(np.argmax(mm))
                peaks.append((b, float(fm[i]), float(ser["t"][i]), float(mm[k]), float(ser["t"][k])))
        data = MR.build(j, peaks, (body.get("images") or [])[:6], body.get("motors"), body.get("ai_text") or j.get("ai_text"))
        name = "动力学报告-{}.docx".format(j.get("item") or jid)
        return Response(data, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        headers={"Content-Disposition": "attachment; filename*=UTF-8''" + urllib.parse.quote(name)})
    if j.get("kind") == "cfd":
        from cae import cfd_report as CR
        aux = _read_json(_job_path(j["id"], "aux.json"))
        data = CR.build(j, aux, (body.get("images") or [])[:4], body.get("ai_text") or j.get("ai_text"))
        name = "流体分析报告-{}.docx".format(j.get("item") or jid)
        return Response(data, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        headers={"Content-Disposition": "attachment; filename*=UTF-8''" + urllib.parse.quote(name)})
    from cae import report as R
    imgs = (body.get("images") or [])[:4]
    data = R.build(j, imgs, body.get("ai_text") or j.get("ai_text"))
    name = "有限元报告-{}.docx".format(j.get("item") or jid)
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    headers={"Content-Disposition": "attachment; filename*=UTF-8''" + urllib.parse.quote(name)})


@app.post("/jobs/{jid}/note")
def note(jid: str, body: dict = Body(...)):
    """记下 AI 解释（报告用）"""
    p = _job_path(jid.replace("/", ""), "job.json")
    if not os.path.exists(p):
        raise HTTPException(404, "没有这个任务")
    _update(jid.replace("/", ""), ai_text=str(body.get("ai_text") or "")[:4000])
    return {"ok": True}


def _modal_child(step_path, setup, q):
    try:
        from cae import modal as MO
        stats, _ = MO.solve(open(step_path, "rb").read(), setup)
        q.put((True, stats))
    except Exception as e:  # noqa: BLE001
        q.put((False, str(e) or e.__class__.__name__))


@app.post("/jobs/{jid}/modal")
def modal(jid: str):
    """固有频率（第 11 轮 F2）：用这次强度计算的零件、材料、网格和支承，求前几阶固有频率；结果记进任务（报告用）"""
    p = _job_path(jid.replace("/", ""), "job.json")
    if not os.path.exists(p):
        raise HTTPException(404, "没有这个任务")
    j = _read_json(p)
    if j["status"] != "done" or j.get("kind") not in (None, "fea") or (j["setup"].get("analysis") or "static") != "static":
        raise HTTPException(409, "要先完成一次强度计算（固有频率用它的零件、材料和支承）")
    setup = dict(j["setup"])
    setup["material"] = M.get(setup["material_id"])
    ok, res = _isolated(_modal_child, (_p("geo", j["step_sha"], "part.step"), setup), TIME_LIMIT_S + 60)
    if not ok:
        raise HTTPException(422, "固有频率没算出来：{}".format(res))
    _update(j["id"], modal=res)
    return res


@app.post("/jobs/{jid}/fatigue")
def fatigue(jid: str, body: dict = Body(...)):
    """疲劳寿命：body = {ref_load, series, block_seconds, surface, size_factor, kf, haibach, label}。
    返回汇总 + 每个表面点的每块损伤（float32，base64），汇总也记进任务（报告用）"""
    import base64
    from cae import fatigue as FT
    p = _job_path(jid.replace("/", ""), "job.json")
    if not os.path.exists(p):
        raise HTTPException(404, "没有这个任务")
    j = _read_json(p)
    if j["status"] != "done":
        raise HTTPException(409, "有限元结果还没出来")
    series = body.get("series") or []
    if len(series) < 2 or len(series) > 200000:
        raise HTTPException(400, "载荷谱至少 2 个点")
    if body.get("surface", "ground") not in FT.SURFACE:
        raise HTTPException(400, "表面状态不对")
    surf = read_surface(_job_path(j["id"], "surface.bin"))
    try:
        D, summ = FT.compute(surf["vm"], float(body.get("ref_load") or 0), series, float(body.get("block_seconds") or 1),
                             M.get(j["setup"]["material_id"]), body.get("surface", "ground"),
                             float(body.get("size_factor") or 0.85), float(body.get("kf") or 1.0), bool(body.get("haibach", True)))
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    i = summ.pop("hot_index")
    summ["hot_at"] = [round(float(x), 3) for x in surf["positions"][i]]
    summ.update(label=body.get("label") or "", ref_load=body.get("ref_load"), ref_unit=body.get("ref_unit") or "",
                series_peak=float(np.max(np.abs(series))), series_points=len(series))
    _update(j["id"], fatigue=summ)
    return {"summary": summ, "damage_b64": base64.b64encode(np.asarray(D, "<f4").tobytes()).decode()}


@app.get("/geometry/{sha}/step")
def geometry_step(sha: str):
    p = _p("geo", sha.replace("/", ""), "part.step")
    if not os.path.exists(p):
        raise HTTPException(404, "没有这个零件")
    return Response(open(p, "rb").read(), media_type="application/step")


# ------------------------------------------------------------------ 数控编程（第 13 轮）
CAM_LIMIT_S = 120


def _cam_geo_child(step_path, outdir, q):
    try:
        from cae import cam_geom as CG
        data = open(step_path, "rb").read()
        out = {}
        for k, fn in (("turn", CG.turn_profile), ("mill", CG.mill_features)):
            try:
                out[k] = fn(data)
            except Exception as e:  # noqa: BLE001 —— 认不出来的写原因，另一种照样给
                out[k] = {"error": str(e) or e.__class__.__name__}
        _write_json(os.path.join(outdir, "cam.json"), out)
        q.put((True, None))
    except Exception as e:  # noqa: BLE001
        q.put((False, str(e) or e.__class__.__name__))


@app.post("/cam/recognize")
def cam_recognize(body: dict = Body(...)):
    """读入过的零件（/geometry）→ 车削轮廓、铣削特征"""
    sha = str(body.get("sha", "")).replace("/", "")
    d = _p("geo", sha)
    if not os.path.exists(os.path.join(d, "part.step")):
        raise HTTPException(400, "请先读入零件")
    if not os.path.exists(os.path.join(d, "cam.json")):
        ok, err = _isolated(_cam_geo_child, (os.path.join(d, "part.step"), d), GEO_LIMIT_S)
        if not ok:
            raise HTTPException(422, "识别不了这个零件：{}".format(err))
    return dict(_read_json(os.path.join(d, "cam.json")), sha=sha)


def _cam_child(spec, outdir, q):
    try:
        from cae import cam_job as J
        progs = J.generate(spec)
        for k, p in enumerate(progs):
            with open(os.path.join(outdir, "{}.nc".format(k)), "w", encoding="utf-8") as f:
                f.write(p.pop("gcode"))
            H = p["sim"].pop("_H", None)
            if H is not None:
                open(os.path.join(outdir, "h{}.bin".format(k)), "wb").write(np.asarray(H, "<f4").tobytes())
                p["sim"]["height"] = True
        q.put((True, {"programs": progs, "compare": spec.get("compare")}))
    except Exception as e:  # noqa: BLE001
        q.put((False, str(e) or e.__class__.__name__))


@app.post("/cam/jobs")
def cam_submit(body: dict = Body(...)):
    """编程单 → 生成程序、仿真、检查（不排队：一般 1–3 秒）"""
    spec = body.get("spec") or {}
    if spec.get("kind") not in ("turn", "slot", "mill25"):
        raise HTTPException(400, "编程单不对")
    if spec.get("machine") not in __import__("cae.cam_post", fromlist=["MACHINES"]).MACHINES:
        raise HTTPException(400, "没有这台机床")
    jid = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
    os.makedirs(_job_path(jid))
    j = {"id": jid, "kind": "cam", "status": "running", "created": time.time(), "spec": spec,
         "owner": body.get("owner"), "owner_name": body.get("owner_name"), "factory": body.get("factory"),
         "title": body.get("title") or "", "item": spec.get("item")}
    _write_json(_job_path(jid, "job.json"), j)
    ok, res = _isolated(_cam_child, (spec, _job_path(jid)), CAM_LIMIT_S)
    if ok:
        j = _update(jid, status="done", finished=time.time(), programs=res["programs"], compare=res["compare"],
                    stats={"seconds": round(time.time() - j["created"], 1),
                           "errors": sum(c["level"] == "error" for p in res["programs"] for c in p["checks"])})
    else:
        j = _update(jid, status="failed", finished=time.time(), error=res)
    return _public(j)


@app.get("/cam/jobs/{jid}/{k}.nc")
def cam_nc(jid: str, k: int):
    p = _job_path(jid.replace("/", ""), "{}.nc".format(int(k)))
    if not os.path.exists(p):
        raise HTTPException(404, "没有这个程序")
    return Response(open(p, encoding="utf-8").read(), media_type="text/plain; charset=utf-8")


@app.get("/cam/jobs/{jid}/h{k}.bin")
def cam_height(jid: str, k: int):
    p = _job_path(jid.replace("/", ""), "h{}.bin".format(int(k)))
    if not os.path.exists(p):
        raise HTTPException(404, "没有高度图")
    return FileResponse(p, media_type="application/octet-stream")


@app.get("/cam/machines")
def cam_machines():
    from cae.cam_post import MACHINES
    return {"machines": MACHINES}


@app.post("/cam/jobs/{jid}/submission")
def cam_submission(jid: str, body: dict = Body(...)):
    """记下这次编程挂到了哪次工艺规程提交（网页再打开时接着看审批）"""
    p = _job_path(jid.replace("/", ""), "job.json")
    if not os.path.exists(p):
        raise HTTPException(404, "没有这个任务")
    return _public(_update(jid.replace("/", ""), submission=str(body.get("submission") or "")[:40]))



# ------------------------------------------------------------------ 设计优化（第 14 轮）
OPT_LIMIT_S = 900


def _opt_child(spec, outdir, q):
    try:
        from cae import optimize as O

        def progress(rows):
            _write_json(os.path.join(outdir, "progress.json"), {"rows": rows})
        res = O.run(spec, progress)
        _write_json(os.path.join(outdir, "result.json"), res)
        best = (res.get("best") or [None])[0]
        q.put((True, {"seconds": res["seconds"], "trials": len(res["trials"]), "feasible": sum(1 for r in res["trials"] if r["ok"]),
                      "best": best, "base": res.get("base")}))
    except Exception as e:  # noqa: BLE001
        q.put((False, str(e) or e.__class__.__name__))


@app.get("/opt/problems")
def opt_problems():
    from cae import optimize as O
    return {"problems": [{"id": k, "label": O.LABELS[k], "vars": [{"name": n, "label": v[0], "low": v[1], "high": v[2], "step": v[3], "int": v[4]}
                                                                  for n, v in O.VARS[k].items()],
                          "default": O.DEFAULT_SPEC[k]} for k in O.VARS if k != "beam"],
            "objectives": {k: {"label": v[0], "unit": v[1], "sense": v[2]} for k, v in O.OBJ.items()}, "max_trials": O.MAX_TRIALS}


@app.post("/opt/jobs")
def opt_submit(body: dict = Body(...)):
    from cae import optimize as O
    spec = body.get("spec") or {}
    if spec.get("problem") not in O.VARS:
        raise HTTPException(400, "不认识的优化问题")
    jid = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
    os.makedirs(_job_path(jid))
    j = {"id": jid, "kind": "opt", "status": "queued", "created": time.time(), "spec": spec,
         "owner": body.get("owner"), "owner_name": body.get("owner_name"), "factory": body.get("factory"),
         "title": body.get("title") or O.LABELS[spec["problem"]], "item": body.get("item")}
    _write_json(_job_path(jid, "job.json"), j)
    _Q.put(jid)
    return _public(j)


@app.get("/opt/jobs/{jid}/trials")
def opt_trials(jid: str):
    d = _job_path(jid.replace("/", ""))
    for name in ("result.json", "progress.json"):
        p = os.path.join(d, name)
        if os.path.exists(p):
            return dict(_read_json(p), final=name == "result.json")
    return {"rows": [], "final": False}


# ---------- 拓扑优化（第 14 轮 H6）：平面件 SIMP，几秒算完，也走排队（和有限元抢同一个 CPU） ----------
TOPO_LIMIT_S = 180


def _topo_spec(body):
    from cae import topo as T
    s = body.get("spec") or {}
    if s.get("preset") == "plate":                 # 两孔平板（学习平台第 41 轮：设计软件的零件减重）
        try:
            ps = T.plate_spec(s.get("plate") or {})
        except (KeyError, TypeError, IndexError, ValueError) as e:
            raise HTTPException(400, "平板说明不对：{}".format(e)) from None
        out = {"preset": "plate", "plate": ps, "volfrac": float(s.get("volfrac") or 0.5), "penal": float(s.get("penal") or 3.0),
               "rmin": float(s.get("rmin") or 1.5), "material_id": s.get("material_id") or "45-QT"}
        if not 0.1 <= out["volfrac"] <= 0.9:
            raise HTTPException(400, "材料用量（体积比）要在 0.1–0.9 之间")
        if not 1.0 <= out["penal"] <= 5.0 or not 1.0 <= out["rmin"] <= 4.0:
            raise HTTPException(400, "惩罚指数要在 1–5、过滤半径要在 1–4 格之间")
        return out
    pre = s.get("preset") if s.get("preset") in T.PRESETS else "mbb"
    out = {"preset": pre, "nelx": int(s.get("nelx") or T.PRESETS[pre]["nelx"]), "nely": int(s.get("nely") or T.PRESETS[pre]["nely"]),
           "volfrac": float(s.get("volfrac") or 0.5), "penal": float(s.get("penal") or 3.0), "rmin": float(s.get("rmin") or 1.5),
           "length_mm": float(s.get("length_mm") or 300), "thickness_mm": float(s.get("thickness_mm") or 10),
           "force_n": float(s.get("force_n") or 2000), "material_id": s.get("material_id") or "6061-T6"}
    if out["nelx"] * out["nely"] > T.MAX_ELEMENTS or out["nelx"] < 8 or out["nely"] < 4:
        raise HTTPException(400, "网格 {}×{} 不合适：长边至少 8 格、短边至少 4 格，总数不超过 {}".format(out["nelx"], out["nely"], T.MAX_ELEMENTS))
    if not 0.1 <= out["volfrac"] <= 0.9:
        raise HTTPException(400, "材料用量（体积比）要在 0.1–0.9 之间")
    if not 1.0 <= out["penal"] <= 5.0 or not 1.0 <= out["rmin"] <= 4.0:
        raise HTTPException(400, "惩罚指数要在 1–5、过滤半径要在 1–4 格之间")
    if not 20 <= out["length_mm"] <= 2000 or not 1 <= out["thickness_mm"] <= 200:
        raise HTTPException(400, "长度 20–2000 mm、板厚 1–200 mm")
    try:
        M.get(out["material_id"])
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    return out


def _topo_child(spec, outdir, q):
    try:
        from cae import topo as T
        t0 = time.time()
        if spec["preset"] == "plate":
            r = T.run_plate(spec["plate"], spec["volfrac"], spec["penal"], spec["rmin"])
        else:
            r = T.run(spec["preset"], spec["nelx"], spec["nely"], spec["volfrac"], spec["penal"], spec["rmin"])
        r["seconds"] = round(time.time() - t0, 1)
        _write_json(os.path.join(outdir, "result.json"), r)
        q.put((True, {k: r[k] for k in ("iterations", "converged", "compliance", "grey", "seconds")}))
    except Exception as e:  # noqa: BLE001
        q.put((False, str(e) or e.__class__.__name__))


@app.get("/topo/presets")
def topo_presets():
    from cae import topo as T
    return {"presets": [dict(v, key=k) for k, v in T.PRESETS.items()], "max_elements": T.MAX_ELEMENTS}


@app.post("/topo/jobs")
def topo_submit(body: dict = Body(...)):
    from cae import topo as T
    spec = _topo_spec(body)
    jid = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
    os.makedirs(_job_path(jid))
    j = {"id": jid, "kind": "topo", "status": "queued", "created": time.time(), "spec": spec,
         "owner": body.get("owner"), "owner_name": body.get("owner_name"), "factory": body.get("factory"),
         "title": body.get("title") or "拓扑优化：" + (T.PRESETS[spec["preset"]]["label"].split("（")[0] if spec["preset"] in T.PRESETS else "两孔平板")}
    _write_json(_job_path(jid, "job.json"), j)
    _Q.put(jid)
    return _public(j)


@app.get("/topo/jobs/{jid}/result")
def topo_result(jid: str):
    p = _job_path(jid.replace("/", ""), "result.json")
    if not os.path.exists(p):
        raise HTTPException(404, "还没算完")
    return _read_json(p)


@app.post("/topo/jobs/{jid}/to-step")
def topo_to_step(jid: str):
    """两孔平板的结果 → 减重后的零件（STEP，登记成几何，同 /geometry）和轮廓（零件平面坐标，mm：外轮廓、孔）"""
    from cae import topo as T
    jid = jid.replace("/", "")
    j = _read_json(_job_path(jid, "job.json"))
    if j.get("kind") != "topo" or j["status"] != "done" or j["spec"].get("preset") != "plate":
        raise HTTPException(400, "不是算完的两孔平板拓扑优化")
    r = _read_json(_job_path(jid, "result.json"))
    try:
        step, g = T.plate_step(r["plate"], r["density"])
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    sha = hashlib.sha256(step).hexdigest()
    d = _p("geo", sha)
    if not os.path.exists(os.path.join(d, "faces.json")):
        os.makedirs(d, exist_ok=True)
        open(os.path.join(d, "part.step"), "wb").write(step)
        ok, err = _isolated(_geo_child, (os.path.join(d, "part.step"), d), GEO_LIMIT_S)
        if not ok:
            raise HTTPException(422, "板件模型生成失败：{}".format(err))
    geo = dict(_read_json(os.path.join(d, "faces.json")), sha=sha)
    ring = lambda c: [[round(x, 4), round(y, 4)] for x, y in list(c.coords)[:-1]]  # noqa: E731
    return {"geometry": geo, "outline": ring(g.exterior), "inner": [ring(h) for h in g.interiors], "area_mm2": round(g.area, 2),
            "thickness_mm": r["plate"]["thickness_mm"], "mass_ratio": r.get("mass_ratio")}


@app.post("/topo/jobs/{jid}/to-fea")
def topo_to_fea(jid: str, body: dict = Body(default={})):
    """拓扑结果按密度 0.5 取轮廓、拉伸成板件，交给有限元校核：返回零件（同 /geometry）和自动填好的约束、载荷"""
    from cae import topo as T
    jid = jid.replace("/", "")
    j = _read_json(_job_path(jid, "job.json"))
    if j.get("kind") != "topo" or j["status"] != "done":
        raise HTTPException(400, "拓扑优化还没算完")
    spec = dict(j["spec"], **{k: float(body[k]) for k in ("length_mm", "thickness_mm", "force_n") if body.get(k)})
    r = _read_json(_job_path(jid, "result.json"))
    try:
        step, pads, note, info = T.fea_part(spec["preset"], r["density"], spec["length_mm"], spec["thickness_mm"])
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    sha = hashlib.sha256(step).hexdigest()
    d = _p("geo", sha)
    if not os.path.exists(os.path.join(d, "faces.json")):
        os.makedirs(d, exist_ok=True)
        open(os.path.join(d, "part.step"), "wb").write(step)
        ok, err = _isolated(_geo_child, (os.path.join(d, "part.step"), d), GEO_LIMIT_S)
        if not ok:
            raise HTTPException(422, "板件模型生成失败：{}".format(err))
    geo = dict(_read_json(os.path.join(d, "faces.json")), sha=sha)
    try:
        rows = T.fea_rows(spec["preset"], pads, geo["faces"], spec["force_n"])
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    return {"geometry": geo, "rows": rows, "material_id": spec["material_id"], "info": info, "mesh_mm": round(max(2.0, info["cell_mm"]), 2),
            "title": "拓扑优化结果校核：{}（体积比 {:g}，{:g} N）".format(T.PRESETS[spec["preset"]]["label"].split("（")[0], spec["volfrac"], spec["force_n"]),
            "note": "按密度 0.5 取轮廓、拉伸成 {:g} mm 厚的板；{}".format(spec["thickness_mm"], note), "source": {"topo": jid}}


# ---------- 流体分析（第 16 轮）：OpenFOAM，排队、独立进程、限时 ----------
CFD_LIMIT_S = 1200


def _cfd_child(step_path, setup, outdir, q):
    try:
        import shutil
        from cae import cfd as CF
        work = os.path.join(outdir, "case")
        shutil.rmtree(work, ignore_errors=True)
        os.makedirs(work)

        def progress(stage):
            _write_json(os.path.join(outdir, "progress.json"), {"stage": stage, "t": time.time()})
        st, surf, aux = CF.solve(open(step_path, "rb").read(), setup, work, progress)
        _write_json(os.path.join(outdir, "surface.json"), {k: np.asarray(v).round(5).tolist() for k, v in surf.items()})
        _write_json(os.path.join(outdir, "aux.json"), aux)
        shutil.rmtree(work, ignore_errors=True)                     # 算完删掉 OpenFOAM 算例（几十 MB），只留结果
        q.put((True, st))
    except Exception as e:  # noqa: BLE001
        q.put((False, str(e) or e.__class__.__name__))


def _cfd_bench_child(outdir, q):
    try:
        import shutil
        from cae import cfd_bench as B
        work = os.path.join(outdir, "bench")
        res = B.all_cases(work)
        shutil.rmtree(work, ignore_errors=True)
        _write_json(os.path.join(outdir, "aux.json"), {"bench": res})
        q.put((True, {"bench": res}))
    except Exception as e:  # noqa: BLE001
        q.put((False, str(e) or e.__class__.__name__))


@app.post("/cfd/jobs")
def cfd_submit(body: dict = Body(...)):
    """流体分析任务：{step_sha, setup:{flow:{velocity_ms, direction, air_t_c}, heat:{wall_t_c}|null, turbulence, domain:{ground}, mesh:{cells_target, level}}}"""
    from cae import cfd as CF
    kind = body.get("kind") or "cfd"
    if kind == "cfd_bench":
        j = {"kind": "cfd_bench", "setup": {}, "title": "流体分析标准题核对"}
    else:
        sha = str(body.get("step_sha") or "")
        if not os.path.exists(_p("geo", sha, "part.step")):
            raise HTTPException(404, "先读入零件")
        setup = body.get("setup") or {}
        fl = setup.get("flow") or {}
        try:
            v = float(fl.get("velocity_ms", 5))
        except (TypeError, ValueError):
            raise HTTPException(400, "风速不对") from None
        if not 0.01 <= v <= 60:
            raise HTTPException(400, "风速要在 0.01–60 m/s 之间")
        if fl.get("direction", "+x") not in CF.DIRS:
            raise HTTPException(400, "来流方向只能是 ±x、±y、±z")
        tgt = int((setup.get("mesh") or {}).get("cells_target", 120000))
        if not 10000 <= tgt <= CF.MAX_CELLS:
            raise HTTPException(400, "网格目标单元数要在 1 万–{} 之间".format(CF.MAX_CELLS))
        if not 1 <= int((setup.get("mesh") or {}).get("level", 3)) <= 4:
            raise HTTPException(400, "表面加密级别要在 1–4 之间")
        if setup.get("heat") and abs(float(setup["heat"].get("wall_t_c", 70)) - float(fl.get("air_t_c", 25))) < 1:
            raise HTTPException(400, "表面温度和空气温度至少差 1 ℃")
        j = {"kind": "cfd", "step_sha": sha, "setup": setup, "title": body.get("title") or "流体分析"}
    jid = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
    os.makedirs(_job_path(jid))
    j.update(id=jid, status="queued", created=time.time(), owner=body.get("owner"), owner_name=body.get("owner_name"),
             factory=body.get("factory"), item=body.get("item"))
    _write_json(_job_path(jid, "job.json"), j)
    _Q.put(jid)
    return _public(j)


@app.get("/cfd/jobs/{jid}/result")
def cfd_result(jid: str):
    d = _job_path(jid.replace("/", ""))
    out = {}
    for name in ("aux", "surface", "progress"):
        p = os.path.join(d, name + ".json")
        if os.path.exists(p):
            out[name] = _read_json(p)
    if not out:
        raise HTTPException(404, "还没有结果")
    return out
