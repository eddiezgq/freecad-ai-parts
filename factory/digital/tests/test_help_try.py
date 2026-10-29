# -*- coding: utf-8 -*-
"""第 30 轮 §八 8-1：帮助里的“当场动手”（hub/help_try.py，/api/help/try）。

- 只在教学模式（生产模式 403）、只在演示工厂（企业工厂整组接口 404：TEACH_ONLY_API）；
- 学生只能按自己岗位能做的，老师都能做；没登记的动作 404；
- 每人 60 秒一次（老师 5 秒，防连点）；失败的不算一次；
- 各动作走的是现成的路：磨床停机 = 教师控制台的 inject_fault；急单 = 两周情景第 1 幕的下单算料提议；保养逾期、发票逾期 = 情景第 6、8 幕；
  重大隐患、带锯床忘关 = 情景第 5、7 幕（8-3 加）。"""
import json
import os

import pytest

from tests.test_story import FakeMes

HERE = os.path.dirname(os.path.abspath(__file__))
DIGITAL = os.path.dirname(HERE)
DSN = os.environ.get("WQ_TEST_DB", "postgresql://postgres@localhost:5433/wq_test")

STU = {"name": "小李", "uid": "s1", "teacher": False, "mode": "teach"}
TEA = {"name": "王老师", "uid": "t1", "teacher": True, "mode": "teach", "role": "manager"}


def _client(H, now=None):
    from fastapi import FastAPI, Header
    from fastapi.testclient import TestClient
    from hub import help_try as HT

    def user_of(x_u: str = Header(default="")):
        return json.loads(x_u)

    HT._last.clear()
    app = FastAPI()
    HT.mount(app, H, user_of, lambda u: u["name"])
    c = TestClient(app)

    def call(u, name, method="post"):
        h = {"x-u": json.dumps(u)}
        return c.post("/api/help/try/" + name, headers=h) if method == "post" else c.get("/api/help/try", headers=h)
    return call


class FakeH:
    def __init__(self):
        self.mes = FakeMes()


def test_roles_mode_and_unknown():
    H = FakeH()
    call = _client(H)
    # 计划员不能让磨床停机；维修工、操作工可以
    r = call(dict(STU, role="planner"), "stop-grinder")
    assert r.status_code == 403 and "维修工" in r.json()["detail"] and not H.mes.sent
    assert call(dict(STU, role="maintenance"), "stop-grinder").status_code == 200
    assert H.mes.sent[-1] == {"unit": "grd-01", "command": "inject_fault", "mode": "teach", "work_order": None, "minutes": 120,
                              "reason": "砂轮主轴故障（帮助里当场动手）"}
    assert call(dict(STU, uid="s2", role="operator"), "stop-grinder").status_code == 200
    # 急单只给计划员（与厂情中枢发起动作同一张岗位表）
    assert call(dict(STU, uid="s3", role="maintenance"), "rush-order").status_code == 403
    # 生产模式：谁都不行，老师也不行
    n = len(H.mes.sent)
    assert call(dict(TEA, mode="prod"), "stop-grinder").status_code == 403
    assert call(dict(STU, uid="s4", role="maintenance", mode="prod"), "stop-grinder").status_code == 403
    assert len(H.mes.sent) == n
    # 没登记的动作
    assert call(TEA, "drop-table").status_code == 404


def test_rate_limit_per_user():
    H = FakeH()
    call = _client(H)
    me = dict(STU, role="maintenance")
    assert call(me, "stop-grinder").status_code == 200
    r = call(me, "stop-grinder")
    assert r.status_code == 429 and "秒后再试" in r.json()["detail"]
    assert call(me, "overdue-pm").status_code == 429                       # 每人一次，不分动作
    assert call(dict(me, uid="s9"), "stop-grinder").status_code == 200    # 别人不受影响
    lst = call(me, "", method="get").json()
    assert lst["enabled"] and not lst["actions"]["stop-grinder"]["ok"] and 0 < lst["actions"]["stop-grinder"]["wait_s"] <= 60
    # 60 秒以后又可以
    from hub import help_try as HT
    HT._last[HT._uid(me)] -= 61
    assert call(me, "stop-grinder").status_code == 200
    # 老师 5 秒一次：防连点两下，上课演示可以接着按
    assert call(TEA, "stop-grinder").status_code == 200
    assert call(TEA, "stop-grinder").status_code == 429
    HT._last[HT._uid(TEA)] -= 6
    r = call(TEA, "stop-grinder")
    assert r.status_code == 200 and r.json()["wait_s"] == 5


def test_failed_action_does_not_count(monkeypatch):
    from hub import help_try as HT
    call = _client(FakeH())

    def boom(H, u, who):
        raise ValueError("现在没有未收的应收发票")
    monkeypatch.setitem(HT.ACTIONS["overdue-invoice"], "fn", boom)
    me = dict(STU, role="planner")
    r = call(me, "overdue-invoice")
    assert r.status_code == 409 and "应收发票" in r.json()["detail"]
    assert HT.wait_s(me) == 0


def test_listing_tells_why():
    call = _client(FakeH())
    lst = call(dict(STU, role="quality"), "", method="get").json()
    assert lst["enabled"] and not lst["teacher"]
    assert set(lst["actions"]) == {"stop-grinder", "rush-order", "overdue-pm", "overdue-invoice", "major-hazard", "idle-saw"}
    assert lst["actions"]["major-hazard"]["ok"]                                  # 隐患谁都能报
    assert all(not a["ok"] and "你现在是质检员" in a["why"] for n, a in lst["actions"].items() if n != "major-hazard")
    lst = call(dict(TEA, mode="prod"), "", method="get").json()
    assert not lst["enabled"] and all(not a["ok"] for a in lst["actions"].values())
    lst = call(TEA, "", method="get").json()
    assert lst["teacher"] and all(a["ok"] for a in lst["actions"].values())


