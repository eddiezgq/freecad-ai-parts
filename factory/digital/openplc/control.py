# -*- coding: utf-8 -*-
"""OpenPLC 兼容性检查服务（第 18 轮第 8 步）：跑在 OpenPLC 运行时的容器里，只在数字工厂内部网络。

POST /check {"st": 问渠 ST 程序, "unit": "press" | "sorter", "seconds": 60}
  1. 把程序改写成 OpenPLC 能编译的完整程序（vplc/openplc_st.py：I/O 声明、地址映射、CONFIGURATION）；
  2. 经 OpenPLC 自己的网页接口上传、编译（MatIEC + g++），读编译日志；
  3. 启动“虚拟设备从站”（vplc/js/plant_server.mjs，Modbus TCP，127.0.0.1:5020），启动 PLC，按真实时间运行 seconds 秒；
  4. 停 PLC，返回 {ok, stage, log, summary}：stage = compile（编译不过）/ run（运行了）。
GET /health
同一时间只做一个检查（只有一个 OpenPLC 运行时）。
"""
import http.cookiejar
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
VPLC = os.environ.get("WQ_VPLC_DIR", os.path.join(os.path.dirname(HERE), "vplc"))
sys.path.insert(0, os.path.dirname(VPLC))
from vplc.openplc_st import to_openplc  # noqa: E402

OPENPLC = os.environ.get("WQ_OPENPLC_WEB", "http://127.0.0.1:8080")
USER, PASSWORD = os.environ.get("WQ_OPENPLC_USER", "openplc"), os.environ.get("WQ_OPENPLC_PASSWORD", "openplc")
PLANT_PORT = int(os.environ.get("WQ_PLANT_PORT", "5020"))
NODE = os.environ.get("WQ_NODE", "node")
LOCK = threading.Lock()


class Web:
    def __init__(self):
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def req(self, path, data=None, files=None, timeout=60):
        headers = {}
        body = None
        if files:
            b = "----wq" + uuid.uuid4().hex
            parts = []
            for k, v in (data or {}).items():
                parts.append("--{}\r\nContent-Disposition: form-data; name=\"{}\"\r\n\r\n{}\r\n".format(b, k, v).encode())
            for k, (fn, content) in files.items():
                parts.append("--{}\r\nContent-Disposition: form-data; name=\"{}\"; filename=\"{}\"\r\nContent-Type: text/plain\r\n\r\n".format(b, k, fn).encode()
                             + content + b"\r\n")
            body = b"".join(parts) + "--{}--\r\n".format(b).encode()
            headers["Content-Type"] = "multipart/form-data; boundary=" + b
        elif data is not None:
            body = urllib.parse.urlencode(data).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        r = urllib.request.Request(OPENPLC + path, data=body, headers=headers, method="POST" if body is not None else "GET")
        with self.op.open(r, timeout=timeout) as f:
            return f.read().decode("utf-8", "replace")

    def login(self):
        t = self.req("/login", {"username": USER, "password": PASSWORD})
        if "Bad credentials" in t or "bad_login" in t:
            raise RuntimeError("OpenPLC 登录失败")

    def ensure_device(self, n_di, n_coil, n_ir):
        """从站设备“wq_plant”：127.0.0.1:5020，离散输入、线圈、输入寄存器的个数按设备的 I/O 表"""
        page = self.req("/modbus")
        for dev in re.findall(r"modbus-edit-device\?table_id=(\d+)", page):
            self.req("/delete-device?dev_id=" + dev)
        self.req("/add-modbus-device", {
            "device_name": "wq_plant", "device_protocol": "TCP", "device_id": "1", "device_ip": "127.0.0.1", "device_port": str(PLANT_PORT),
            "device_cport": "", "device_baud": "115200", "device_parity": "None", "device_data": "8", "device_stop": "1", "device_pause": "0",
            "di_start": "0", "di_size": str(n_di), "do_start": "0", "do_size": str(n_coil), "ai_start": "0", "ai_size": str(n_ir),
            "aor_start": "0", "aor_size": "0", "aow_start": "0", "aow_size": "0"})

    def compile(self, src):
        page = self.req("/upload-program", files={"file": ("wq.st", src.encode())})
        m = re.search(r"id='prog_file' name='prog_file'[^>]*value='([^']+)'|value='([^']+)' id='prog_file'", page)
        if not m:
            raise RuntimeError("OpenPLC 没有接收程序文件")
        fn = m.group(1) or m.group(2)
        self.req("/upload-program-action", {"prog_name": "WenQuest", "prog_descr": "WenQuest virtual PLC check", "prog_file": fn,
                                            "epoch_time": str(int(time.time()))})
        self.req("/compile-program?file=" + fn)
        t0 = time.time()
        log = ""
        while time.time() - t0 < 240:
            time.sleep(2)
            log = self.req("/compilation-logs")
            if "Compilation finished successfully" in log:
                return True, log
            if "Compilation finished with errors" in log:
                return False, log
        return False, log + "\n(编译超时)"


