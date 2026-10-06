# -*- coding: utf-8 -*-
"""第 18 轮第 8 步《PLC 原理及实践》：数字工厂虚拟 PLC。
引擎副本与学习平台一致；一个（缩短的）班次能算、能按格式回放到总线；枢纽记录班次；任务单里“PLC 程序”这项交付物
上传即检查（含“状态变量不得保持”），老师批准后程序下载到虚拟 PLC 跑一班，结果回到任务单和“虚拟 PLC”页。
需要 node（班次计算）；数据库部分需要本机 PostgreSQL（WQ_TEST_DB）。"""
import importlib
import os
import shutil

import pytest

import wqbus

HERE = os.path.dirname(os.path.abspath(__file__))
DIGITAL = os.path.dirname(HERE)
REPO = os.path.dirname(os.path.dirname(DIGITAL))
LABKIT = os.path.join(REPO, "services", "gateway", "app", "production", "labkit")
BOOK = os.path.join(REPO, "textbook", "plc", "ch15", "code")
EX = os.path.join(DIGITAL, "vplc", "examples")
DSN = os.environ.get("WQ_TEST_DB", "postgresql://postgres@localhost:5433/wq_test").rsplit("/", 1)[0] + "/wq_vplc_test"

need_node = pytest.mark.skipif(not shutil.which(os.environ.get("WQ_NODE", "node")), reason="需要 node")


def _read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


def test_engine_copies_match_the_learning_platform():
    """vplc/js 里的引擎、虚拟设备、班次模拟是学习平台 labkit 的副本：两边必须一样（改了一边要同步另一边）。"""
    if not os.path.isdir(LABKIT):
        pytest.skip("不在完整仓库里")
    for f in ("plc.js", "plants.js", "shift.js"):
        assert _read(os.path.join(DIGITAL, "vplc", "js", f)) == _read(os.path.join(LABKIT, f)), f + " 与学习平台的不一致"
    if os.path.isdir(BOOK):
        assert _read(os.path.join(EX, "press_p15_5_1.st")) == _read(os.path.join(BOOK, "p15_5_1.st"))


def test_message_types():
    wqbus.make("plc.download", "hub", {"run_id": "PLC-1", "program": "PROGRAM Main END_PROGRAM", "hours": 8, "seed": 1})
    wqbus.make("plc.cycle", "plc/press-01", {"run_id": "PLC-1", "good": True, "n": 3, "cycle_s": 15.2, "progress": 0.5})
    wqbus.make("plc.shift", "plc/press-01", {"run_id": "PLC-1", "phase": "done", "summary": {"parts": 3}})
    with pytest.raises(wqbus.ValidationError):
        wqbus.make("plc.download", "hub", {"run_id": "PLC-1", "program": "x", "hours": 30})
    assert wqbus.PLC_UNITS == {"press-01": "press", "sort-01": "sorter"}
    assert wqbus.unit_topic("press-01", "cmd") == "wq/gearbox/machining/press-01/cmd"


@need_node
def test_check_import_and_a_short_shift():
    from vplc.runner import compute, tool
    st = _read(os.path.join(EX, "press_p15_5_1.st"))
    c = tool({"op": "check", "st": st, "unit": "press"})
    assert c["ok"] and not [r for r in c["review"] if r["level"] == "error"]
    bad = tool({"op": "check", "st": "PROGRAM Main Y_Clamp := ; END_PROGRAM", "unit": "press"})
    assert not bad["ok"] and "1" in bad["error"]
    # 0.3 小时（18 分钟）：合格件、节拍、无报警（这段时间里没有安排设备故障）
    r = compute("press-01", st, hours=0.3)
    s = r["summary"]
    assert r["ok"] and s["parts"] > 50 and s["good"] >= s["parts"] - 5 and 10 < s["cycle_mean_s"] < 25 and s["hazards"] == 0
    # 分拣线参考程序：推杆 2 卡住时报 E-SORT-2
    r = tool({"op": "shift", "unit": "sorter", "program": {"st": _read(os.path.join(EX, "sorter_ref.st"))}, "hours": 0.5,
              "breakdowns": [{"at_h": 0.1, "fault": "y2stuck", "repair_min": 5}]})
    assert r["ok"] and r["summary"]["alarm_codes"].get("E-SORT-2") == 1 and r["summary"]["parts"] > 300


