# -*- coding: utf-8 -*-
"""
问渠数字工厂 · FreeCAD “发布”宏（输出轴 SH-301）

在 FreeCAD 里：宏 → 宏… → 选中本文件 → 执行。它会：
  1. 按 wq_shaft.py 的 PARAMS 建模，导出 STEP；
  2. 生成零件图（SVG）和键槽 G 代码（wq_cam_keyway.py）；
  3. 按毛坯尺寸算 45 钢用量，得到新版 BOM；
  4. 登录数字工厂工作台，上传文件，把 design.release 和 design.gcode 两条消息发到统一数据总线；
     桥接收到后在 ERPNext 里把 SH-301 的版本号加一、挂上附件，用量变了就建新版 BOM；AI 会检查在制工单是否受影响。

先改下面 CONFIG 里的工作台地址和你的名字。命令行（不开界面）也能跑：
  "C:\\Program Files\\FreeCAD 1.1\\bin\\FreeCADCmd.exe" wq_publish.py
没有装 FreeCAD 时，用普通 Python 运行也可以（不导出 STEP，其余照常），便于测试：
  py wq_publish.py --note "键槽长 45 → 42"
"""
import datetime as dt
import hashlib
import json
import math
import os
import sys
import urllib.request
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import wq_cam_keyway  # noqa: E402
import wq_drawing  # noqa: E402
import wq_shaft  # noqa: E402

CONFIG = {
    "hub": os.environ.get("WQ_HUB_URL", "http://localhost:8100"),   # 数字工厂工作台地址
    "name": os.environ.get("WQ_USER", "工艺员"),                    # 你的名字（教学模式按它记分）
    "mode": os.environ.get("WQ_MODE", "teach"),                     # teach 教学 / prod 生产
    "token": os.environ.get("WQ_TOKEN", ""),                        # 线上登录凭证：从“设计与工艺”页下载的宏包里已填好（7 天有效）
    "item": "SH-301",
    "title": "输出轴 Output shaft",
    "material_item": "RM-45-D50",      # 45 钢圆棒 Ø50
    "bar_d": 50.0,                     # 棒料直径 mm
    "blank_allowance": 15.0,           # 下料留量：两端车削与夹持 mm
    "density": 7.85e-6,                # kg/mm³
}


# ---------------------------------------------------------------- 纯计算
def blank_kg(params, cfg=CONFIG):
    total = sum(length for _, length in params["segments"])
    vol = math.pi * (cfg["bar_d"] / 2) ** 2 * (total + cfg["blank_allowance"])
    return round(vol * cfg["density"], 1)


def bom(params, cfg=CONFIG):
    return [{"item_code": cfg["material_item"], "qty": blank_kg(params, cfg)}]


# ---------------------------------------------------------------- 与工作台通信
def _req(url, data=None, headers=None, method=None):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def login(hub, name, mode):
    body = json.dumps({"name": name, "role": "engineer", "mode": mode}).encode()
    return _req(hub + "/api/login", body, {"Content-Type": "application/json"})["token"]


def upload(hub, token, filename, content, mime):
    boundary = uuid.uuid4().hex
    body = (("--{}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{}\"\r\nContent-Type: {}\r\n\r\n"
             .format(boundary, filename, mime)).encode("utf-8") + content + "\r\n--{}--\r\n".format(boundary).encode())
    r = _req(hub + "/api/files", body, {"Content-Type": "multipart/form-data; boundary=" + boundary,
                                         "x-wq-token": token})
    return {"name": filename, "url": r["url"], "sha256": r["sha256"], "size": r["size"]}


def bus_publish(hub, token, topic, type_, data, mode, corr=None):
    msg = {"v": 1, "id": str(uuid.uuid4()), "ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds")
           .replace("+00:00", "Z"), "type": type_, "source": "freecad", "mode": mode, "corr": corr, "data": data}
    body = json.dumps({"topic": topic, "message": msg}, ensure_ascii=False).encode("utf-8")
    return _req(hub + "/api/bus/publish", body, {"Content-Type": "application/json", "x-wq-token": token})