def io_of(unit):
    out = subprocess.run([NODE, "-e", "process.stdout.write(JSON.stringify(require(process.argv[1])[process.argv[2]]().io))",
                          os.path.join(VPLC, "js", "plants.js"), unit], capture_output=True, timeout=30)
    return json.loads(out.stdout)


def check(st, unit, seconds=60):
    with LOCK:
        io = io_of(unit)
        try:
            src = to_openplc(st, io)
        except ValueError as e:
            return {"ok": False, "stage": "prepare", "log": str(e)}
        w = Web()
        w.login()
        w.req("/stop_plc")
        n_di = 1 + max([(int(m.group(1)) * 8 + int(m.group(2))) for x in io for m in [re.match(r"%IX(\d+)\.(\d+)", x["addr"])] if m] or [0])
        n_coil = 1 + max([(int(m.group(1)) * 8 + int(m.group(2))) for x in io for m in [re.match(r"%QX(\d+)\.(\d+)", x["addr"])] if m] or [0])
        n_ir = sum(1 for x in io if x["addr"].startswith("%IW"))
        w.ensure_device(n_di, n_coil, n_ir)
        ok, log = w.compile(src)
        tail = "\n".join([ln for ln in log.replace("<br>", "\n").splitlines() if ln.strip()][-25:])
        if not ok:
            errs = [ln for ln in log.replace("<br>", "\n").splitlines() if "error" in ln.lower()]
            return {"ok": False, "stage": "compile", "log": "\n".join(errs[:20]) or tail, "program": src}   # 行号对应改写后的程序
        plant = subprocess.Popen([NODE, os.path.join(VPLC, "js", "plant_server.mjs"), unit, str(seconds), str(PLANT_PORT)],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        time.sleep(0.5)
        w.req("/start_plc")
        try:
            out, err = plant.communicate(timeout=seconds + 60)
        finally:
            try:
                w.req("/stop_plc")
            except Exception:  # noqa: BLE001
                pass
        if plant.returncode != 0:
            return {"ok": False, "stage": "run", "log": err.decode("utf-8", "replace")[-1000:]}
        r = json.loads(out.decode())
        return {"ok": True, "stage": "run", "log": tail, "summary": r["summary"], "polls": r["polls"], "writes": r["writes"],
                "alarms": r["alarms"], "cycles": r.get("cycles"), "hazards": r.get("hazards"), "seconds": seconds}


class H(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path == "/health":
            try:
                Web().login()
                return self._send(200, {"ok": True, "busy": LOCK.locked()})
            except Exception as e:  # noqa: BLE001
                return self._send(503, {"ok": False, "error": str(e)})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/check":
            return self._send(404, {"error": "not found"})
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
            unit = body.get("unit", "press")
            if unit not in ("press", "sorter"):
                return self._send(422, {"error": "unit"})
            r = check(body["st"], unit, max(10, min(300, int(body.get("seconds", 60)))))
            self._send(200, r)
        except Exception as e:  # noqa: BLE001
            self._send(500, {"ok": False, "stage": "error", "log": str(e)[:1000]})

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("WQ_CHECK_PORT", "8300"))), H).serve_forever()