def _fake_shift(hours=0.05):
    return {"ok": True, "error": None, "summary": {"parts": 2, "good": 1, "nok": 1, "alarms": 1},
            "events": [{"t": 0, "kind": "state", "state": "idle"}, {"t": 1000, "kind": "state", "state": "run"},
                       {"t": 5000, "kind": "cycle", "good": True, "cycle_s": None, "peak_kN": 5.6},
                       {"t": 6000, "kind": "alarm", "code": "E-PRESS-1", "text": ["夹紧超时", "Clamp timeout"]},
                       {"t": 7000, "kind": "recover"},
                       {"t": 20000, "kind": "cycle", "good": False, "cycle_s": 15.0, "peak_kN": 2.1}]}


def test_replay_publishes_well_formed_messages_and_cancels():
    from vplc.runner import VirtualPLC
    out = []
    v = VirtualPLC(lambda tp, ty, src, d, corr: out.append((tp, wqbus.make(ty, src, d, corr=corr))),
                   compute_fn=lambda unit, st, h, seed: _fake_shift())
    msg = wqbus.make("plc.download", "hub", {"run_id": "PLC-A", "program": "x", "hours": 0.05, "speed": 0})
    assert not v.handle("grd-01", msg) and v.handle("press-01", msg, block=True)
    types = [m["type"] for _, m in out]
    assert types[0] == "plc.shift" and out[0][1]["data"]["phase"] == "started"
    assert out[-1][1]["data"]["phase"] == "done" and out[-1][1]["data"]["summary"]["parts"] == 2
    cyc = [m["data"] for _, m in out if m["type"] == "plc.cycle"]
    assert [c["n"] for c in cyc] == [1, 2] and cyc[1]["nok_n"] == 1 and cyc[0]["peak_kN"] == 5.6
    al = [m for _, m in out if m["type"] == "machine.event"]
    assert al[0]["data"]["code"] == "E-PRESS-1" and al[0]["source"] == "plc/press-01" and al[1]["data"]["event"] == "recover"
    assert all(tp.startswith("wq/gearbox/machining/press-01/") for tp, _ in out)
    # 新程序到来，正在回放的班次作废
    out.clear()
    slow = wqbus.make("plc.download", "hub", {"run_id": "PLC-B", "program": "x", "hours": 0.05, "speed": 0.001})
    v.handle("press-01", slow)
    import time
    time.sleep(0.3)
    v.handle("press-01", msg, block=True)
    time.sleep(0.6)
    phases = [(m["data"]["run_id"], m["data"]["phase"]) for _, m in out if m["type"] == "plc.shift"]
    assert ("PLC-B", "cancelled") in phases and ("PLC-A", "done") in phases


# ---------------------------------------------------------------- 枢纽与任务单（PostgreSQL）
@pytest.fixture()
def db():
    psycopg = pytest.importorskip("psycopg")
    try:
        with psycopg.connect(DSN.rsplit("/", 1)[0] + "/postgres", autocommit=True) as c:
            c.execute("drop database if exists wq_vplc_test with (force)")
            c.execute("create database wq_vplc_test")
    except psycopg.OperationalError:
        pytest.skip("没有可用的 PostgreSQL")
    from hub.db import DB
    d = DB(DSN)
    d.init()
    return d


SPEC = {
    "编号": "TS-15-1", "book": "plc", "no": "15.1", "学时": 4,
    "标题": ["轴承压装工位的顺序控制程序", "Press station program"], "角色": ["电气工程师", "electrical engineer"],
    "背景": ["压装", "Press"], "工位": ["PY", "PLM"],
    "交付物": [{"名称": ["PLC 程序（PLCopen XML）", "PLC program"], "验收": ["测试全过", "All tests pass"], "类型": "PLC 程序",
                "设备": "press-01", "格式": ["xml", "st"], "班次小时": 0.2}],
    "步骤": [["写", "Write"]], "评审要点": [["查", "Check"]],
    "评分": [{"项": ["程序", "Program"], "分": 100, "标准": ["对", "Right"]}],
}


