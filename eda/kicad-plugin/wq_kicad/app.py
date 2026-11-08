# -*- coding: utf-8 -*-
"""问渠电子 KiCad 插件（第 113 轮 P6）：连上 KiCad → 读编辑器里的板子 → 跑问渠电子的检查 → 在浏览器里开一个
只在本机的结果页（127.0.0.1）→ 点一条，KiCad 里选中那个器件并放大；还能把摆放读回设计描述、出报告。

KiCad 9 的插件接口还不能在编辑器里嵌面板，所以结果页是插件自己开的（浏览器标签页）。全是确定性代码，
不调 AI、不联网；结果页只监听本机地址，带一次性口令，别的网页调不到。"""

from __future__ import annotations

import glob
import html
import json
import os
import secrets
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

IDLE_S = 2 * 3600  # 两个小时没人点，插件自己退出
ZOOM_ACTION = "common.Control.zoomFitSelection"


def find_design(folder):
    """设计描述：板子所在文件夹和上一层里的 design.yaml 或 variant.yaml（没有就不做依赖设计描述的检查）"""
    for d in (folder, os.path.dirname(folder)):
        for name in ("design.yaml", "variant.yaml"):
            p = os.path.join(d, name)
            if os.path.isfile(p):
                return p
    return None


def find_factory(folder, here):
    """工艺能力表：工程文件夹里的 wqeda-factory.yaml；没有就用插件自带的示例工厂（虚构）"""
    p = os.path.join(folder, "wqeda-factory.yaml")
    if os.path.isfile(p):
        return p
    found = sorted(glob.glob(os.path.join(here, "factories", "example-smt.yaml")))
    return found[0] if found else None


def run_checks(model, design_path, factory_path, thermal=False):
    """板子模型 → 检查结果（和网页、工厂端同一套判定）"""
    from wqeda.checks import basic, layout, process
    from wqeda.schema import capability
    from wqeda.schema import design as D

    cap = capability.load(factory_path)
    x = None
    if design_path:
        raw = D.read_yaml(design_path)
        if raw.get("format") == D.VARIANT_FORMAT:
            x = D.expand(*D.load_variant(design_path))
        else:
            x = D.expand(D.load_design(design_path))
    rows = basic.run(model, cap)["checks"] + process.run(model, cap, x) + (layout.run(model, x) if x else [])
    return {"rows": rows, "factory": cap.get("factory"), "design": design_path}


def refs_in(row):
    from wqeda.factory import refs_of

    return refs_of(row)


class Session:
    """一次插件运行：KiCad 连接、板子、检查结果"""

    def __init__(self, kicad, board, folder, here):
        self.kicad, self.board, self.folder, self.here = kicad, board, folder, here
        self.design = find_design(folder)
        self.factory = find_factory(folder, here)
        self.result = None
        self.last = time.time()
        self.token = secrets.token_urlsafe(16)

    def check(self):
        from wqeda.readers import kicad_ipc

        model = kicad_ipc.read(self.board)
        self.result = run_checks(model, self.design, self.factory)
        self.model = model
        return self.result

    def jump(self, i):
        row = self.result["rows"][i]
        refs = refs_in(row)
        fps = {fp.reference_field.text.value: fp for fp in self.board.get_footprints()}
        items = [fps[r] for r in refs if r in fps]
        if not items:
            return "这一条没有位号，请按说明里的坐标找"
        self.board.clear_selection()
        self.board.add_to_selection(items)
        try:
            self.kicad.run_action(ZOOM_ACTION)
        except Exception:  # noqa: BLE001 —— 放大不了也已经选中了
            pass
        return "已在 KiCad 里选中 " + "、".join(refs[: len(items)])

    def readback(self):
        from wqeda import readback as R
        from wqeda.schema import design as D

        if not self.design:
            return "没找到设计描述（design.yaml），读回不了"
        raw = D.read_yaml(self.design)
        if raw.get("format") == D.VARIANT_FORMAT:
            return "变体文件不能直接写回：请改基础设计描述或变体的 add_placement"
        ch = R.compare(R.read_ipc(self.board), raw)
        lines = R.describe(ch)
        if ch["none"] or not (ch["moved"] or ch["holes"]["changed"] or ch["pours"]["changed"]):
            return "\n".join(lines)
        with open(self.design, encoding="utf-8") as f:
            text = R.patch(f.read(), ch)
        D.validate_design(D.read_yaml_text(text))
        out = os.path.splitext(self.design)[0] + ".readback.yaml"
        with open(out, "w", encoding="utf-8") as f:
            f.write(text)
        return "\n".join(lines + ["写好了：" + out + "（原文件没动，核对后自己替换）"])

    def report(self):
        from wqeda import report as W

        if not self.design:
            return "没找到设计描述（design.yaml），报告要用它算电气部分"
        rep = W.build(
            self.design,
            self.factory,
            board=self.model,
            drc=False,
            sim=False,
            thermal=bool(os.environ.get("WQ_PLUGIN_THERMAL")),
        )
        out = os.path.join(self.folder, "wqeda-report")
        W.write(out, rep, self.design, sim=False)
        webbrowser.open("file://" + os.path.join(out, "report.html"))
        return "报告写在 " + out