def test_only_on_demo_plant():
    """企业工厂：/api/help/try 整组 404（与 E1–E7、情景导演同一张表）；网页上不显示（TryBlock 看 plant.demo 与模式）"""
    with open(os.path.join(DIGITAL, "hub", "app.py"), encoding="utf-8") as f:
        app = f.read()
    head = app[app.index("TEACH_ONLY_API = "):app.index("TEACH_ONLY_NAV = ")]
    ns = {}
    exec(head, ns)                                                          # 只是一个元组表达式
    teach_only = lambda p: any(p == x or p.startswith(x + "/") for x in ns["TEACH_ONLY_API"])   # noqa: E731 —— 与 app.teach_only 同一写法
    assert "return any(path == p or path.startswith(p + \"/\") for p in TEACH_ONLY_API)" in app      # 第 51 轮：后面多一句“有产品的厂放行采购与来料”
    assert teach_only("/api/help/try") and teach_only("/api/help/try/stop-grinder")
    assert not teach_only("/api/help/docs") and not teach_only("/api/help/media")    # 帮助正文、视频企业工厂照样能看
    assert "_help_try.mount(app, H, user_of, who)" in app
    with open(os.path.join(DIGITAL, "web", "src", "components", "help", "TryBlock.vue"), encoding="utf-8") as f:
        vue = f.read()
    assert "const show = computed(() => demo.value && (!loggedIn.value || session.user?.mode === 'teach'));" in vue


# ---------------------------------------------------------------- 动作真做了（临时数据库，与两周情景同一套）
@pytest.fixture(scope="module")
def env():
    pytest.importorskip("psycopg")
    from hub.ont import evals as EV
    from tests.test_agent import NoLLM
    try:
        H, eng = EV.sandbox(DSN, name="wq_help_try_test", llm=NoLLM())
    except Exception as e:  # noqa: BLE001
        pytest.skip("没有可用的 PostgreSQL：{}".format(e))
    H.mes = FakeMes()
    return H, eng


def test_actions_do_the_real_thing(env):
    from hub import finance as FN
    from hub import maint as MT
    H, _ = env
    call = _client(H)
    # 急单：计划员的“下单并算料”提议，已确认，等桥接写进 ERPNext
    r = call(dict(STU, role="planner"), "rush-order")
    assert r.status_code == 200, r.text
    p = H.db.one("select * from ai_proposal where proposal_id=%s", (r.json()["proposal_id"],))
    assert p["action"] == "create_order_and_plan" and p["status"] == "confirmed" and p["preview"]["sales_order"]["qty"] == 5
    assert r.json()["look"] == "/work/planner"
    # 保养逾期：运行小时拨到保养周期的 1.4 倍，发给仿真车间
    r = call(dict(STU, uid="s2", role="maintenance"), "overdue-pm")
    assert r.status_code == 200, r.text
    assert MT._state(H.db, "teach")["overdue"]["grd-01"] == 700.0
    assert {"unit": "grd-01", "command": "set_run_h", "mode": "teach", "work_order": None, "hours": 700.0} in H.mes.sent
    # 发票逾期：有未收的应收发票就设一张逾期 15 天、不催不付；没有就 409
    FN.init(H.db)
    H.db.x("delete from invoice where mode='teach'")
    assert call(dict(TEA), "overdue-invoice").status_code == 409                # 没有未收的应收
    FN.opening(H.db, "teach")                                                   # 期初应收（三个客户各一笔）
    x = H.db.one("select id from invoice where mode='teach' and kind='ar' and status not in ('paid','held','failed') order by id desc limit 1")
    r = call(dict(TEA), "overdue-invoice")
    assert r.status_code == 200, r.text
    assert r.json()["invoice_id"] == x["id"] and "逾期 15 天" in r.json()["text"]
    assert H.db.one("select no_pay from invoice where id=%s", (x["id"],))["no_pay"] is True


def test_hazard_and_idle_do_the_real_thing(env):
    """8-3 加的两个：重大隐患（谁都能报）、带锯床下班忘关（操作工等能按，质检员不能）"""
    from hub import ehs as EH
    from hub import energy as EN
    H, _ = env
    call = _client(H)
    EH.init(H.db)
    n0 = EH.kpis(H.db, "teach")["major_open"]
    r = call(dict(STU, uid="h1", role="quality"), "major-hazard")
    assert r.status_code == 200, r.text
    assert EH.kpis(H.db, "teach")["major_open"] == n0 + 1 and r.json()["look"] == "/ehs"
    assert call(dict(STU, uid="h2", role="quality"), "idle-saw").status_code == 403
    r = call(dict(STU, uid="h3", role="operator"), "idle-saw")
    assert r.status_code == 200, r.text
    f = (EN._state(H.db, "teach").get("faults") or {})["forgot:saw-01"]
    assert f["hours"] == 4 and EN.sim_on(H.db, "teach")
    assert any(c.get("command") == "set_energy" and c.get("inject") == [{"kind": "forgot", "unit": "saw-01", "hours": 4.0}] for c in H.mes.sent)