@need_node
def test_task_upload_review_approve_runs_a_shift(db, monkeypatch):
    monkeypatch.setenv("WQ_HUB_NO_START", "1")
    monkeypatch.setenv("WQ_AUTH", "wenquest")
    monkeypatch.setenv("WQ_SSO_URL", "https://learn.example.com/api/v1/auth/sso")
    monkeypatch.setenv("WQ_SECRET", "test-secret")
    monkeypatch.setenv("WQ_FACTORY_TASK_KEY", "task-key-123")
    import httpx
    from test_auth import ACCOUNTS, _Resp, _Teach, _client

    def fake_get(url, cookies=None, timeout=None):
        u = ACCOUNTS.get((cookies or {}).get("wq_sso", ""))
        return _Resp(200, {"token": "x", "user": u}) if u else _Resp(401, {"code": "not_logged_in"})
    monkeypatch.setattr(httpx, "get", fake_get)
    import hub.app as A
    A = importlib.reload(A)
    from hub.historian import Historian
    from hub.vplc import VPLC
    from vplc.runner import VirtualPLC
    A.H.teach = _Teach()
    A.H.db = db
    sent = []
    A.H.vplc = VPLC(db, A.H.publish)
    A.H.vplc.init()
    A.H.hist = Historian(db, A.H.on_message)

    class _Bus:
        def publish_msg(self, tp, msg):
            sent.append((tp, msg))
    A.H.bus = _Bus()
    try:
        gw = _client(A)
        tid = gw.post("/api/tasks/course/issue", json={"spec": SPEC, "course_id": 9, "cmid": 3}, headers={"Authorization": "Bearer task-key-123"}).json()["id"]
        stu, tea = _client(A, "stu-cookie"), _client(A, "tea-cookie")
        hs = {"x-wq-token": stu.post("/api/login", json={"role": "engineer", "mode": "teach"}).json()["token"]}
        ht = {"x-wq-token": tea.post("/api/login", json={"role": "engineer", "mode": "teach"}).json()["token"]}
        # 状态变量设成保持型的程序（第 15 章程序 15.7.1）：上传能编译，AI 预检指出 RETAIN
        bad = _read(os.path.join(BOOK, "p15_7_1.st")) if os.path.isdir(BOOK) else \
            _read(os.path.join(EX, "press_p15_5_1.st")).replace("  VAR\n", "  VAR RETAIN\n", 1)
        r = stu.post(f"/api/tasks/{tid}/deliverables/0/file", files={"file": ("press.st", bad.encode(), "text/plain")}, headers=hs)
        assert r.status_code == 200, r.text
        assert r.json()["deliverables"]["0"]["check"]["ok"]
        pre = stu.post(f"/api/tasks/{tid}/precheck", headers=hs).json()
        assert any("RETAIN" in f["text"] and f["level"] == "error" for f in pre["findings"])
        # 正确的程序，用实验台导出的 PLCopen XML 交
        from vplc.runner import tool
        st = _read(os.path.join(EX, "press_p15_5_1.st"))
        xml = __import__("subprocess").run(["node", "-e", "const P=require(process.argv[1]);const W=require(process.argv[2]);"
                                            "process.stdout.write(P.exportXml(require('fs').readFileSync(0,'utf8'),{io:W.press().io}))",
                                            os.path.join(DIGITAL, "vplc", "js", "plc.js"), os.path.join(DIGITAL, "vplc", "js", "plants.js")],
                                           input=st.encode(), capture_output=True).stdout.decode()
        assert tool({"op": "import", "xml": xml, "unit": "press"})["ok"]
        stu.post(f"/api/tasks/{tid}/deliverables/0/file", files={"file": ("press.xml", xml.encode(), "application/xml")}, headers=hs)
        sub = stu.post(f"/api/tasks/{tid}/submit", headers=hs).json()
        assert sub["status"] == "submitted" and not [c for c in sub["comments"] if c["level"] == "error"], sub["comments"]
        sid = sub["id"]
        r = tea.post(f"/api/task-submissions/{sid}/decision", json={"decision": "approve"}, headers=ht).json()
        assert r["status"] == "approved" and "虚拟 PLC" in r["decision"], r["decision"]
        dl = [(tp, m) for tp, m in sent if m["type"] == "plc.download"]
        assert len(dl) == 1 and dl[0][0] == "wq/gearbox/machining/press-01/cmd" and dl[0][1]["data"]["hours"] == 0.2
        rid = dl[0][1]["data"]["run_id"]
        # 仿真车间里的虚拟 PLC 收到程序：算一个（0.2 小时的）班次，立即回放；枢纽收消息、记班次
        vp = VirtualPLC(lambda tp, ty, src, d, corr: A.H.hist.handle(tp, wqbus.make(ty, src, d, corr=corr)))
        dl[0][1]["data"]["speed"] = 0
        vp.handle("press-01", dl[0][1], block=True)
        run = db.one("select * from plc_run where id=%s", (rid,))
        assert run["status"] == "done" and run["origin"] == "task" and run["task_sub"] == sid
        assert run["summary"]["parts"] > 30 and run["live"]["n"] == run["summary"]["parts"]
        # 学生在任务单上看到班次；“虚拟 PLC”页
        mine = stu.get(f"/api/task-submissions/{sid}", headers=hs).json()
        assert mine["plc_runs"][0]["id"] == rid and mine["plc_runs"][0]["status"] == "done"
        ov = tea.get("/api/plc", headers=ht).json()
        assert {u["unit"] for u in ov["units"]} == {"press-01", "sort-01"} and ov["runs"][0]["id"] == rid and ov["teacher"]
        assert stu.get("/api/plc", headers=hs).json()["teacher"] is False
        # 老师试跑：参考程序；学生不能下发
        assert stu.post("/api/plc/runs", data={"unit": "sort-01", "example": "1"}, headers=hs).status_code == 403
        r = tea.post("/api/plc/runs", data={"unit": "sort-01", "example": "1", "hours": "0.1"}, headers=ht)
        assert r.status_code == 200, r.text
        r = tea.post("/api/plc/runs", data={"unit": "sort-01", "program": "PROGRAM Main M_Belt := ; END_PROGRAM"}, headers=ht)
        assert r.status_code == 422 and "编译" in r.json()["detail"]
        assert tea.get("/api/plc/runs/" + rid, headers=ht).json()["program"].startswith("TYPE")
    finally:
        for k in ("WQ_AUTH", "WQ_SSO_URL", "WQ_FACTORY_TASK_KEY"):
            os.environ.pop(k, None)
        importlib.reload(A)