def current_revision(hub, token, item):
    req = urllib.request.Request(hub + "/api/design/" + item, headers={"x-wq-token": token})
    with urllib.request.urlopen(req, timeout=30) as r:
        rel = json.loads(r.read())["releases"]
    return max([x["revision"] for x in rel] + [1])        # 没发布过：工厂数据里的现行版本算第 1 版


# ---------------------------------------------------------------- 发布
def publish(hub_url=None, token=None, author=None, params=None, change_note="", step_bytes=None, cfg=CONFIG, mode=None):
    hub = (hub_url or cfg["hub"]).rstrip("/")
    mode = mode or cfg["mode"]
    author = author or cfg["name"]
    params = params or wq_shaft.PARAMS
    problems = wq_shaft.check_keyway(params["segments"], params["keyway"])
    if problems:
        raise ValueError("；".join(problems))
    token = token or cfg.get("token") or login(hub, author, mode)
    item = cfg["item"]
    rev = current_revision(hub, token, item) + 1
    tag = "{}-rev{}".format(item, rev)

    files = []
    if step_bytes is None:
        try:
            import FreeCAD  # noqa: F401 —— 在 FreeCAD 里运行时建模并导出
            out_dir = os.path.join(os.path.expanduser("~"), "wq-digital-factory", tag)
            _, base = wq_shaft.build(params, out_dir=out_dir, name=tag)
            step_bytes = open(base + ".step", "rb").read()
        except ImportError:
            step_bytes = None
    if step_bytes:
        files.append(dict(upload(hub, token, tag + ".step", step_bytes, "application/step"), kind="step"))
    drawing = wq_drawing.svg(params, item, cfg["title"], rev, author).encode("utf-8")
    files.append(dict(upload(hub, token, tag + "-drawing.svg", drawing, "image/svg+xml"), kind="drawing"))
    gcode, info = wq_cam_keyway.generate(params, item=item, revision=rev)
    gfile = upload(hub, token, tag + "-keyway.nc", gcode.encode("utf-8"), "text/plain")

    data = {"item": item, "revision": rev, "params": params, "bom": bom(params, cfg), "files": files,
            "author": author, "change_note": change_note, "total_length_mm": sum(l for _, l in params["segments"]),
            "tool": "FreeCAD 1.1 + wq_publish.py"}
    bus_publish(hub, token, "wq/gearbox/design/{}/release".format(item.lower()), "design.release", data, mode)
    g = {"item": item, "revision": rev, "operation": "铣键槽 Keyway milling", "machine": "key-01",
         "gcode_ref": gfile["url"], "gcode_url": gfile["url"], "sha256": gfile["sha256"],
         "tools": info["tools"], "est_time_s": info["est_time_s"], "cut_length_mm": info["cut_length_mm"],
         "slot": info["slot"]}
    bus_publish(hub, token, "wq/gearbox/design/{}/gcode".format(item.lower()), "design.gcode", g, mode)
    return {"revision": rev, "files": files, "gcode": gfile, "gcode_lines": gcode.count("\n"), "bom": data["bom"]}


def _message(text):
    try:
        import FreeCAD as App
        App.Console.PrintMessage(text + "\n")
    except ImportError:
        print(text)


if __name__ == "__main__":
    note = ""
    if "--note" in sys.argv:
        note = sys.argv[sys.argv.index("--note") + 1]
    try:
        r = publish(change_note=note)
        _message("已发布 {} 第 {} 版：{} 个文件，键槽 G 代码 {} 行，45 钢 {} kg。到工作台“工艺员”页查看。".format(
            CONFIG["item"], r["revision"], len(r["files"]) + 1, r["gcode_lines"], r["bom"][0]["qty"]))
    except Exception as e:  # noqa: BLE001
        _message("发布失败：{}".format(e))
        raise