PAGE = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "page.html"), encoding="utf-8").read()


def render(session):
    e = html.escape
    names = {"pass": "通过", "fail": "不通过", "pending": "待核对", "unknown": "未知"}
    rank = {"fail": 0, "unknown": 1, "pending": 2, "pass": 3}
    rows = []
    order = sorted(range(len(session.result["rows"])), key=lambda i: rank[session.result["rows"][i]["status"]])
    for i in order:
        r = session.result["rows"][i]
        v = "—" if r.get("value") is None else r["value"]
        lim = "" if r.get("limit") is None else " / 限 {}".format(r["limit"])
        refs = refs_in(r)
        btn = '<button data-i="{}">定位</button>'.format(i) if refs else ""
        rows.append(
            "<tr><td>{} {}</td><td class='{}'><b>{}</b></td><td>{}{} {}</td><td>{}</td><td>{}</td></tr>".format(
                e(r["key"]),
                e(r["name"]),
                r["status"],
                names[r["status"]],
                e(str(v)),
                e(str(lim)),
                e(r.get("unit") or ""),
                e(r.get("detail") or r.get("why") or ""),
                btn,
            )
        )
    sub = "工艺能力表：{}；设计描述：{}".format(
        session.result["factory"], session.design or "没找到（只做不依赖设计描述的检查）"
    )
    return PAGE.replace("{sub}", e(sub)).replace("{rows}", "".join(rows)).replace("{token}", json.dumps(session.token))


def serve(session, open_browser=True):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype):
            data = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):  # noqa: N802
            u = urlparse(self.path)
            if u.path != "/" or parse_qs(u.query).get("t", [""])[0] != session.token:
                return self._send(404, "not found", "text/plain")
            session.last = time.time()
            self._send(200, render(session), "text/html; charset=utf-8")

        def do_POST(self):  # noqa: N802
            u = urlparse(self.path)
            q = parse_qs(u.query)
            if q.get("t", [""])[0] != session.token:
                return self._send(403, json.dumps({"msg": "口令不对"}), "application/json")
            session.last = time.time()
            try:
                if u.path == "/jump":
                    msg, reload = session.jump(int(q["i"][0])), False
                elif u.path == "/recheck":
                    session.check()
                    msg, reload = "重新检查好了", True
                elif u.path == "/readback":
                    msg, reload = session.readback(), False
                elif u.path == "/report":
                    msg, reload = session.report(), False
                else:
                    return self._send(404, json.dumps({"msg": "没有这个操作"}), "application/json")
            except Exception as ex:  # noqa: BLE001 —— 出错写在页面上，插件不退出
                msg, reload = "出错了：{}".format(ex), False
            self._send(200, json.dumps({"msg": msg, "reload": reload}, ensure_ascii=False), "application/json")

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    url = "http://127.0.0.1:{}/?t={}".format(srv.server_address[1], session.token)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    if open_browser:
        webbrowser.open(url)
    return srv, url


def main():
    from kipy import KiCad

    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    kicad = KiCad()
    board = kicad.get_board()
    path = board.document.board_filename
    proj = board.get_project()
    folder = getattr(proj, "path", "") or os.path.dirname(path) or os.getcwd()
    s = Session(kicad, board, folder, here)
    s.check()
    srv, url = serve(s)
    print("问渠电子检查结果：" + url, flush=True)
    while time.time() - s.last < IDLE_S:
        time.sleep(5)
    srv.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