def test_openplc_program_rewrite():
    """给 OpenPLC 的程序：去注释、I/O 声明（地址挪到从站映射区）、拆开一行多个实例的声明（MatIEC 会崩）、加 CONFIGURATION"""
    from vplc.openplc_st import mapping, to_openplc
    io = [{"name": "B_Part", "addr": "%IX0.0", "dir": "in"}, {"name": "S_EStop", "addr": "%IX1.0", "dir": "in"},
          {"name": "AI_Force", "addr": "%IW64", "dir": "in", "type": "INT"}, {"name": "Y_Clamp", "addr": "%QX0.0", "dir": "out"}]
    assert [(m[1], m[3], m[4]) for m in mapping(io)] == [("%IX100.0", 0, "di"), ("%IX101.0", 8, "di"), ("%IW100", 0, "ir"), ("%QX100.0", 0, "coil")]
    src = to_openplc("(* 中文注释 *)\nPROGRAM Main\n  VAR\n    a, b, c : R_TRIG;  (* 三个 *)\n  END_VAR\n"
                     "  CASE x OF\n    A, B: y := 1;\n  END_CASE;\n  Y_Clamp := B_Part;\nEND_PROGRAM\n", io)
    assert "中文" not in src and "B_Part AT %IX100.0 : BOOL;" in src and "AI_Force AT %IW100 : INT;" in src
    assert "a : R_TRIG;" in src and "c : R_TRIG;" in src and "A, B: y := 1;" in src
    assert "PROGRAM Inst0 WITH MainTask : Main;" in src


def test_compat_result_is_published_and_recorded():
    from vplc.runner import VirtualPLC
    out = []
    v = VirtualPLC(lambda tp, ty, src, d, corr: out.append((tp, wqbus.make(ty, src, d, corr=corr))),
                   compute_fn=lambda unit, st, h, seed: _fake_shift(),
                   check_fn=lambda unit, st: {"ok": True, "stage": "run", "summary": {"parts": 5, "good": 5}})
    v.handle("press-01", wqbus.make("plc.download", "hub", {"run_id": "PLC-C", "program": "x", "speed": 0}), block=True)
    import time
    for _ in range(50):
        if any(m["data"].get("phase") == "compat" for _, m in out if m["type"] == "plc.shift"):
            break
        time.sleep(0.05)
    c = [m["data"]["compat"] for _, m in out if m["type"] == "plc.shift" and m["data"]["phase"] == "compat"]
    assert c and c[0]["ok"] and c[0]["summary"]["parts"] == 5
