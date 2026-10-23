# -*- coding: utf-8 -*-
"""数字工厂枢纽服务（hub）：历史库写入 + 看板指标 + AI 工厂助手 + MES + 教学评分 + 工作台网页。

运行：uvicorn hub.app:app --port 8100
环境变量：WQ_DB、WQ_MQTT_HOST/PORT/USER/PASSWORD、WQ_MQTT_WS（浏览器连总线的地址）、WQ_ERPNEXT_URL、
WQ_NODERED_URL、WQ_TZ、WQ_SECRET、WQ_CLAUDE_KEY / WQ_DEEPSEEK_KEY（可选）、WQ_AI_PROVIDER / WQ_AI_REGION（第 30 轮，见 hub/llm.py）、
WQ_PLANT_FILE（工厂清单，第 30 轮；不设 = 演示工厂）；WQ_EDITION=local、WQ_TEACHER_PASSWORD（学校本地版，第 30 轮 H-5）；
线上另有 WQ_AUTH=wenquest、WQ_SSO_URL、WQ_LOGIN_URL、WQ_AI_PER_HOUR、WQ_HISTORY_DAYS（见第 3 轮细则）。
"""
import base64
import datetime as dt
import hashlib
import hmac
import json
import logging
import os
import secrets
import sys
import threading
import time
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.dirname(HERE), os.path.dirname(os.path.dirname(HERE))]

from fastapi import Body, Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse, Response  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

import wqbus  # noqa: E402
from wqbus import layout as L  # noqa: E402
from wqbus.client import Bus  # noqa: E402
from wqbus.topics import topic, unit_topic  # noqa: E402
from factory import data as F  # noqa: E402
from factory import plant as PLANT  # noqa: E402
from hub import kpi, mrp  # noqa: E402
from hub import select as lib_select  # noqa: E402
from hub import design as design_web  # noqa: E402
from hub import erp_sso  # noqa: E402
from hub import plm  # noqa: E402
from hub import process  # noqa: E402
from hub import cards as proc_cards  # noqa: E402
from hub import qproblem  # noqa: E402
from hub import spc  # noqa: E402
from hub import configurator  # noqa: E402
from hub.ai import Assistant, ROLE_NAMES  # noqa: E402
from hub.db import DB  # noqa: E402
from hub.historian import Historian  # noqa: E402
from hub.privacy import actor  # noqa: E402
from hub.mes import MES  # noqa: E402
from hub.teach import Teach  # noqa: E402

log = logging.getLogger("hub")
logging.basicConfig(level=os.environ.get("WQ_LOG", "INFO"), format="%(asctime)s hub %(levelname)s %(message)s")

SECRET = (os.environ.get("WQ_SECRET") or secrets.token_hex(16)).encode()
ROLES = ("planner", "engineer", "operator", "quality", "manager", "approver", "sales", "service", "safety", "maintenance", "lead")   # approver、sales：企业版（第 8 轮）
STUDENT_ROLES = ("planner", "engineer", "operator", "quality", "service", "safety", "maintenance", "lead")   # lead 班组长：第 18 轮 E4（实验 19）     # safety 安全员：第 18 轮 E2（实验 17）     # service 售后：第 18 轮 E1（实验 16）
# 登录方式（第 3 轮 D2）：local = 填名字进入（自己电脑上用）；wenquest = 问渠账号（线上）
AUTH = os.environ.get("WQ_AUTH", "local")
# 版本（第 30 轮 H-5）：local = 学校机房的本地版（factory/local/start.sh 设）；server = 线上服务器或开发机
EDITION = os.environ.get("WQ_EDITION", "server")
# 本地版填名字登录时：学生只能选学生岗位；当老师（厂长、生产模式、教师控制台）要输老师密码（.env 的 WQ_TEACHER_PASSWORD）。
# 不是本地版时照旧：填名字的人都按老师（开发机、CI 演练）
LOCAL_ROLES = AUTH == "local" and EDITION == "local"
TEACHER_PASSWORD = os.environ.get("WQ_TEACHER_PASSWORD", "")
SSO_URL = os.environ.get("WQ_SSO_URL", "")          # 学习平台核对登录的接口，如 https://learn.<域名>/api/v1/auth/sso
LOGIN_URL = os.environ.get("WQ_LOGIN_URL", "")      # 学习平台登录页，如 https://learn.<域名>/pages/login/login
SSO_COOKIE = "wq_sso"                               # 全站登录凭证（学习平台设置，整个域名共用）
TOKEN_DAYS = float(os.environ.get("WQ_TOKEN_DAYS", "7"))
# AI 工厂助手每人每小时提问上限（D7）；0 = 不限。线上默认 30，自己电脑上默认不限
AI_PER_HOUR = int(os.environ.get("WQ_AI_PER_HOUR", "30" if AUTH == "wenquest" else "0"))
DEFAULT_MODE = os.environ.get("WQ_MODE", "teach")
FACTORY_NAME = os.environ.get("WQ_FACTORY_NAME", "")                       # 班级工厂的显示名（第 10 轮）
CLASS_TEACHERS = {x for x in os.environ.get("WQ_CLASS_TEACHERS", "").split(",") if x}
CLASS_IDS = set(os.environ.get("WQ_CLASS_IDS", "").split())                # 公共工厂：有哪些班级工厂（给 Caddy 按需发证书）
WEB_DIST = os.environ.get("WQ_WEB_DIST", os.path.join(os.path.dirname(HERE), "web", "dist"))
# 工厂清单（第 30 轮 H-2；freecad-ai-parts ADR-0064）：E1–E7 领域、实验 15–23、情景导演、教学模拟器只在演示工厂开。
# 企业工厂（WQ_PLANT_FILE 指定、demo_data: false）里这些接口一律 404，网页按 /api/config 的 plant.hidden 不显示入口
DEMO_PLANT = PLANT.is_demo()
TEACH_ONLY_API = tuple("/api/lab{}".format(n) for n in range(15, 24)) + (
    "/api/labs", "/api/story", "/api/scenario", "/api/teach/batch-complaint", "/api/help/try",       # 帮助里的“当场动手”（第 30 轮 §八）
    "/api/complaints", "/api/crm", "/api/followups", "/api/ont/customer360", "/api/service",     # E1 客户与服务
    "/api/ehs", "/api/maint", "/api/people", "/api/supply", "/api/energy", "/api/finance")      # E2–E7
TEACH_ONLY_NAV = ("/service", "/supply", "/finance", "/maint", "/people", "/ehs", "/energy", "/director", "/labs", "/teach",
                  "/plc") + tuple("/lab{}".format(n) for n in range(15, 24))
PUBLISH_ALLOW = ("wq/gearbox/design/",)       # HTTP → 总线网关只放行这些主题（FreeCAD 宏用）


class Hub:
    def __init__(self):
        self.db = DB()
        self.bus = None
        self.ai = None
        self.hist = None
        self.mes = None
        self.teach = None
        self.twin = None
        self.vplc = None
        self.ont = None
        self.plan_snaps = None
        self.agent = None
        self.stop = threading.Event()
        self.last_brief = {}
        self._ncr_sent = set()

    def publish(self, tp, type_, source, data, corr=None, mode=None):
        msg = wqbus.make(type_, source, data, mode=mode or DEFAULT_MODE, corr=corr)
        self.bus.publish_msg(tp, msg)
        # 立即入库，页面马上能读到（总线回来的同一条会按 id 去重）
        self.hist.handle(tp, msg)
        return msg

    def start(self):
        self.db.init()
        self.bus = Bus("wq-hub-" + secrets.token_hex(3))
        self.ai = Assistant(self.db, self.publish)
        ai_setting_load(self.db, self.ai.llm)          # 第 30 轮 H-6：管理员选的模型（Claude / DeepSeek / 自动）
        from hub.ont.agent import Agent               # AI 代理（第 17 轮 D 期）：问答走代理，工具是本体、异常、推演、动作
        self.agent = Agent(self, self.ai.llm, locked=self.compare_locked)
        self.hist = Historian(self.db, self.on_message)
        self.hist.load()
        self.mes = MES(self.db, self.publish)
        self.teach = Teach(self.db)
        from hub.twin import TwinService
        self.twin = TwinService(self.db, self.publish)
        self.twin.init()
        from hub.vplc import VPLC                     # 虚拟 PLC（第 18 轮第 8 步）
        self.vplc = VPLC(self.db, self.publish)
        self.vplc.init()
        self.bus.subscribe("wq/#", self.hist.handle_raw, raw=True)
        try:
            self.bus.start(timeout=float(os.environ.get("WQ_MQTT_TIMEOUT", "20")))
        except ConnectionError:
            log.exception("总线未就绪，后台继续重连")
        threading.Thread(target=self._loop, daemon=True, name="ai-loop").start()
        threading.Thread(target=self.twin.run, daemon=True, name="field-sim").start()
        self._start_ont()

    def _start_ont(self):
        """厂情中枢的工厂本体（第 17 轮 A 期）：总线历史 → 对象和链接，后台增量同步"""
        from hub.cae_api import FACTORY_ID, call
        from hub.ont.sync import Sync
        try:
            self.ont = Sync(self.db, factory_id=FACTORY_ID, cae_call=call, modes=("teach", "prod"))
            self.ont.init()
        except Exception:  # noqa: BLE001  —— 本体出问题不影响工厂其他功能
            log.exception("工厂本体初始化失败")
            return
        threading.Thread(target=self.ont.run, daemon=True, name="ontology").start()
        try:
            self.ai.detector().init()                  # 厂情中枢的异常表（第 17 轮 B 期）
        except Exception:  # noqa: BLE001
            log.exception("异常表初始化失败")
        self._start_plan()

    def _start_plan(self):
        """推演与动作（第 17 轮 C 期）：建表；把班次日历发给仿真车间；每 15 分钟拍一张快照"""
        from hub.ont import actions as AC
        from hub.ont import plan as P
        try:
            P.init(self.db)
            AC.init(self.db)
            from hub.ont import agent as AG
            from hub.ont import evals as EV
            AG.init(self.db)
            EV.init(self.db)
            from hub.ont import notify as NT
            from hub.ont import report as RP
            from hub.ont import retro as RT
            from hub import service as SV
            SV.init(self.db)
            from hub import ehs as EH
            EH.init(self.db)
            from hub import maint as MT
            MT.init(self.db)
            from hub import people as PE
            PE.init(self.db)
            from hub import supply as SP
            SP.init(self.db)
            from hub import energy as EG
            EG.init(self.db)
            from hub import finance as FN
            FN.init(self.db)
            from hub import story as ST
            ST.init(self.db)
            from hub import lab23 as L23
            L23.init(self.db)
            NT.init(self.db)
            RP.init(self.db)
            RT.init(self.db)
        except Exception:  # noqa: BLE001
            log.exception("推演表初始化失败")
            return
        self.plan_snaps = P.Snapshots(self.db, self.mes)
        threading.Thread(target=self._plan_loop, daemon=True, name="plan").start()

    def _plan_loop(self):
        from hub.ont import plan as P
        last_cal, last_snap = 0.0, time.time() - 600            # 启动 5 分钟后拍第一张
        while not self.stop.wait(15):
            now = time.time()
            for mode in self.active_modes():
                try:
                    if now - last_cal > 300:
                        P.push_calendar(self.mes, self.db, mode)
                    if now - last_snap > 900:
                        self.plan_snaps.take(mode, timeout=5)
                except Exception:  # noqa: BLE001
                    log.exception("班次 / 快照出错")
            if now - last_cal > 300:
                last_cal = now
            if now - last_snap > 900:
                last_snap = now
                try:
                    self.db.x("delete from sim_snapshot where ts < now() - interval '30 days'")
                except Exception:  # noqa: BLE001
                    pass

    def compare_locked(self, u, anomaly_id=None):
        """实验 15 的比对模式：学生提交自己的分析之前看不到建议和推荐理由（第 17 轮 D 期 D9）"""
        try:
            from hub import lab15, lab16, lab17, lab18, lab19, lab20, lab21, lab22, lab23   # 实验 16–23 沿用同一个比对模式
            return any(m.locked(self.db, u, anomaly_id) for m in (lab15, lab16, lab17, lab18, lab19, lab20, lab21, lab22, lab23))
        except ImportError:
            return False

    def on_message(self, tp, msg):
        t = msg["type"]
        if t in ("test.torque", "twin.telemetry"):
            try:
                self.twin.on_message(tp, msg)
            except Exception:  # noqa: BLE001
                log.exception("数字孪生处理消息出错")
        if self.vplc is not None and t in ("plc.shift", "plc.cycle", "machine.status", "machine.event"):
            try:
                self.vplc.on_message(tp, msg)
            except Exception:  # noqa: BLE001
                log.exception("虚拟 PLC 处理消息出错")
        if t == "energy.reading":                 # 第 18 轮 E6：计量读数入库
            try:
                from hub import energy as EG
                EG.ingest(self.db, msg["mode"], msg["data"])
            except Exception:  # noqa: BLE001
                log.exception("能源读数入库出错")
        if t == "sim.snapshot" and self.plan_snaps is not None:
            try:
                self.plan_snaps.deliver(msg)
            except Exception:  # noqa: BLE001
                log.exception("保存快照出错")
        if t == "erp.doc":
            self.ai.on_erp_result(msg)
        elif t == "design.release":
            self.ai.on_design_release(dict(msg, _topic=tp))
        elif t == "quality.measurement" and msg["data"]["result"] == "fail":
            r = self.db.one("select * from ncr where part_serial=%s", (msg["data"]["part_serial"],))
            if r and r["ncr_id"] not in self._ncr_sent:
                self._ncr_sent.add(r["ncr_id"])
                self.publish(topic("quality", "qc-01", "ncr"), "quality.ncr", "hub",
                             {"ncr_id": r["ncr_id"], "part_serial": r["part_serial"], "status": "open",
                              "item": r["item"], "work_order": r["work_order"], "detail": r["detail"]},
                             r["work_order"], msg["mode"])

    def _first_run(self):
        """第一次启动（教学模式、历史库还是空的）：让仿真器载入实验 7 情景，首页一打开就有内容。"""
        if DEFAULT_MODE != "teach" or os.environ.get("WQ_AUTO_SCENARIO", "1") != "1" or not DEMO_PLANT:
            return                              # 实验 7 情景是演示工厂的；企业工厂不载入
        for _ in range(6):
            if self.db.one("select 1 as x from bus_message where mode='teach' and type='erp.doc' limit 1"):
                return
            if self.bus and self.bus._connected.is_set():
                log.info("历史库为空，请仿真器载入实验 7 情景")
                self.mes.command("sim", "load_scenario", "teach", "system", speed=1)
            if self.stop.wait(15):
                return

    def _loop(self):
        """每 20 秒按规则检查一次提醒；每 10 分钟或状况明显变化时重写今日简报。"""
        try:
            self._first_run()
        except Exception:  # noqa: BLE001
            log.exception("载入情景失败")
        while not self.stop.wait(float(os.environ.get("WQ_AI_EVERY_S", "20"))):
            self._prune()
            for mode in self.active_modes():
                try:
                    new = self.ai.evaluate(mode)
                    try:                              # 主动提醒（第 17 轮 D 期）：新的 / 升级 / 重开的异常，没人确认的“严重”异常
                        from hub.ont import notify as NT
                        NT.on_alerts(self.db, mode, new)
                        NT.escalate(self.db, mode)
                        from hub.ont import report as RP       # 厂情日报 07:30、经营周报周一 08:00（生产模式）
                        for kind in RP.due(self.db, mode):
                            RP.generate(self.db, mode, kind, llm=self.ai.llm)
                        from hub.ont import retro as RT        # 自动复盘：异常解决、动作执行完、受影响的工单做完
                        RT.due(self.db, mode)
                        if DEMO_PLANT:                         # E1–E7 只在演示工厂（第 30 轮 H-2）
                            from hub import service as SV          # 客户与服务的教学模拟器（第 18 轮 E1）：投诉、上门、回访、线索
                            SV.tick(self, mode)
                            from hub import ehs as EH              # 安全环保的教学模拟器（第 18 轮 E2）：一般隐患、未遂、化学品与废物
                            EH.tick(self, mode)
                    except Exception:  # noqa: BLE001
                        log.exception("通知 / 报告出错")
                    if DEMO_PLANT:                    # E1–E7 与情景导演只在演示工厂（第 30 轮 H-2）
                        try:                              # 设备维护单独一段：前面的模拟器出错不影响台账和故障单
                            from hub import maint as MT            # 设备维护（第 18 轮 E3）：台账进 ERPNext、故障 → 维修单、模拟器
                            MT.ensure_setup(self, mode)
                            if mode == "teach":
                                MT.tick(self, mode)
                            else:
                                MT.scan_failures(self, mode)
                        except Exception:  # noqa: BLE001
                            log.exception("设备维护出错")
                        try:                              # 人员与组织（第 18 轮 E4）：员工档案进 ERPNext、出勤模拟、人员等级下发车间
                            from hub import people as PE
                            PE.ensure_setup(self, mode)
                            PE.tick(self, mode)
                        except Exception:  # noqa: BLE001
                            log.exception("人员出错")
                        try:                              # 供应链（第 18 轮 E5）：备选供应商进 ERPNext、发货到货、批次用料、模拟器
                            from hub import supply as SP
                            SP.ensure_setup(self, mode)
                            SP.tick(self, mode)
                        except Exception:  # noqa: BLE001
                            log.exception("供应链出错")
                        try:                              # 能源与环境（第 18 轮 E6）：计量开关与节能设定下发车间、模拟器出问题、修好了清掉
                            from hub import energy as EG
                            EG.tick(self, mode)
                        except Exception:  # noqa: BLE001
                            log.exception("能源出错")
                        try:                              # 经营与财务（第 18 轮 E7）：订单做完开票、收货开采购发票、客户付款模拟器
                            from hub import finance as FN
                            FN.tick(self, mode)
                        except Exception:  # noqa: BLE001
                            log.exception("财务出错")
                        try:                              # 第 19 轮：情景导演——推进等 ERPNext 的步骤、核对异常、自动演示
                            if mode == "teach":
                                from hub import story as ST
                                ST.tick(self, mode)
                        except Exception:  # noqa: BLE001
                            log.exception("情景出错")
                    last = self.last_brief.get(mode, 0)
                    if new or time.time() - last > 600:
                        self.ai.briefing(mode)
                        self.last_brief[mode] = time.time()
                except Exception:  # noqa: BLE001
                    log.exception("AI 巡检出错（%s）", mode)

    _pruned_day = None

    def _prune(self):
        """D9：历史库只保留最近 WQ_HISTORY_DAYS 天（0 = 全部保留），每天清理一次。"""
        days = float(os.environ.get("WQ_HISTORY_DAYS", "0"))
        today = dt.date.today()
        if days <= 0 or self._pruned_day == today:
            return
        self._pruned_day = today
        try:
            for table in ("bus_message", "machine_state_log"):
                self.db.x("delete from {} where ts < now() - make_interval(days => %s)".format(table), (int(days),))
            log.info("历史库已清理 %s 天以前的记录", int(days))
        except Exception:  # noqa: BLE001
            log.exception("清理历史库失败")

    def active_modes(self):
        rows = self.db.q("select distinct mode from bus_message where ts > now() - interval '1 day' and mode is not null")
        return [r["mode"] for r in rows] or [DEFAULT_MODE]


H = Hub()
app = FastAPI(title="问渠数字工厂枢纽 WenQuest Digital Factory Hub", version="1.0.0")


def teach_only(path):
    """只属于演示工厂的接口（E1–E7、实验 15–23、情景）"""
    return any(path == p or path.startswith(p + "/") for p in TEACH_ONLY_API)


@app.middleware("http")
async def _demo_plant_only(request: Request, call_next):
    if not DEMO_PLANT and teach_only(request.url.path):
        return JSONResponse({"detail": "这项功能只属于演示工厂（问渠减速器厂），本厂没有"}, 404)
    return await call_next(request)


@app.on_event("startup")
def _startup():
    if os.environ.get("WQ_HUB_NO_START") != "1":
        H.start()


@app.on_event("shutdown")
def _shutdown():
    H.stop.set()
    if H.bus:
        H.bus.stop()


# ---------------------------------------------------------------- 登录（统一入口）
def _sign(payload):
    raw = base64.urlsafe_b64encode(json.dumps(payload, ensure_ascii=False).encode()).decode()
    sig = hmac.new(SECRET, raw.encode(), hashlib.sha256).hexdigest()[:32]
    return raw + "." + sig


def user_of(x_wq_token: str = Header(default="")):
    try:
        raw, sig = x_wq_token.split(".")
        if hmac.compare_digest(sig, hmac.new(SECRET, raw.encode(), hashlib.sha256).hexdigest()[:32]):
            u = json.loads(base64.urlsafe_b64decode(raw.encode()))
            if u.get("exp", float("inf")) > time.time():
                u.setdefault("teacher", not LOCAL_ROLES)      # 填名字登录的旧凭证：人人可用全部角色（学校本地版除外）
                return u
    except Exception:  # noqa: BLE001
        pass
    raise HTTPException(401, "请先登录")


def check_allowed(teacher, role, mode, member=None):
    """D3：学生只能用教学模式和四个岗位角色；厂长角色、生产模式、教师控制台只给老师。
    第 8 轮：企业成员（老师在“企业成员”页授权）在生产模式可用授权给他的角色。"""
    if role not in ROLES or mode not in ("teach", "prod"):
        raise HTTPException(400, "角色或模式不对")
    if teacher:
        return
    if mode == "teach" and role in STUDENT_ROLES:
        return
    if mode == "prod" and member and role in member:
        return
    if LOCAL_ROLES:
        raise HTTPException(403, "学生只能选学生岗位、用教学模式；老师请勾“我是老师”并输老师密码")
    raise HTTPException(403, "这个角色或生产模式没有授权给你（请老师或企业管理员在“企业成员”里授权）")


def _member_roles(uid):
    try:
        r = H.db.one("select roles from enterprise_member where uid=%s", (str(uid),))
        return list(r["roles"]) if r else None
    except Exception:  # noqa: BLE001 —— 测试里没有数据库
        return None


def _seen(uid, name, teacher):
    try:
        H.db.x("insert into known_user (uid, name, teacher) values (%s,%s,%s) on conflict (uid) do update "
               "set name=excluded.name, teacher=excluded.teacher, last_seen=now()", (str(uid), name, teacher))
    except Exception:  # noqa: BLE001
        pass


def who(u):
    """总线上代表这个人的写法：线上版“角色·匿名编号”，本地版姓名（第 4 轮 C5）。"""
    return actor(u["name"], u.get("role"))


def require_teacher(u):
    if not u.get("teacher"):
        raise HTTPException(403, "只有老师可以做这个操作")


def wenquest_user(cookie):
    """拿浏览器带来的全站登录凭证向学习平台核对身份。返回 {id, fullname, username, teacher} 或 None。"""
    if not cookie or not SSO_URL:
        return None
    import httpx
    try:
        r = httpx.get(SSO_URL, cookies={SSO_COOKIE: cookie}, timeout=10)
    except httpx.HTTPError:
        log.exception("学习平台登录核对失败")
        raise HTTPException(503, "暂时连不上学习平台，请稍后再试")
    if r.status_code != 200:
        return None
    x = r.json().get("user") or {}
    if not x.get("id"):
        return None
    return {"id": x["id"], "fullname": (x.get("fullname") or x.get("username") or "").strip(),
            "username": x.get("username", ""), "teacher": bool(x.get("can_create_courses"))}


def _display_name(w):
    # 实验评分、提议记录按这个名字区分人；加上账号编号，重名的同学也不会混在一起
    return "{}（{}）".format(w["fullname"] or w["username"], w["id"])[:60]


@app.get("/api/login/info")
def login_info(request: Request):
    """登录页用：登录方式、学习平台登录页地址，以及（线上）此人是否已在学习平台登录。"""
    out = {"auth": AUTH, "login_url": LOGIN_URL, "student_roles": STUDENT_ROLES,
           "edition": EDITION, "teacher_password": LOCAL_ROLES}      # 本地版：当老师要输老师密码（第 30 轮 H-5）
    if AUTH == "wenquest":
        w = wenquest_user(request.cookies.get(SSO_COOKIE, ""))
        out["account"] = {"fullname": w["fullname"], "teacher": w["teacher"]} if w else None
    return out


_pw_fails = {}


def _local_teacher(request, pw):
    """本地版的老师密码：不填 = 学生；填错报错（同一台电脑 10 分钟内错 5 次就先锁 10 分钟）。"""
    if not pw:
        return False
    ip, now = (request.client.host if request.client else "?"), time.time()
    with _ai_lock:
        fails = [t for t in _pw_fails.get(ip, []) if now - t < 600]
        _pw_fails[ip] = fails
        if len(fails) >= 5:
            raise HTTPException(429, "老师密码错得太多，请 10 分钟后再试")
    if TEACHER_PASSWORD and hmac.compare_digest(pw.encode(), TEACHER_PASSWORD.encode()):
        return True
    with _ai_lock:
        _pw_fails.setdefault(ip, []).append(now)
    raise HTTPException(403, "老师密码不对（在启动工厂那台电脑的 factory/digital/.env 里，WQ_TEACHER_PASSWORD）"
                        if TEACHER_PASSWORD else "这台工厂没有设老师密码（factory/digital/.env 的 WQ_TEACHER_PASSWORD）")


@app.post("/api/login")
def login(request: Request, body: dict = Body(...)):
    mode = body.get("mode", DEFAULT_MODE)
    if AUTH == "wenquest":
        w = wenquest_user(request.cookies.get(SSO_COOKIE, ""))
        if not w:
            raise HTTPException(401, "请先用问渠账号登录")
        teacher = w["teacher"] or str(w["id"]) in CLASS_TEACHERS          # 班级工厂的任课老师（第 10 轮）
        member = None if teacher else _member_roles(w["id"])
        role = body.get("role") or ("manager" if teacher else (member[0] if member and mode == "prod" else "planner"))
        if not teacher and not member:
            mode = "teach"
        if member and mode == "prod" and role not in member:            # 登录页按学生角色选的：换成授权的第一个
            role = member[0]
        check_allowed(teacher, role, mode, member)
        u = {"name": _display_name(w), "uid": w["id"], "teacher": teacher, "role": role, "mode": mode,
             "exp": int(time.time() + TOKEN_DAYS * 86400)}
        if member:
            u["member"] = member
        _seen(w["id"], _display_name(w), teacher)
    else:
        name = str(body.get("name", "")).strip()[:40]
        if not name:
            raise HTTPException(400, "请填写姓名")
        teacher = True
        if LOCAL_ROLES:                       # 学校本地版（第 30 轮 H-5）：输对老师密码才是老师，否则是学生
            teacher = _local_teacher(request, str(body.get("teacher_password") or ""))
            if not teacher:
                mode = "teach"
        role = body.get("role") or ("manager" if teacher else "planner")
        check_allowed(teacher, role, mode)
        u = {"name": name, "role": role, "mode": mode, "teacher": teacher}
    if u["mode"] == "teach":
        H.teach.start(u["name"])
    return {"token": _sign(u), "user": u}


@app.post("/api/me/switch")
def switch(body: dict = Body(...), u=Depends(user_of)):
    role = body.get("role", u["role"])
    mode = body.get("mode", u["mode"])
    member = None if u["teacher"] or AUTH != "wenquest" else _member_roles(u.get("uid"))   # 授权随时生效
    check_allowed(u["teacher"], role, mode, member)
    nu = dict(u, role=role, mode=mode)
    if member:
        nu["member"] = member
    else:
        nu.pop("member", None)
    return {"token": _sign(nu), "user": nu}


_ai_calls = {}
_ai_lock = threading.Lock()


def ai_quota(u):
    """D7：AI 工厂助手每人每小时最多 AI_PER_HOUR 次。"""
    if AI_PER_HOUR <= 0:
        return
    now, key = time.time(), u.get("uid") or u["name"]
    with _ai_lock:
        recent = [t for t in _ai_calls.get(key, []) if now - t < 3600]
        if len(recent) >= AI_PER_HOUR:
            wait = int((3600 - (now - recent[0])) // 60) + 1
            raise HTTPException(429, "本小时已问了 {} 次，请 {} 分钟后再问".format(AI_PER_HOUR, wait))
        recent.append(now)
        _ai_calls[key] = recent


@app.get("/api/caddy/ask")
def caddy_ask(domain: str = ""):
    """学习平台的 Caddy 按需申请证书前来问：<编号>.factory.<域名>、<编号>.erp.<域名> 是不是已建的班级工厂（第 10 轮）"""
    parts = domain.lower().split(".")
    if len(parts) >= 4 and parts[1] in ("factory", "erp") and parts[0] in CLASS_IDS:
        return {"ok": True}
    raise HTTPException(404, "不是班级工厂")


@app.get("/api/config")
def config(request: Request):
    lan = _lan_host(request)
    return {
        "mqtt_ws": lan(os.environ.get("WQ_MQTT_WS", "ws://localhost:9001")),
        "erpnext_url": ((os.environ.get("WQ_PUBLIC_URL", "").rstrip("/") + "/api/erp/sso") if AUTH == "wenquest" and erp_sso.enabled()
                        else lan(os.environ.get("WQ_ERPNEXT_URL", "http://localhost:8090"))),   # 线上：经单点登录入口（第 7 轮）
        "nodered_url": lan(os.environ.get("WQ_NODERED_URL", "http://localhost:1880")),   # 线上设为空：不对外（D8）
        "auth": AUTH, "login_url": LOGIN_URL, "edition": os.environ.get("WQ_EDITION", EDITION),   # 每次现读（测试、企业版改环境变量后不用重载）
        "default_mode": DEFAULT_MODE, "roles": ROLE_NAMES, "factory_name": FACTORY_NAME, "ai_engine": H.ai.llm.name if H.ai else "rules",
        "tz": str(kpi.TZ), "customers": F.CUSTOMERS, "fg": [{"item_code": "WQR-105", "name": F.ITEMS["WQR-105"][0],
                                                               "price": F.FG_SELLING_PRICE}],
        "plant": _plant_cfg(),
    }


def _lan_host(request):
    """本地版（第 30 轮 H-5）：机房里学生用 http://老师电脑IP:8100 打开，总线、ERPNext 的地址里的 localhost 换成同一个 IP。"""
    host = request.url.hostname or "localhost"
    if EDITION != "local" or host in ("localhost", "127.0.0.1"):
        return lambda url: url
    return lambda url: url.replace("//localhost:", "//" + host + ":").replace("//127.0.0.1:", "//" + host + ":")


def _plant_cfg():
    """页面上随工厂变的：厂名、是否演示工厂、班次；hidden 是企业工厂里不显示的页面入口（第 30 轮 H-2）"""
    from sim import calendar as cal
    c = PLANT.company()
    return {"name": PLANT.display_name(), "company": c["name"], "currency": c["currency"], "demo": DEMO_PLANT,
            "shift": "{}–{}".format(cal.DEF_START, cal.DEF_END), "hidden": [] if DEMO_PLANT else list(TEACH_ONLY_NAV)}


# ---------------------------------------------------------------- AI 模型选择（第 30 轮 H-6；freecad-ai-parts ADR-0063）
AI_SETTING_SQL = "create table if not exists app_setting (key text primary key, value jsonb, updated_by text, ts timestamptz default now())"


def ai_setting_load(db, llm):
    try:
        db.x(AI_SETTING_SQL)
        r = db.one("select value from app_setting where key='ai_provider'")
        llm.override = r["value"] if r and r["value"] in ("claude", "deepseek", "auto") else None
    except Exception as e:  # noqa: BLE001 —— 设置读不到时按环境变量
        log.warning("读不到 AI 模型设置：%s", e)


def _can_admin_ai(u):
    if u.get("teacher") or u["role"] == "manager":
        return
    raise HTTPException(403, "AI 模型设置要用厂长或管理员账号")


@app.get("/api/admin/ai")
def ai_status(u=Depends(user_of)):
    _can_admin_ai(u)
    return H.ai.llm.status()


@app.post("/api/admin/ai")
def ai_set(body: dict = Body(...), u=Depends(user_of)):
    """选模型：claude / deepseek / auto（按地区：国内 DeepSeek、其他 Claude）。存库，重启后照样生效。
    部署在国内（WQ_AI_REGION=cn）时只用 DeepSeek，选 claude 也不会调用 Claude（合规：国内只用已备案模型）。"""
    _can_admin_ai(u)
    v = body.get("provider")
    if v not in ("claude", "deepseek", "auto"):
        raise HTTPException(400, "provider 只能是 claude、deepseek 或 auto")
    from psycopg.types.json import Jsonb
    H.db.x(AI_SETTING_SQL)
    H.db.x("insert into app_setting (key, value, updated_by) values ('ai_provider', %s, %s) on conflict (key) do update "
           "set value=excluded.value, updated_by=excluded.updated_by, ts=now()", (Jsonb(v), who(u)))
    H.ai.llm.override = v
    return H.ai.llm.status()


@app.get("/api/routing/{item}")
def routing(item: str):
    from sim.engine import OP_UNITS, routing_for
    if item not in F.BOMS:
        raise HTTPException(404, "没有这个自制件")
    ops = routing_for(item)
    return {"item": item, "name": F.ITEMS[item][0], "routing": F.BOMS[item][0],
            "bom": [{"item_code": c, "qty": q, "name": F.ITEMS[c][0]} for c, q in F.BOMS[item][1]],
            "operations": [{"operation": op, "minutes": m, "units": OP_UNITS[op],
                            "rate_per_hour": kpi.rate_per_hour(OP_UNITS[op][0])} for op, m in ops],
            "std_cost": dict(zip(("material", "operations"), mrp.std_unit_cost(item)))}


@app.get("/api/health")
def health():
    ok_db = bool(H.db.one("select 1 as x"))
    return {"ok": ok_db, "bus": bool(H.bus and H.bus._connected.is_set()),
            "messages": H.db.one("select count(*) as n from bus_message")["n"],
            "ai": (H.ai.llm.name.split(":")[0] if H.ai else "rules")}       # 第 17 轮 D 期：AI 代理用的引擎种类（claude / deepseek / rules），不含密钥


def _pm_h(u):
    """标准保养周期（运行小时）：3D 车间、首页点设备时和状态里的 run_h_pm 比，显示“保养逾期”（第 30 轮 §八 8-1）"""
    from sim import reliability as REL
    rp = REL.params(u)
    return {"pm_h": rp["pm_h"]} if rp else {}


@app.get("/api/layout")
def get_layout():
    return {"floor": L.FLOOR, "units": {u: {"x": v[0], "y": v[1], "w": v[2], "d": v[3],
                                           "name": wqbus.UNITS[u][1], "en": wqbus.UNITS[u][2],
                                           **({"h": L.HEIGHT[u]} if L.HEIGHT and u in L.HEIGHT else {}),
                                           **_pm_h(u)}
                                       for u, v in L.LAYOUT.items()},
            "agv_home": L.AGV_HOME, "aisles": L.AISLES, "cross_x": L.CROSS_X}


# ---------------------------------------------------------------- 看板
@app.get("/api/overview")
def get_overview(u=Depends(user_of)):
    ov = kpi.overview(H.db, None, u["mode"])
    b = H.db.one("select payload from bus_message where type='ai.briefing' and mode=%s order by ts desc limit 1",
                 (u["mode"],))
    ov["briefing"] = b["payload"] if b else None
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=24)
    alerts = H.db.messages(["ai.alert"], since=since, mode=u["mode"], order="desc", limit=40)
    seen, al = set(), []
    for a in alerts:
        k = a["data"].get("key") or a["data"]["title"]
        if k not in seen:
            seen.add(k)
            al.append({"id": a["id"], "ts": a["ts"], **a["data"]})
    ov["alerts"] = al
    ov["proposals"] = [_prop(p) for p in H.db.q(
        "select * from ai_proposal where mode=%s and (status='pending' or decided_at > now() - interval '1 day') "
        "order by created_at desc limit 20", (u["mode"],))]
    ov["todos"] = todos_for(u, ov)
    if u["mode"] == "teach":
        ov["teach"] = H.teach.check(u["name"])
    return ov


def _prop(p):
    return {k: (v.isoformat() if isinstance(v, dt.datetime) else v) for k, v in p.items()}


def todos_for(u, ov):
    """提醒与待办：按角色取不同的东西。"""
    role = u["role"]
    out = []
    if u["mode"] == "teach":
        t = ov.get("teach") or H.teach.status(u["name"])
        for task in t["tasks"]:
            if task["done"]:
                out.append({"kind": "已完成", "tone": "good", "text": task["title"], "src": "任务 · 得 {} 分".format(task["score"]),
                            "act": "查看", "link": "/teach"})
            elif len([x for x in out if x["kind"] == "任务"]) < 2:
                out.append({"kind": "任务", "tone": "task", "text": task["desc"], "src": "实验 7 · " + task["title"],
                            "act": "去做", "link": "/work/" + task["role"]})
        return out[:6]
    for p in ov["proposals"]:
        if p["status"] == "pending" and role in ("planner", "manager"):
            out.append({"kind": "AI 提议", "tone": "info", "text": p["title"], "src": "ai/proposal " + p["proposal_id"],
                        "act": "预览并确认", "proposal_id": p["proposal_id"]})
    for n in ov["quality"]["ncr"]:
        if role in ("quality", "manager"):
            out.append({"kind": "质量", "tone": "bad", "text": "不合格品 {}：{} {} 超差".format(
                n["ncr_id"], n["part_serial"], n["detail"].get("name")), "src": "quality/qc-01 · " + n["ncr_id"],
                "act": "评审", "link": "/work/quality"})
    for a in ov["alerts"][:8]:
        k = a.get("key", "")
        if role == "operator" and not k.startswith(("down:", "tool:")):
            continue
        if role == "quality" and not k.startswith(("trend:", "ncr:")):
            continue
        if role == "planner" and not k.startswith(("late:", "stock:", "down:")):
            continue
        if role == "engineer" and not k.startswith(("release:", "tool:", "trend:")):
            continue
        if k.startswith("ncr:"):
            continue
        out.append({"kind": {"critical": "紧急", "warn": "提醒", "info": "提示"}[a["level"]],
                    "tone": {"critical": "bad", "warn": "warn", "info": "info"}[a["level"]],
                    "text": a["title"] + "：" + (a.get("detail") or ""), "src": (a.get("evidence") or [{}])[0].get("topic", "ai/alert").replace("wq/gearbox/", ""),
                    "act": "查看", "hint": a.get("action_hint")})
    return out[:8]


@app.get("/api/history")
def history(type: str = None, topic_like: str = None, corr: str = None, hours: float = 24, limit: int = 100,
            u=Depends(user_of)):
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=min(hours, 24 * 60))
    rows = H.db.messages([type] if type else None, since=since, mode=u["mode"], topic_like=topic_like, corr=corr,
                         limit=min(limit, 500), order="desc")
    return [{"id": r["id"], "ts": r["ts"], "topic": r["_topic"], "type": r["type"], "source": r["source"],
             "corr": r.get("corr"), "data": r["data"]} for r in rows]


@app.get("/api/message/{mid}")
def message(mid: str, u=Depends(user_of)):
    r = H.db.one("select topic, payload from bus_message where id::text=%s", (mid,))
    if not r:
        raise HTTPException(404, "没有这条消息")
    return dict(r["payload"], topic=r["topic"])


@app.get("/api/machine/{unit}")
def machine_detail(unit: str, u=Depends(user_of)):
    if unit not in wqbus.UNITS:
        raise HTTPException(404, "没有这台设备")
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=24)
    evs = H.db.messages(["machine.event"], since=since, mode=u["mode"], topic_like=unit_topic(unit, "event"),
                        limit=60, order="desc")
    st = H.db.latest_per_topic(["machine.status"], mode=u["mode"], topic_like=unit_topic(unit, "status"))
    ov = kpi.Overview(H.db, None, u["mode"])
    return {"unit": unit, "name": wqbus.UNITS[unit][1], "status": next(iter(st.values()), None),
            "events": evs, "oee": ov.oee()["machines"].get(unit), "rate_per_hour": kpi.rate_per_hour(unit)}


@app.get("/api/work_orders")
def work_orders(u=Depends(user_of)):
    ov = kpi.Overview(H.db, None, u["mode"])
    out = []
    for w in sorted(ov.wos, key=lambda w: w["data"]["name"], reverse=True):
        d = w["data"]
        released = bool(H.db.one("select 1 as x from bus_message where type='machine.cmd' and corr=%s and "
                                 "payload->'data'->>'command'='dispatch' limit 1", (d["name"],)))
        out.append(dict(d, produced=ov.produced(d), released=released, started=d["name"] in ov.started_wos,
                        demo=bool(d.get("demo"))))
    return out


@app.get("/api/work_orders/{name}/cost")
def wo_cost(name: str, u=Depends(user_of)):
    c = mrp.wo_cost(H.db, name, u["mode"])
    if not c:
        raise HTTPException(404, "该工单还没有加工记录")
    mat, ops = mrp.std_unit_cost(c["item"])
    c["std_unit"] = {"material": mat, "operations": ops}
    return c


@app.get("/api/sales_orders")
def sales_orders(u=Depends(user_of)):
    return [s["data"] for s in H.db.erp_docs("Sales Order", u["mode"])]


# ---------------------------------------------------------------- 计划：算料与提议
@app.post("/api/plan/order")
def plan(body: dict = Body(...), u=Depends(user_of)):
    try:
        return mrp.plan_order(H.db, body.get("customer"), body.get("item", "WQR-105"), int(body["qty"]),
                              body["delivery_date"], u["mode"])
    except (KeyError, ValueError) as e:
        raise HTTPException(400, "订单信息不完整：{}".format(e))


@app.post("/api/proposals")
def create_proposal(body: dict = Body(...), u=Depends(user_of)):
    """计划员表单提交：与 AI 起草的提议走同一流程（预览 → 确认 → 桥接写入 ERPNext）。"""
    action = body.get("action", "create_order_and_plan")
    if action == "create_order_and_plan":
        pv = mrp.plan_order(H.db, body.get("customer"), body.get("item", "WQR-105"), int(body["qty"]),
                            body["delivery_date"], u["mode"])
        from hub.ai import _order_title
        title = _order_title(pv)
    elif action == "purchase_request":
        pv = {"material_requests": body["material_requests"]}
        title = "请购：" + "、".join("{} {}".format(x["item_code"], x["qty"]) for x in body["material_requests"])
    elif action == "release_work_order":
        pv = {"work_order": body["work_order"]}
        title = "下达工单 " + body["work_order"]
    else:
        raise HTTPException(400, "不支持的提议 " + action)
    pid = H.ai.propose(action, pv, u["mode"], u["name"], title, source="workbench/" + who(u), role=u["role"])
    return {"proposal_id": pid, "preview": pv, "title": title}


@app.get("/api/proposals")
def list_proposals(u=Depends(user_of)):
    return [_prop(p) for p in H.db.q("select * from ai_proposal where mode=%s order by created_at desc limit 50",
                                     (u["mode"],))]


@app.get("/api/proposals/{pid}")
def get_proposal(pid: str, u=Depends(user_of)):
    p = H.db.one("select * from ai_proposal where proposal_id=%s", (pid,))
    if not p:
        raise HTTPException(404, "没有这个提议")
    out = _prop(p)
    out["results"] = [m["data"] for m in H.db.messages(["erp.doc"], corr=pid)]
    return out


@app.post("/api/proposals/{pid}/{decision}")
def decide(pid: str, decision: str, u=Depends(user_of)):
    if decision not in ("confirm", "reject"):
        raise HTTPException(404)
    executors = {"release_work_order": lambda p: {"dispatched": H.mes.release(p["preview"]["work_order"], p["mode"], who(u))}}
    try:
        st = H.ai.decide(pid, u["name"], decision == "confirm", executors, role=u["role"])
    except KeyError:
        raise HTTPException(404, "没有这个提议")
    except ValueError as e:
        raise HTTPException(409, str(e))
    return {"status": st}


# ---------------------------------------------------------------- AI 助手
@app.post("/api/ai/chat")
def ai_chat(body: dict = Body(...), u=Depends(user_of)):
    msgs = [m for m in body.get("messages", []) if m.get("role") in ("user", "assistant") and m.get("content")]
    if not msgs:
        raise HTTPException(400, "请输入问题")
    ai_quota(u)
    if H.agent is None:
        return H.ai.chat(msgs, u["mode"], u["role"], u["name"])
    return H.agent.ask(u, msgs[-12:])


_catalog = lib_select.Catalog()


@app.post("/api/library/select")
def library_select(body: dict = Body(...), u=Depends(user_of)):
    """AI 选型（零件库第 5 轮 P10③）：只从零件库里挑，答案里的编号逐个核对"""
    q = (body.get("question") or "").strip()
    if not q:
        raise HTTPException(400, "请用一句话说需求，例如：35 mm 轴、1450 r/min、径向载荷为主用什么轴承")
    if len(q) > 500:
        raise HTTPException(400, "需求请写短一些（500 字以内）")
    ai_quota(u)
    llm = H.ai.llm if getattr(H, "ai", None) else None
    try:
        return lib_select.answer(_catalog, llm, q)
    except Exception as ex:  # noqa: BLE001 —— 模型出错时退回规则回答
        log.warning("AI 选型出错，改用规则：%s", ex)
        return lib_select.answer(_catalog, None, q)


@app.post("/api/ai/briefing/refresh")
def refresh_briefing(u=Depends(user_of)):
    ai_quota(u)
    H.ai.evaluate(u["mode"])
    return H.ai.briefing(u["mode"])


# ---------------------------------------------------------------- 车间执行
@app.post("/api/mes/release")
def release(body: dict = Body(...), u=Depends(user_of)):
    try:
        return {"dispatched": H.mes.release(body["work_order"], u["mode"], who(u), body.get("units"))}
    except KeyError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(409, str(e))


@app.post("/api/mes/cmd")
def mes_cmd(body: dict = Body(...), u=Depends(user_of)):
    unit, cmd = body.get("unit"), body.get("command")
    allowed = {"start", "pause", "reset"} | ({"inject_fault", "set_speed", "load_scenario"} if u["mode"] == "teach" else set())
    if cmd not in allowed:
        raise HTTPException(403, "不允许的指令 {}".format(cmd))
    if cmd in ("inject_fault", "set_speed", "load_scenario"):
        require_teacher(u)                 # 教师控制台（D3）
    if cmd == "load_scenario" and not DEMO_PLANT:
        raise HTTPException(400, "实验 7 情景只属于演示工厂，本厂没有")
    extra = {k: v for k, v in body.items() if k in ("minutes", "reason", "kind", "speed")}
    try:
        H.mes.command(unit, cmd, u["mode"], who(u), body.get("work_order"), body.get("operation"), **extra)
    except KeyError as e:
        raise HTTPException(404, str(e))
    return {"sent": True}


# ---------------------------------------------------------------- 问题情景与 8D（第 13 轮）
def _sim_sender(u):
    def send(cmd, **extra):
        H.mes.command("sim", cmd, u["mode"], who(u), **extra)
    return send


def _q(fn, *a, **k):
    try:
        return fn(*a, **k)
    except KeyError as e:
        raise HTTPException(404, "没有：{}".format(e))
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except ValueError as e:
        raise HTTPException(409, str(e))


@app.get("/api/quality/problems/catalog")
def q_catalog(u=Depends(user_of)):
    c = qproblem.catalog()
    if not (u.get("teacher") and u["mode"] == "teach"):
        c.pop("problems")                  # 学生看不到问题清单，只能从数据里找
    return c


@app.get("/api/quality/problems")
def q_active(u=Depends(user_of)):
    require_teacher(u)
    return qproblem.active(H.db, u["mode"])


@app.post("/api/quality/problems")
def q_inject(body: dict = Body(...), u=Depends(user_of)):
    require_teacher(u)
    if body.get("clear"):
        return _q(qproblem.clear, H.db, _sim_sender(u), u["mode"], who(u))
    return _q(qproblem.inject, H.db, _sim_sender(u), u["mode"], who(u), body.get("problem"), body.get("magnitude"))


@app.get("/api/quality/8d")
def q8d_list(u=Depends(user_of)):
    return qproblem.list_(H.db, u["mode"])


@app.post("/api/quality/8d")
def q8d_create(body: dict = Body(...), u=Depends(user_of)):
    if not (body.get("title") or "").strip():
        raise HTTPException(400, "写一个简短的标题（现象）")
    return qproblem.create(H.db, u["mode"], who(u), _uid(u), body.get("item") or "SH-301", body.get("characteristic"),
                           body["title"].strip(), body.get("d"))


@app.get("/api/quality/8d/{sid}")
def q8d_get(sid: str, u=Depends(user_of)):
    s = qproblem.get(H.db, sid)
    if not s or s["mode"] != u["mode"]:
        raise HTTPException(404, "没有这张 8D")
    return s


@app.post("/api/quality/8d/{sid}")
def q8d_update(sid: str, body: dict = Body(...), u=Depends(user_of)):
    q8d_get(sid, u)
    act = body.get("action", "save")
    if act == "save":
        return _q(qproblem.update, H.db, sid, body.get("d") or {}, body.get("fix"))
    if act == "submit":
        return _q(qproblem.submit_fix, H.db, sid)
    if act in ("approve", "reject"):
        require_teacher(u)
        return _q(qproblem.decide_fix, H.db, _sim_sender(u), sid, who(u), act == "approve", body.get("note") or "")
    if act == "verify":
        return _q(qproblem.verify, H.db, sid)
    if act == "close":
        return _q(qproblem.close, H.db, sid, who(u))
    raise HTTPException(400, "不支持的操作")


@app.post("/api/ncr/{ncr_id}")
def ncr_decide(ncr_id: str, body: dict = Body(...), u=Depends(user_of)):
    disp = body.get("disposition")
    if disp not in ("rework", "scrap", "use_as_is"):
        raise HTTPException(400, "处置只能是返修、报废或让步接收")
    r = H.db.one("select * from ncr where ncr_id=%s", (ncr_id,))
    if not r:
        raise HTTPException(404, "没有这张不合格品单")
    H.db.x("update ncr set status=%s, decided_by=%s, decided_at=now() where ncr_id=%s", (disp, u["name"], ncr_id))
    H.publish(topic("quality", "qc-01", "ncr"), "quality.ncr", "workbench/" + who(u),
              {"ncr_id": ncr_id, "part_serial": r["part_serial"], "status": disp, "decided_by": who(u),
               "note": body.get("note", ""), "item": r["item"], "work_order": r["work_order"]}, r["work_order"], u["mode"])
    return {"status": disp}


@app.get("/api/ncr")
def ncr_list(u=Depends(user_of)):
    return [_prop(r) for r in H.db.q("select * from ncr where mode=%s or mode is null order by created_at desc limit 100",
                                     (u["mode"],))]


@app.get("/api/quality/measurements")
def measurements(characteristic: str = "bearing_seat_d35", limit: int = 50, u=Depends(user_of)):
    rows = H.db.messages(["quality.measurement"], mode=u["mode"], order="desc", limit=500)
    rows = [r for r in rows if r["data"]["characteristic"] == characteristic][:limit]
    return list(reversed([{"id": r["id"], "ts": r["ts"], **r["data"]} for r in rows]))


# ---------------------------------------------------------------- 设计与文件
@app.post("/api/files")
async def upload(file: UploadFile = File(...), u=Depends(user_of)):
    data = await file.read()
    if len(data) > 50 * 1024 * 1024:
        raise HTTPException(413, "文件超过 50 MB")
    sha = hashlib.sha256(data).hexdigest()
    H.db.x("insert into stored_file (sha256, name, mime, size, content) values (%s,%s,%s,%s,%s) "
           "on conflict (sha256) do nothing", (sha, file.filename, file.content_type, len(data), data))
    return {"sha256": sha, "name": file.filename, "size": len(data), "url": "/api/files/" + sha}


@app.get("/api/files/{sha}")
def download(sha: str):
    r = H.db.one("select name, mime, content from stored_file where sha256=%s", (sha,))
    if not r:
        raise HTTPException(404, "没有这个文件")
    return Response(bytes(r["content"]), media_type=r["mime"] or "application/octet-stream",
                    headers={"Content-Disposition": "inline; filename*=UTF-8''" + _quote(r["name"])})


def _quote(s):
    import urllib.parse
    return urllib.parse.quote(s)


@app.post("/api/bus/publish")
def http_publish(body: dict = Body(...), u=Depends(user_of)):
    """给没有 MQTT 客户端的工具（FreeCAD 宏）用：校验后原样发到总线。只放行设计类主题。"""
    tp, msg = body.get("topic", ""), body.get("message")
    if not tp.startswith(PUBLISH_ALLOW):
        raise HTTPException(403, "这个接口只能发布设计类主题")
    if isinstance(msg, dict) and isinstance(msg.get("data"), dict) and "author" in msg["data"]:
        msg = dict(msg, data=dict(msg["data"], author=who(u)))       # 作者也不以姓名上总线（C5）
    try:
        msg = wqbus.validate(dict(msg, mode=u["mode"]))
    except (wqbus.ValidationError, TypeError) as e:
        raise HTTPException(422, "消息不合规范：{}".format(e))
    if u["mode"] == "prod" and msg["type"] in ("design.release", "design.gcode"):     # 企业版：桌面宏的发布也先进待审（第 8 轮）
        return _desktop_submit(msg, u)
    H.bus.publish_msg(tp, msg)
    H.hist.handle(tp, msg)
    return {"id": msg["id"]}


@app.get("/api/design/{item}")
def design(item: str, u=Depends(user_of)):
    rel = H.db.messages(["design.release"], mode=u["mode"], order="desc", limit=20)
    gc = H.db.messages(["design.gcode"], mode=u["mode"], order="desc", limit=20)
    return {"releases": [dict(r["data"], id=r["id"], ts=r["ts"]) for r in rel if r["data"]["item"] == item],
            "gcode": [dict(r["data"], id=r["id"], ts=r["ts"]) for r in gc if r["data"]["item"] == item]}


# 网页设计台（第 6 轮 W2、W3）：不装 FreeCAD 也能改参数、校核、发布
def _design_item(item):
    if item != design_web.ITEM:
        raise HTTPException(404, "网页设计台目前只支持 {}".format(design_web.ITEM))


@app.get("/api/design/{item}/params")
def design_params(item: str, u=Depends(user_of)):
    """现行参数：本模式最新发布版的参数；没发布过用工厂数据里的第 1 版"""
    _design_item(item)
    rel = [r for r in H.db.messages(["design.release"], mode=u["mode"], order="desc", limit=50) if r["data"]["item"] == item]
    params = rel[0]["data"].get("params") if rel else None
    params = design_web.normalize(params) if params else design_web.normalize(design_web.defaults())
    return {"item": item, "revision": rel[0]["data"]["revision"] if rel else 1, "params": params,
            "check": design_web.check(params), "limits": design_web.LIMITS}


@app.post("/api/design/{item}/check")
def design_check(item: str, body: dict = Body(...), u=Depends(user_of)):
    _design_item(item)
    try:
        return design_web.check(design_web.normalize(body.get("params") or {}))
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.post("/api/design/{item}/publish")
def design_publish(item: str, body: dict = Body(...), u=Depends(user_of)):
    _design_item(item)

    def emit(tp, type_, data):
        msg = wqbus.make(type_, "web-cad", data, mode=u["mode"])
        H.bus.publish_msg(tp, msg)
        H.hist.handle(tp, msg)
    try:
        params = design_web.normalize(body.get("params") or {})
        note = (body.get("change_note") or "").strip()[:200]
        if u["mode"] == "teach":
            return design_web.publish(H.db, emit, params, who(u), u["mode"], note)
        return dict(design_web.submit_prod(H.db, emit, params, who(u), _uid(u), note), pending=True)   # 企业版：先审批（第 8 轮）
    except ValueError as e:
        raise HTTPException(422, str(e))


# ---------------------------------------------------------------- 企业版：通用发布、看图、审批（第 8 轮）
def _uid(u):
    return str(u.get("uid") or erp_sso.local_uid(u["name"]))


def _emit_as(u, source="plm"):
    def emit(tp, type_, data):
        msg = wqbus.make(type_, source, data, mode=u["mode"])
        H.bus.publish_msg(tp, msg)
        H.hist.handle(tp, msg)
    return emit


def _can_submit(u):
    if u["mode"] == "teach" or u["role"] in ("engineer", "manager"):
        return
    raise HTTPException(403, "提交设计要用工艺员（设计工程师）或厂长角色")


def _can_approve(u):
    if u["role"] in ("approver", "manager"):
        return
    raise HTTPException(403, "审批要用审批人或厂长角色")


def _plm_call(fn, *a, **k):
    try:
        return fn(*a, **k)
    except KeyError as e:
        raise HTTPException(404, str(e).strip("'"))
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except ValueError as e:
        raise HTTPException(422, str(e))


def _desktop_submit(msg, u):
    d = msg["data"]
    if msg["type"] == "design.gcode":
        sid = _plm_call(plm.attach_gcode, H.db, u["mode"], d["item"], _uid(u), d)
        return {"submission": sid, "pending": True}
    _can_submit(u)
    files = d.get("files") or []
    step = next((f for f in files if f.get("kind") == "step"), None)
    drw = next((f for f in files if f.get("kind") == "drawing"), None)
    r = _plm_call(plm.submit, H.db, _emit_as(u, "freecad"), u["mode"], who(u), _uid(u), d["item"],
                  step=plm.load_file(H.db, step["url"]) if step else None, step_name=step and step["name"],
                  drawing=plm.load_file(H.db, drw["url"]) if drw else None, drawing_name=drw and drw["name"],
                  note=d.get("change_note") or "", params=d.get("params"))
    return {"submission": r["id"], "pending": True, "id": r["id"]}


@app.get("/api/plm/item/{item}")
def plm_item(item: str, u=Depends(user_of)):
    info = plm.item_info(item, plm.erp_item_name if AUTH == "wenquest" else None)
    if not info:
        raise HTTPException(404, "物料 {} 不存在（先在 ERPNext 里建物料）".format(item))
    return dict(info, revision=plm.current_revision(H.db, u["mode"], item))


@app.post("/api/plm/submit")
async def plm_submit(item: str = Form(...), note: str = Form(""), operation: str = Form(""),
                     step: UploadFile = File(None), drawing: UploadFile = File(None), gcode: UploadFile = File(None),
                     u=Depends(user_of)):
    """网页上传发布（任何 CAD 导出的 STEP 都行）：教学模式直接生效，生产模式进待审"""
    _can_submit(u)
    item = item.strip()
    if not plm.item_info(item, plm.erp_item_name if AUTH == "wenquest" else None):
        raise HTTPException(404, "物料 {} 不存在（先在 ERPNext 里建物料）".format(item))
    blobs = {}
    for k, f in (("step", step), ("drawing", drawing), ("gcode", gcode)):
        if f is not None and f.filename:
            b = await f.read()
            if len(b) > 50 * 1024 * 1024:
                raise HTTPException(413, "文件超过 50 MB")
            blobs[k] = (b, f.filename)
    if "step" not in blobs and "drawing" not in blobs:
        raise HTTPException(422, "至少要上传 STEP 模型或图纸")
    return _plm_call(plm.submit, H.db, _emit_as(u), u["mode"], who(u), _uid(u), item,
                     step=blobs.get("step", (None, None))[0], step_name=blobs.get("step", (None, None))[1],
                     drawing=blobs.get("drawing", (None, None))[0], drawing_name=blobs.get("drawing", (None, None))[1],
                     gcode=blobs.get("gcode", (None, None))[0], operation=operation.strip() or None, note=note.strip()[:500])


@app.get("/api/plm/submissions")
def plm_list(status: str = "", item: str = "", u=Depends(user_of)):
    where, args = ["mode=%s"], [u["mode"]]
    if status:
        where.append("status=%s")
        args.append(status)
    if item:
        where.append("item=%s")
        args.append(item)
    rows = H.db.q("select s.id, s.item, s.status, s.author, s.author_uid, s.ts, s.note, s.base_rev, s.revision, s.decided_by, "
                  "s.decided_at, s.decision, (select count(*) from design_comment c where c.sub_id=s.id and not c.resolved) "
                  "as open_comments from design_submission s where " + " and ".join(where) + " order by s.ts desc limit 200", args)
    me = _uid(u)
    out = []
    for r in rows:
        r = dict(r)
        r["mine"] = r.pop("author_uid") == me
        out.append(r)
    return out


@app.get("/api/plm/submissions/{sid}")
def plm_get(sid: str, u=Depends(user_of)):
    s = plm.get(H.db, sid)
    if not s or s["mode"] != u["mode"]:
        raise HTTPException(404, "没有这次提交")
    _, base = plm.current_glb(H.db, s["mode"], s["item"]) if s["status"] == "pending" else (None, None)
    s["base_glb"] = base["url"] if base else None
    s["mine"] = s["author_uid"] == _uid(u)
    s["can_approve"] = u["role"] in ("approver", "manager") and not s["mine"] and s["status"] == "pending"
    s.pop("author_uid", None)
    return s


@app.post("/api/plm/submissions/{sid}/comments")
def plm_comment(sid: str, body: dict = Body(...), u=Depends(user_of)):
    return _plm_call(plm.comment, H.db, sid, who(u), body.get("body"), body.get("anchor"))


@app.post("/api/plm/submissions/{sid}/comments/{cid}")
def plm_resolve(sid: str, cid: int, body: dict = Body(default={}), u=Depends(user_of)):
    return plm.resolve_comment(H.db, sid, cid, bool(body.get("resolved", True)))


@app.post("/api/plm/submissions/{sid}/decision")
def plm_decision(sid: str, body: dict = Body(...), u=Depends(user_of)):
    d, note = body.get("decision"), (body.get("note") or "").strip()[:500]
    if d == "approve":
        _can_approve(u)
        return _plm_call(plm.approve, H.db, _emit_as(u), sid, who(u), note, approver_uid=_uid(u))
    if d == "reject":
        _can_approve(u)
        return _plm_call(plm.decide, H.db, _emit_as(u), sid, who(u), "rejected", note)
    if d == "withdraw":
        s = plm.get(H.db, sid)
        if not s or s["author_uid"] != _uid(u):
            raise HTTPException(403, "只有提交人能撤回")
        return _plm_call(plm.decide, H.db, _emit_as(u), sid, s["author"], "withdrawn", note)
    raise HTTPException(400, "decision 只能是 approve / reject / withdraw")


# 工艺规程（第 13 轮《机械制造技术》2.7 节）：提交 → AI 工艺评审员预审 → 老师批准 → ERPNext BOM 工序与 MES 派工生效
def _can_approve_process(u):
    if u.get("teacher") or u["role"] in ("approver", "manager"):
        return
    raise HTTPException(403, "批准工艺规程要用老师、审批人或厂长账号")


@app.get("/api/process/{item}")
def process_item(item: str, u=Depends(user_of)):
    if item not in F.ITEMS:
        raise HTTPException(404, "没有这个零件")
    subs = H.db.q("select id, status, author, ts, revision, review->'suggested_score' as score from process_submission "
                  "where mode=%s and item=%s order by ts desc limit 30", (u["mode"], item))
    return {"item": item, "revision": process.current_revision(H.db, u["mode"], item),
            "routing": process.active_routing(H.db, u["mode"], item) or [list(x) for x in F.ROUTINGS[F.BOMS[item][0]]] if item in F.BOMS else [],
            "factory_plan": process.factory_plan(item) if item in F.BOMS else None, "submissions": [dict(r) for r in subs]}


@app.post("/api/process/review")
def process_preview(plan: dict = Body(...), u=Depends(user_of)):
    """AI 预检：不提交，只看意见（工艺员边写边查）。"""
    f = process.review(plan)
    return {"findings": f, "suggested_score": process.suggested_score(f)}


def _plan_of(body: dict) -> dict:
    """工艺规程：网页上传的 YAML 原文（yaml）或数据（plan）。"""
    if body.get("yaml"):
        import yaml
        text = str(body["yaml"])
        if len(text) > 1_000_000:
            raise HTTPException(413, "工艺规程太大（超过 1 MB）")
        try:
            plan = yaml.safe_load(text)
        except yaml.YAMLError as e:
            raise HTTPException(400, f"YAML 格式有错：{str(e)[:300]}")
    else:
        plan = body.get("plan")
    if not isinstance(plan, dict) or not plan.get("item"):
        raise HTTPException(400, "这不是一份工艺规程（要有 item、operations 等，可先下载参照工艺规程照着改）")
    return json.loads(json.dumps(plan, ensure_ascii=False, default=str))      # YAML 里不带引号的日期等转成文字，才能存库


@app.post("/api/process/check")
def process_check(body: dict = Body(...), u=Depends(user_of)):
    """“工艺规程与 AI 评审”页（第 13 轮 8.8（3a））：上传的工艺规程预检（不记录）或提交审批。"""
    plan = _plan_of(body)
    if not body.get("submit"):
        try:
            f = process.review(plan)
        except (KeyError, TypeError, ValueError) as e:
            raise HTTPException(400, f"工艺规程数据不完整，评审不了：{e!r}"[:400])
        return {"findings": f, "suggested_score": process.suggested_score(f)}
    _can_submit(u)
    return _plm_call(process.submit, H.db, _emit_as(u), u["mode"], who(u), _uid(u), plan, (body.get("note") or "")[:500])


@app.get("/api/process/reference/{item}")
def process_reference(item: str, u=Depends(user_of)):
    """参照工艺规程原文（std/<零件>_process.yaml），学生下载后照着改。"""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "std", f"{item}_process.yaml")
    if item not in F.ITEMS or not os.path.exists(path):
        raise HTTPException(404, "这个零件没有参照工艺规程")
    with open(path, encoding="utf-8") as f:
        return {"item": item, "yaml": f.read()}


@app.post("/api/process/submit")
def process_submit(body: dict = Body(...), u=Depends(user_of)):
    _can_submit(u)
    return _plm_call(process.submit, H.db, _emit_as(u), u["mode"], who(u), _uid(u), body.get("plan") or {},
                     (body.get("note") or "")[:500])


@app.get("/api/process/submissions/{sid}")
def process_get(sid: str, u=Depends(user_of)):
    s = process.get(H.db, sid)
    if not s or s["mode"] != u["mode"]:
        raise HTTPException(404, "没有这次提交")
    return s


def _cards_response(plan: dict, fmt: str):
    """全套工艺文件（第 13 轮 N2）：HTML 直接看、用浏览器打印成 PDF；fmt=docx 下载可编辑的 Word。"""
    if not plan.get("operations") or not plan.get("doc"):
        raise HTTPException(400, "这份工艺规程还不是数据格式 v2（缺 doc 或 operations），生成不了卡片")
    try:
        if fmt == "docx":
            import tempfile
            with tempfile.TemporaryDirectory() as d:
                path = proc_cards.docx(plan, os.path.join(d, "cards.docx"))
                data = path.read_bytes()
            name = urllib.parse.quote(f"{plan.get('item', 'part')}_工艺文件.docx")
            return Response(data, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{name}"})
        return Response(proc_cards.html(plan), media_type="text/html; charset=utf-8")
    except (KeyError, TypeError, ValueError, StopIteration) as e:
        raise HTTPException(400, f"工艺规程数据不完整，生成卡片失败：{e!r}")


@app.get("/api/process/cards/reference/{item}")
def process_cards_reference(item: str, fmt: str = "html", u=Depends(user_of)):
    """参照工艺规程（std/<零件>_process.yaml）的全套卡片：教材第 50 章的样例就是它。"""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "std", f"{item}_process.yaml")
    if item not in F.ITEMS or not os.path.exists(path):
        raise HTTPException(404, "这个零件没有参照工艺规程")
    return _cards_response(proc_cards.load(path), fmt)


@app.post("/api/process/cards")
def process_cards_preview(plan: dict = Body(...), fmt: str = "html", u=Depends(user_of)):
    """工艺员边写边看卡片（不提交）。"""
    return _cards_response(plan, fmt)


@app.get("/api/process/submissions/{sid}/cards")
def process_cards_submission(sid: str, fmt: str = "html", u=Depends(user_of)):
    s = process.get(H.db, sid)
    if not s or s["mode"] != u["mode"]:
        raise HTTPException(404, "没有这次提交")
    return _cards_response(s["plan"], fmt)


@app.post("/api/process/submissions/{sid}/comments/{cid}")
def process_resolve(sid: str, cid: int, body: dict = Body(default={}), u=Depends(user_of)):
    return process.resolve(H.db, sid, cid, bool(body.get("resolved", True)))


@app.post("/api/process/submissions/{sid}/decision")
def process_decision(sid: str, body: dict = Body(...), u=Depends(user_of)):
    d, note = body.get("decision"), (body.get("note") or "").strip()[:500]
    _can_approve_process(u)
    if d == "approve":
        s = _plm_call(process.approve, H.db, _emit_as(u), sid, who(u), note, approver_uid=_uid(u))
        s["programs_released"] = _cam.release_programs(H.db, _emit_as(u, "cam"), s)      # 第 13 轮：挂在工序上的数控程序随之下发
        return s
    if d == "reject":
        return _plm_call(process.reject, H.db, _emit_as(u), sid, who(u), note)
    raise HTTPException(400, "decision 只能是 approve / reject")


# 质量统计（第 13 轮〔SPC〕）：控制图、判异、过程能力；测量系统分析
@app.get("/api/quality/spc")
def quality_spc(item: str = "SH-301", characteristic: str = "bearing_seat_d35", n: int = 5, u=Depends(user_of)):
    if not 2 <= n <= 10:
        raise HTTPException(400, "子组容量 n 取 2–10")
    return spc.for_characteristic(H.db, u["mode"], item, characteristic, n)


@app.post("/api/quality/msa")
def quality_msa(body: dict = Body(...), u=Depends(user_of)):
    """data[检验员][零件] = [各次读数]；tol 为公差带宽度（可选）"""
    try:
        return spc.grr_anova(body["data"], body.get("tol"))
    except (KeyError, ValueError, ZeroDivisionError, TypeError, IndexError) as e:   # noqa: F821
        raise HTTPException(422, "数据格式不对：{}".format(e))


# 参数配置器（第 8 轮 Q6）
@app.get("/api/configurator")
def cfg_templates(u=Depends(user_of)):
    return configurator.templates()


@app.post("/api/configurator/{tid}/evaluate")
def cfg_evaluate(tid: str, body: dict = Body(default={}), u=Depends(user_of)):
    try:
        return configurator.evaluate(tid, body.get("values"), int(body.get("qty") or 1))
    except KeyError as e:
        raise HTTPException(404, str(e).strip("'"))


@app.post("/api/configurator/{tid}/model")
def cfg_model(tid: str, body: dict = Body(default={}), u=Depends(user_of)):
    """三维（glb）和图纸（SVG）：按参数缓存，同一组参数只生成一次"""
    if tid not in configurator.TEMPLATES:
        raise HTTPException(404, "没有这个模板")
    key = configurator.model_key(tid, body.get("values"))
    got = {r["name"]: r["sha256"] for r in H.db.q("select name, sha256 from stored_file where name = any(%s)",
                                                       (["cfg-{}.glb".format(key), "cfg-{}.svg".format(key)],))}
    if len(got) < 2:
        try:
            glb, svg = configurator.model(tid, body.get("values"))
        except Exception as e:  # noqa: BLE001
            log.exception("配置器建模失败")
            raise HTTPException(500, "三维生成失败：{}".format(str(e)[:120]))
        got = {"cfg-{}.glb".format(key): plm.store(H.db, "cfg-{}.glb".format(key), "model/gltf-binary", glb)["sha256"],
               "cfg-{}.svg".format(key): plm.store(H.db, "cfg-{}.svg".format(key), "image/svg+xml", svg)["sha256"]}
    return {"glb": "/api/files/" + got["cfg-{}.glb".format(key)], "drawing": "/api/files/" + got["cfg-{}.svg".format(key)]}


@app.post("/api/configurator/{tid}/order")
def cfg_order(tid: str, body: dict = Body(...), u=Depends(user_of)):
    """按报价草拟订单：走现有“提议—确认”，确认后桥接写入 ERPNext（销售订单带报价单价）"""
    if u["mode"] == "prod" and u["role"] not in ("sales", "planner", "manager"):
        raise HTTPException(403, "下单要用销售、计划员或厂长角色")
    try:
        r = configurator.evaluate(tid, body.get("values"), int(body.get("qty") or 1))
    except KeyError as e:
        raise HTTPException(404, str(e).strip("'"))
    if not r["ok"]:
        raise HTTPException(422, "校核没通过，不能下单：" + "；".join(r["errors"]))
    q = r["quote"]
    try:
        pv = mrp.plan_order(H.db, body.get("customer"), r["item"], q["qty"], body["delivery_date"], u["mode"])
    except (KeyError, ValueError) as e:
        raise HTTPException(400, "订单信息不完整：{}".format(e))
    pv["sales_order"].update(rate=q["unit_price"], amount=q["total"])
    pv["configuration"] = {"template": tid, "values": r["values"], "figures": r["figures"], "quote": q}
    from hub.ai import _order_title
    title = "配置器：" + _order_title(pv)
    pid = H.ai.propose("create_order_and_plan", pv, u["mode"], u["name"], title, source="configurator/" + who(u), role=u["role"])
    return {"proposal_id": pid, "title": title, "preview": pv}


# 企业成员（第 8 轮 Q7）：老师授权登录过的问渠账号在生产模式使用某些角色
@app.get("/api/plm/members")
def plm_members(u=Depends(user_of)):
    require_teacher(u)
    rows = H.db.q("select k.uid, k.name, k.teacher, k.last_seen, m.roles from known_user k "
                  "left join enterprise_member m on m.uid=k.uid order by m.roles is null, k.last_seen desc limit 500")
    return [dict(r, roles=list(r["roles"] or [])) for r in rows]


@app.post("/api/plm/members/{uid}")
def plm_member_set(uid: str, body: dict = Body(...), u=Depends(user_of)):
    require_teacher(u)
    roles = [r for r in body.get("roles") or [] if r in ROLES and r != "manager"]
    if roles:
        H.db.x("insert into enterprise_member (uid, roles, added_by) values (%s,%s,%s) on conflict (uid) do update "
               "set roles=excluded.roles, added_by=excluded.added_by, added_at=now()", (uid, roles, who(u)))
    else:
        H.db.x("delete from enterprise_member where uid=%s", (uid,))
    return {"uid": uid, "roles": roles}


# ---------------------------------------------------------------- ERPNext 单点登录（第 7 轮）
_codes = erp_sso.Codes()


def _sso_person(request, wq_token):
    """当前是谁：线上看学习平台登录（没登录返回跳转），本地版看工作台凭证。返回 (person, redirect)"""
    from fastapi.responses import RedirectResponse
    if AUTH == "wenquest":
        w = wenquest_user(request.cookies.get(SSO_COOKIE, ""))
        if not w:                                    # 还没登录学习平台：先去登录，登录后回到这里
            proto = request.headers.get("x-forwarded-proto") or request.url.scheme
            here = "{}://{}{}?{}".format(proto, request.headers.get("host") or request.url.netloc,
                                         request.url.path, request.url.query)
            return None, RedirectResponse((LOGIN_URL or "/") + "?back=" + urllib.parse.quote(here, safe=""), 302)
        return {"uid": w["id"], "name": w["fullname"] or w["username"], "teacher": w["teacher"]}, None
    try:                                             # 本地版（和 CI 演练）：用工作台凭证代表身份
        u = user_of(wq_token)
    except HTTPException:
        raise HTTPException(401, "本地版请带工作台登录凭证 wq_token")
    return {"uid": erp_sso.local_uid(u["name"]), "name": u["name"], "teacher": u.get("teacher", True)}, None


def _sso_finish(person, redirect_uri, state):
    """在 ERPNext 建好账号，带一次性授权码回到 ERPNext"""
    from fastapi.responses import RedirectResponse
    ident = erp_sso.erp_identity(person, erp_sso.config()["user_domain"])
    try:
        erp_sso.provision(ident)
    except Exception as e:  # noqa: BLE001
        log.exception("ERPNext 建账号失败")
        raise HTTPException(502, "ERPNext 暂时不能登录：{}".format(e))
    code = _codes.issue(ident, redirect_uri)
    return RedirectResponse("{}?{}".format(redirect_uri, urllib.parse.urlencode({"code": code, "state": state})), 302)


@app.get("/api/oauth/authorize")
def oauth_authorize(request: Request, client_id: str = "", redirect_uri: str = "", state: str = "",
                    response_type: str = "code", wq_token: str = ""):
    """ERPNext 登录页跳过来：核对问渠账号 → 在 ERPNext 建好账号 → 带一次性授权码回去"""
    if client_id != erp_sso.CLIENT_ID or response_type != "code" or not erp_sso.valid_redirect(redirect_uri):
        raise HTTPException(400, "登录请求不合规范")
    if not erp_sso.enabled():
        raise HTTPException(503, "ERPNext 单点登录还没有配置")
    person, go = _sso_person(request, wq_token)
    return go or _sso_finish(person, redirect_uri, state)


@app.get("/api/erp/sso")
def erp_sso_start(request: Request, next: str = "", wq_token: str = "", go: int = 0):
    """工作台“ERPNext”入口（第 7 轮补）：不靠 ERPNext 登录页上的脚本（浏览器可能缓存了旧脚本），
    由枢纽向 ERPNext 要一个登录请求编号（state），直接走完授权，浏览器一步进到 ERPNext。
    先回一个“正在进入”的等待页（建账号、登录、打开 ERPNext 要几秒），再自动接着走（go=1）"""
    if not go:
        from fastapi.responses import HTMLResponse
        q = dict(request.query_params, go="1")
        return HTMLResponse(ERP_WAIT_PAGE.replace("__URL__", json.dumps(request.url.path + "?" + urllib.parse.urlencode(q))))
    if not erp_sso.enabled():
        raise HTTPException(503, "ERPNext 单点登录还没有配置")
    person, go = _sso_person(request, wq_token)
    if go:
        return go
    try:
        auth = erp_sso.login_request(next if next.startswith("/") else "")
    except Exception as e:  # noqa: BLE001
        log.exception("向 ERPNext 要登录请求失败")
        raise HTTPException(502, "ERPNext 暂时不能登录：{}".format(e))
    return _sso_finish(person, auth["redirect_uri"], auth["state"])


ERP_WAIT_PAGE = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>正在进入 ERPNext…</title>
<style>
body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;background:#F4F6F8;
 font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;color:#1F2A33}
.box{width:min(420px,90vw);text-align:center}
h1{font-size:18px;font-weight:600;margin:0 0 6px}
p{font-size:13px;color:#5B6B78;margin:0 0 18px;min-height:1.4em}
.bar{height:6px;border-radius:3px;background:#DDE3E8;overflow:hidden}
.bar i{display:block;height:100%;width:0;background:#1E6A7A;border-radius:3px;transition:width .6s ease}
</style></head><body><div class="box">
<h1>正在进入 ERPNext</h1><p id="t">核对问渠账号…</p><div class="bar"><i id="b"></i></div>
</div><script>
var steps=[[8,"核对问渠账号…"],[30,"准备你的 ERPNext 账号…"],[55,"登录 ERPNext…"],[75,"打开 ERPNext 工作台（第一次会慢一些）…"],[90,"快好了…"]];
var k=0,b=document.getElementById("b"),t=document.getElementById("t");
function tick(){if(k<steps.length){b.style.width=steps[k][0]+"%";t.textContent=steps[k][1];k++;setTimeout(tick,k<3?900:2500);}}
tick();setTimeout(function(){location.replace(__URL__);},150);
</script></body></html>"""


@app.post("/api/oauth/token")
async def oauth_token(request: Request):
    """ERPNext 服务器用授权码和密钥换令牌（表单提交）"""
    f = await request.form()
    if not erp_sso.check_client(f.get("client_id"), f.get("client_secret")):
        return JSONResponse({"error": "invalid_client"}, 401)
    if f.get("grant_type") != "authorization_code":
        return JSONResponse({"error": "unsupported_grant_type"}, 400)
    ident = _codes.take(f.get("code", ""), f.get("redirect_uri", ""))
    if not ident:
        return JSONResponse({"error": "invalid_grant"}, 400)
    key = erp_sso.config()["secret"].encode()
    return {"access_token": erp_sso.sign_token(ident, key), "token_type": "Bearer", "expires_in": erp_sso.TOKEN_TTL}


@app.get("/api/oauth/userinfo")
def oauth_userinfo(authorization: str = Header(default="")):
    key = erp_sso.config()["secret"].encode()
    body = erp_sso.read_token(authorization.replace("Bearer ", "", 1).strip(), key) if key else None
    if not body:
        return JSONResponse({"error": "invalid_token"}, 401)
    return {k: body[k] for k in ("sub", "email", "email_verified", "name", "given_name")}


@app.get("/api/freecad/pack.zip")
def freecad_pack(request: Request, x_wq_token: str = Header(default=""), u=Depends(user_of)):
    """进阶：桌面 FreeCAD 宏包（第 6 轮 W5）。工作台地址、本人凭证、模式已填进 wq_publish.py，解压即用"""
    import io
    import zipfile
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    base = "{}://{}".format(proto, request.headers.get("host") or request.url.netloc)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name in ("wq_shaft.py", "wq_publish.py", "wq_drawing.py", "wq_cam_keyway.py", "wq_library.py", "wq_submit.py"):
            text = open(os.path.join(design_web.FREECAD_DIR, name), encoding="utf-8").read()
            if name == "wq_publish.py":
                text = (text.replace('os.environ.get("WQ_HUB_URL", "http://localhost:8100")', 'os.environ.get("WQ_HUB_URL", {!r})'.format(base))
                        .replace('os.environ.get("WQ_USER", "工艺员")', 'os.environ.get("WQ_USER", {!r})'.format(who(u)))
                        .replace('os.environ.get("WQ_MODE", "teach")', 'os.environ.get("WQ_MODE", {!r})'.format(u["mode"]))
                        .replace('os.environ.get("WQ_TOKEN", "")', 'os.environ.get("WQ_TOKEN", {!r})'.format(x_wq_token)))
            if name == "wq_library.py":
                text = text.replace('"https://factory.wenquestrobotics.com"', repr(base))
            z.writestr("wenquest-freecad/" + name, text)
            z.writestr("wenquest-freecad/Mod/WenQuest/" + name, text)      # 第 8 轮：“问渠”工作台（工具栏按钮）
        sw = open(os.path.join(design_web.FREECAD_DIR, "wq_submit_solidworks.swb"), encoding="ascii").read()     # 第 10 轮 S1
        z.writestr("wenquest-freecad/SolidWorks/wq_submit_solidworks.swb",
                   sw.replace("__WQ_HUB__", base).replace("__WQ_TOKEN__", x_wq_token).replace("\r\n", "\n").replace("\n", "\r\n"))   # VBA 宏用 CRLF
        for name in ("InitGui.py", "wq_workbench.py"):    # 工作台（第 39 轮第 5 步：InitGui 只找文件夹，代码在 wq_workbench.py）
            z.writestr("wenquest-freecad/Mod/WenQuest/" + name,
                       open(os.path.join(design_web.FREECAD_DIR, "Mod", "WenQuest", name), encoding="utf-8").read())
        z.writestr("wenquest-freecad/使用说明.txt", FREECAD_README.format(base=base, mode="教学" if u["mode"] == "teach" else "生产"))
    return Response(buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": "attachment; filename=wenquest-freecad.zip"})


FREECAD_README = """问渠数字工厂 · 我的 CAD 宏包（FreeCAD、SolidWorks；进阶，选做）

不想装软件的话，直接用“设计与工艺”页上的“在线设计”即可，效果相同。

1. 安装 FreeCAD 1.1（https://www.freecad.org/downloads.php），装好后打开。
2. 把本压缩包解压到任意文件夹，例如“文档\\wenquest-freecad”。
3. FreeCAD 菜单：宏 → 宏…，在“用户宏的位置”里选这个文件夹。
4. 改设计：在宏列表里选 wq_shaft.py → 编辑，修改 PARAMS（例如键槽长 45 → 42），保存。
5. 发布：选 wq_publish.py → 执行。成功后回到 {base}/work/engineer 刷新，能看到新版本、零件图和 G 代码。
6. 插入零件库标准件：执行 wq_library.py，搜索 6207 等编号。

任何零件提交到工厂（企业版）：
7. 把压缩包里的 Mod\\WenQuest 文件夹复制到 FreeCAD 的用户 Mod 目录
   （Windows：%APPDATA%\\FreeCAD\\Mod；macOS：~/Library/Application Support/FreeCAD/Mod；Linux：~/.local/share/FreeCAD/Mod），重启 FreeCAD。
8. 工作台列表里选“问渠”，工具栏出现“提交到问渠工厂”“插入零件库标准件”两个按钮。
9. 在模型树里选中零件 → 点“提交到问渠工厂” → 填物料编号和改动说明 → 提交。文档里有 TechDraw 图纸页的会一并导出 PDF。
   企业（生产）模式进“设计发布与审批”待审，审批人批准后才进 ERPNext 和车间。
   不装工作台也行：选中零件后执行 wq_submit.py 宏。

SolidWorks（第 10 轮）：
10. 在 SolidWorks 里打开要提交的零件或装配体（同名工程图也打开的话会一并导出 PDF）。
11. 菜单“工具 → 宏 → 运行”，文件类型选 *.swb，打开压缩包里的 SolidWorks\\wq_submit_solidworks.swb。
12. 按提示填物料编号和改动说明，提交。宏的提示是英文的（这样在任何语言的 Windows 上都不乱码）。

说明：wq_publish.py 里已经填好了工作台地址和你的登录凭证（{mode}模式，7 天内有效）。
发布时提示“请先登录”，说明凭证过期了：回到“设计与工艺”页重新下载宏包即可。
不要把这个宏包转给别人——别人用它发布会记在你名下。
"""


# ---------------------------------------------------------------- 教学
@app.get("/api/teach")
def teach_status(u=Depends(user_of)):
    if u["mode"] != "teach":
        raise HTTPException(409, "生产模式没有实验任务")
    return H.teach.check(u["name"])


@app.post("/api/teach/{tid}")
def teach_answer(tid: str, body: dict = Body(...), u=Depends(user_of)):
    if u["mode"] != "teach":
        raise HTTPException(409, "生产模式没有实验任务")
    try:
        return H.teach.answer(u["name"], tid, body)
    except KeyError:
        raise HTTPException(404, "这个任务不用提交答案，系统会自动检查")


# ---------------------------------------------------------------- 实验 15（第 17 轮 D 期 D9）
@app.get("/api/lab15")
def lab15_status(u=Depends(user_of)):
    from hub import lab15
    if u["mode"] != "teach":
        raise HTTPException(409, "生产模式没有实验任务")
    out = lab15.check(H.db, u["name"])
    out["teacher"] = bool(u.get("teacher"))
    out["inject_kinds"] = lab15.INJECT
    if u.get("teacher"):
        out["class"] = lab15.class_view(H.db)
    return out


@app.post("/api/lab15/inject")
def lab15_inject(body: dict = Body(...), u=Depends(user_of)):
    from hub import lab15
    try:
        return lab15.inject(H, u, body.get("kind"), body)
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e))


@app.post("/api/lab15/{tid}")
def lab15_answer(tid: str, body: dict = Body(...), u=Depends(user_of)):
    from hub import lab15
    if u["mode"] != "teach":
        raise HTTPException(409, "生产模式没有实验任务")
    try:
        return lab15.answer(H.db, u["name"], tid, body)
    except KeyError:
        raise HTTPException(404, "这个任务不用提交答案，系统会自动检查")


# ---------------------------------------------------------------- 实验 16（第 18 轮 E1-12）
@app.get("/api/lab16")
def lab16_status(u=Depends(user_of)):
    from hub import lab16
    if u["mode"] != "teach":
        raise HTTPException(409, "生产模式没有实验任务")
    out = lab16.check(H.db, u["name"])
    out["teacher"] = bool(u.get("teacher"))
    if u.get("teacher"):
        out["class"] = lab16.class_view(H.db)
    return out


@app.post("/api/lab16/inject")
def lab16_inject(body: dict = Body(default={}), u=Depends(user_of)):
    from hub import lab16
    try:
        return lab16.inject(H, u, body)
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e))


@app.post("/api/lab16/{tid}")
def lab16_answer(tid: str, body: dict = Body(...), u=Depends(user_of)):
    from hub import lab16
    if u["mode"] != "teach":
        raise HTTPException(409, "生产模式没有实验任务")
    try:
        return lab16.answer(H.db, u["name"], tid, body)
    except KeyError:
        raise HTTPException(404, "这个任务不用提交答案，系统会自动检查")


# ---------------------------------------------------------------- 实验 17（第 18 轮 E2-9）
@app.get("/api/lab17")
def lab17_status(u=Depends(user_of)):
    from hub import lab17
    if u["mode"] != "teach":
        raise HTTPException(409, "生产模式没有实验任务")
    out = lab17.check(H.db, u["name"])
    out["teacher"] = bool(u.get("teacher"))
    if u.get("teacher"):
        out["class"] = lab17.class_view(H.db)
    return out


@app.post("/api/lab17/inject")
def lab17_inject(body: dict = Body(default={}), u=Depends(user_of)):
    from hub import lab17
    try:
        return lab17.inject(H, u, body)
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e))


@app.post("/api/lab17/{tid}")
def lab17_answer(tid: str, body: dict = Body(...), u=Depends(user_of)):
    from hub import lab17
    if u["mode"] != "teach":
        raise HTTPException(409, "生产模式没有实验任务")
    try:
        return lab17.answer(H.db, u["name"], tid, body)
    except KeyError:
        raise HTTPException(404, "这个任务不用提交答案，系统会自动检查")


# ---------------------------------------------------------------- 实验 18（第 18 轮 E3-9）
@app.get("/api/lab18")
def lab18_status(u=Depends(user_of)):
    from hub import lab18
    if u["mode"] != "teach":
        raise HTTPException(409, "生产模式没有实验任务")
    out = lab18.check(H.db, u["name"])
    out["teacher"] = bool(u.get("teacher"))
    if u.get("teacher"):
        out["class"] = lab18.class_view(H.db)
    return out


@app.post("/api/lab18/inject")
def lab18_inject(body: dict = Body(default={}), u=Depends(user_of)):
    from hub import lab18
    try:
        return lab18.inject(H, u, body)
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e))


@app.post("/api/lab18/{tid}")
def lab18_answer(tid: str, body: dict = Body(...), u=Depends(user_of)):
    from hub import lab18
    if u["mode"] != "teach":
        raise HTTPException(409, "生产模式没有实验任务")
    try:
        return lab18.answer(H.db, u["name"], tid, body)
    except KeyError:
        raise HTTPException(404, "这个任务不用提交答案，系统会自动检查")


# ---------------------------------------------------------------- 实验 22（第 18 轮 E7-10）
# ---------------------------------------------------------------- 实验 23（第 19 轮 J-7）：两周情景，分组、分角色
@app.get("/api/lab23")
def lab23_status(u=Depends(user_of)):
    from hub import lab23
    if u["mode"] != "teach":
        raise HTTPException(409, "生产模式没有实验任务")
    out = lab23.check(H.db, u["name"])
    out["teacher"] = bool(u.get("teacher"))
    if u.get("teacher"):
        out["class"] = lab23.class_view(H.db)
    return out


@app.post("/api/lab23/register")
def lab23_register(body: dict = Body(...), u=Depends(user_of)):
    from hub import lab23
    if u["mode"] != "teach":
        raise HTTPException(409, "生产模式没有实验任务")
    try:
        return lab23.register(H.db, u["name"], body.get("team"), body.get("role"))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/lab23/decide/{n}")
def lab23_decide(n: int, body: dict = Body(...), u=Depends(user_of)):
    from hub import lab23
    if u["mode"] != "teach":
        raise HTTPException(409, "生产模式没有实验任务")
    try:
        return lab23.decide(H, u, n, body.get("option"), body.get("reason"))
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e))


@app.post("/api/lab23/{tid}")
def lab23_answer(tid: str, body: dict = Body(...), u=Depends(user_of)):
    from hub import lab23
    if u["mode"] != "teach":
        raise HTTPException(409, "生产模式没有实验任务")
    try:
        return lab23.answer(H, u["name"], tid, body)
    except KeyError:
        raise HTTPException(404, "这个任务不用提交答案，系统会自动检查")


@app.get("/api/lab22")
def lab22_status(u=Depends(user_of)):
    from hub import lab22
    if u["mode"] != "teach":
        raise HTTPException(409, "生产模式没有实验任务")
    out = lab22.check(H.db, u["name"])
    out["teacher"] = bool(u.get("teacher"))
    if u.get("teacher"):
        out["class"] = lab22.class_view(H.db)
    return out


@app.post("/api/lab22/inject")
def lab22_inject(body: dict = Body(default={}), u=Depends(user_of)):
    from hub import lab22
    try:
        return lab22.inject(H, u, body)
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e))


@app.post("/api/lab22/{tid}")
def lab22_answer(tid: str, body: dict = Body(...), u=Depends(user_of)):
    from hub import lab22
    if u["mode"] != "teach":
        raise HTTPException(409, "生产模式没有实验任务")
    try:
        return lab22.answer(H.db, u["name"], tid, body)
    except KeyError:
        raise HTTPException(404, "这个任务不用提交答案，系统会自动检查")


# ---------------------------------------------------------------- 实验 21（第 18 轮 E6-10）
@app.get("/api/lab21")
def lab21_status(u=Depends(user_of)):
    from hub import lab21
    if u["mode"] != "teach":
        raise HTTPException(409, "生产模式没有实验任务")
    out = lab21.check(H.db, u["name"])
    out["teacher"] = bool(u.get("teacher"))
    if u.get("teacher"):
        out["class"] = lab21.class_view(H.db)
    return out


@app.post("/api/lab21/inject")
def lab21_inject(body: dict = Body(default={}), u=Depends(user_of)):
    from hub import lab21
    try:
        return lab21.inject(H, u, body)
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e))


@app.post("/api/lab21/{tid}")
def lab21_answer(tid: str, body: dict = Body(...), u=Depends(user_of)):
    from hub import lab21
    if u["mode"] != "teach":
        raise HTTPException(409, "生产模式没有实验任务")
    try:
        return lab21.answer(H.db, u["name"], tid, body)
    except KeyError:
        raise HTTPException(404, "这个任务不用提交答案，系统会自动检查")


# ---------------------------------------------------------------- 实验 20（第 18 轮 E5-8）
@app.get("/api/lab20")
def lab20_status(u=Depends(user_of)):
    from hub import lab20
    if u["mode"] != "teach":
        raise HTTPException(409, "生产模式没有实验任务")
    out = lab20.check(H.db, u["name"])
    out["teacher"] = bool(u.get("teacher"))
    if u.get("teacher"):
        out["class"] = lab20.class_view(H.db)
    return out


@app.post("/api/lab20/inject")
def lab20_inject(body: dict = Body(default={}), u=Depends(user_of)):
    from hub import lab20
    try:
        return lab20.inject(H, u, body)
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e))


@app.post("/api/lab20/{tid}")
def lab20_answer(tid: str, body: dict = Body(...), u=Depends(user_of)):
    from hub import lab20
    if u["mode"] != "teach":
        raise HTTPException(409, "生产模式没有实验任务")
    try:
        return lab20.answer(H.db, u["name"], tid, body)
    except KeyError:
        raise HTTPException(404, "这个任务不用提交答案，系统会自动检查")


# ---------------------------------------------------------------- 实验 19（第 18 轮 E4-10）
@app.get("/api/lab19")
def lab19_status(u=Depends(user_of)):
    from hub import lab19
    if u["mode"] != "teach":
        raise HTTPException(409, "生产模式没有实验任务")
    out = lab19.check(H.db, u["name"])
    out["teacher"] = bool(u.get("teacher"))
    if u.get("teacher"):
        out["class"] = lab19.class_view(H.db)
    return out


@app.post("/api/lab19/inject")
def lab19_inject(body: dict = Body(default={}), u=Depends(user_of)):
    from hub import lab19
    try:
        return lab19.inject(H, u, body)
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e))


@app.post("/api/lab19/{tid}")
def lab19_answer(tid: str, body: dict = Body(...), u=Depends(user_of)):
    from hub import lab19
    if u["mode"] != "teach":
        raise HTTPException(409, "生产模式没有实验任务")
    try:
        return lab19.answer(H.db, u["name"], tid, body)
    except KeyError:
        raise HTTPException(404, "这个任务不用提交答案，系统会自动检查")


@app.post("/api/scenario/reset")
def teach_reset(body: dict = Body(default={}), u=Depends(user_of)):
    """重置教学情景：清空教学模式的历史，让仿真器重新载入实验 7 情景。只有“厂长”角色（教师）能做。"""
    require_teacher(u)
    if u["role"] != "manager":
        raise HTTPException(403, "请用厂长（教师）角色重置")
    reset_teach(who(u), float(body.get("speed", 1)), bool(body.get("scores")))
    return {"reset": True}


def reset_teach(by, speed=1.0, scores=False):
    """清空教学模式的历史和各领域状态，让仿真器重新载入实验 7 情景（第 19 轮：情景导演“开始两周情景”也用它）"""
    H.db.x("delete from bus_message where mode='teach'")
    H.db.x("delete from machine_state_log where mode='teach'")
    H.db.x("delete from ncr where mode='teach' or mode is null")
    H.db.x("delete from ai_proposal where mode='teach'")
    if scores:
        H.db.x("delete from task_result")
    H.hist._last_state = {k: v for k, v in H.hist._last_state.items() if k[1] != "teach"}
    H.hist._failed_parts.clear()
    H.ai._sent = {k: v for k, v in H.ai._sent.items() if k[0] != "teach"}
    H.ai.detector().init()                     # 厂情中枢的异常（第 17 轮 B 期）随情景一起清空
    H.db.x("delete from anomaly_note where anomaly_id in (select id from anomaly where mode='teach')")
    H.db.x("delete from anomaly where mode='teach'")
    H.db.x("update quality_problem set cleared_at=now(), cleared_how='scenario' where mode='teach' and cleared_at is null")
    H.twin.reset("teach")
    from hub import service as _SV                        # 第 18 轮 E1：投诉、服务、回访、模拟器状态一起清空
    _SV.reset(H.db, "teach")
    from hub import ehs as _EH                            # 第 18 轮 E2：隐患、许可、事故、培训、化学品、废物回到情景初始
    _EH.reset(H.db, "teach")
    from hub import maint as _MT                          # 第 18 轮 E3：点检、故障、维修、保养单清空（车间重载情景时可靠性回到关闭）
    _MT.reset(H.db, "teach")
    from hub import people as _PE                         # 第 18 轮 E4：出勤、调班、加班、培训清空，技能回到初始，“要有人”关闭
    _PE.reset(H.db, "teach")
    from hub import supply as _SP                         # 第 18 轮 E5：批次清空，备选供应商回到初始，供应商模拟器关闭
    _SP.reset(H.db, "teach")
    from hub import energy as _EG                         # 第 18 轮 E6：读数清空，节能设定、错峰回到初始，模拟器关闭（计量照开）
    _EG.reset(H.db, "teach")
    from hub import finance as _FN                        # 第 18 轮 E7：发票、毛利清空，期初应收重建，预算目标信用回默认，模拟器关闭
    _FN.reset(H.db, "teach")
    if H.ont is not None:
        H.ont.reset_mode("teach")
    H.mes.command("sim", "load_scenario", "teach", by, speed=float(speed))


# ---------------------------------------------------------------- 零件库文件（第 2 轮 L14）
from hub import library as _library  # noqa: E402
_library.mount(app)

# ---------------------------------------------------------------- 课程接口（第 4 轮）
from hub import course as _course  # noqa: E402
_course.mount(app, H)


# ---------------------------------------------------------------- 仿真与分析（第 11 轮）
from hub import cae_api as _cae  # noqa: E402
_cae.mount(app, H, user_of, who, _uid, lambda u: bool(u.get("teacher")), ai_quota)

# ---------------------------------------------------------------- 数控编程（第 13 轮）
from hub import cam_api as _cam  # noqa: E402
_cam.mount(app, H, user_of, who, _uid, lambda u: bool(u.get("teacher")), ai_quota)
_cam.mount_release(app, H, user_of, who, _uid, lambda u: bool(u.get("teacher")), _emit_as, _can_submit)

# ---------------------------------------------------------------- 设计优化（第 14 轮）
from hub import opt_api as _opt  # noqa: E402
_opt.mount(app, H, user_of, who, _uid, lambda u: bool(u.get("teacher")), ai_quota)

# ---------------------------------------------------------------- 流体分析（第 16 轮）
from hub import cfd_api as _cfd  # noqa: E402
_cfd.mount(app, H, user_of, who, _uid, lambda u: bool(u.get("teacher")), ai_quota)

# ---------------------------------------------------------------- 数字孪生（第 15 轮）
from hub import twin_api as _twin  # noqa: E402
_twin.mount(app, H, user_of, who, _uid, lambda u: bool(u.get("teacher")), ai_quota)


# ---------------------------------------------------------------- 厂情中枢：工厂本体（第 17 轮 A 期）
from hub.ont import api as _ont  # noqa: E402
_ont.mount(app, H, user_of)
from hub import service_api as _service_api  # noqa: E402
_service_api.mount(app, H, user_of, who)          # 第 18 轮 E1：客户与服务
from hub import ehs_api as _ehs_api  # noqa: E402
_ehs_api.mount(app, H, user_of, who)              # 第 18 轮 E2：安全环保
from hub import maint_api as _maint_api  # noqa: E402
_maint_api.mount(app, H, user_of, who)            # 第 18 轮 E3：设备维护
from hub import people_api as _people_api  # noqa: E402
_people_api.mount(app, H, user_of, who)           # 第 18 轮 E4：人员与排班
from hub import supply_api as _supply_api  # noqa: E402
_supply_api.mount(app, H, user_of, who)           # 第 18 轮 E5：采购与来料
from hub import energy_api as _energy_api  # noqa: E402
_energy_api.mount(app, H, user_of, who)           # 第 18 轮 E6：能源与环境
from hub import finance_api as _finance_api  # noqa: E402
_finance_api.mount(app, H, user_of, who)          # 第 18 轮 E7：经营与财务
from hub import story_api as _story_api  # noqa: E402
_story_api.mount(app, H, user_of, who, reset_teach)   # 第 19 轮：情景导演（两周情景）
from hub import help_api as _help_api  # noqa: E402
_help_api.mount(app, user_of)                          # 第 19 轮：帮助在网页里读；第 30 轮：/api/help/docs、帮助视频 /api/help/media、/help-media/
from hub import help_try as _help_try  # noqa: E402
_help_try.mount(app, H, user_of, who)                  # 第 30 轮 §八 8-1：帮助里的“当场动手”（只在演示工厂、教学模式）
from hub import labs_api as _labs_api  # noqa: E402
_labs_api.mount(app, H, user_of)                       # 第 19 轮：“实验与任务”一个入口
from hub.ont import agent_api as _agent_api  # noqa: E402
_agent_api.mount(app, H, user_of, who, ai_quota)  # 第 17 轮 D 期：AI 代理（要在 mount_anomaly 之前）
_ont.mount_anomaly(app, H, user_of, who)          # 第 17 轮 B 期：异常、追因、态势、规则
from hub.ont import plan_api as _plan  # noqa: E402
_plan.mount(app, H, user_of, who)                 # 第 17 轮 C 期：班次、推演、动作、时间回看


# ---------------------------------------------------------------- 虚拟 PLC（第 18 轮第 8 步《PLC 原理及实践》）
from hub import vplc as _vplc  # noqa: E402
_vplc.mount(app, H, user_of, who, _uid, lambda u: bool(u.get("teacher")))


# ---------------------------------------------------------------- 工程任务单（第 11 轮《机械设计》2.7（5））
from hub import tasks as _tasks  # noqa: E402
_tasks.mount(app, H, user_of, who, _uid, _emit_as)


# ---------------------------------------------------------------- 设计软件接口（学习平台第 41 轮缝纫机设计软件、第 39 轮问渠凸轮提交 CAE 计算）
try:                                       # 只在问渠这边（见 SYNC.md），另一边没有这个文件
    from hub import design_sw_api as _design_sw  # noqa: E402
    _design_sw.mount(app)
except ImportError:
    pass


# ---------------------------------------------------------------- 企业功能（第 30 轮 H-8）：freecad-ai-parts 独有的 hub/enterprise_api.py
# （企业账号、CAD 方案、选型零件库、新产品进工厂、浮动席位）有就挂上；问渠这边没有这个文件
import importlib.util  # noqa: E402
if importlib.util.find_spec("hub.enterprise_api"):
    from hub import enterprise_api as _enterprise  # noqa: E402
    _enterprise.mount(app, H, sys.modules[__name__])


# ---------------------------------------------------------------- 网页
if os.path.isdir(WEB_DIST):
    app.mount("/assets", StaticFiles(directory=os.path.join(WEB_DIST, "assets")), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        if path.startswith("api/") or path.startswith("library/"):
            return JSONResponse({"detail": "Not Found"}, 404)
        f = os.path.join(WEB_DIST, path)
        if path and os.path.isfile(f):
            return FileResponse(f)
        if path.startswith("embed/"):            # 嵌入式 3D 车间（第 4 轮 C8）：只许学习平台和本站嵌入
            anc = " ".join(["'self'"] + [o for o in os.environ.get("WQ_EMBED_ORIGINS", os.environ.get(
                "WQ_LIBRARY_ORIGINS", "")).split(",") if o.strip()] + ["http://localhost:*", "http://127.0.0.1:*"])
            return FileResponse(os.path.join(WEB_DIST, "index.html"),
                                headers={"Content-Security-Policy": "frame-ancestors " + anc, "Cache-Control": "no-cache"})
        return FileResponse(os.path.join(WEB_DIST, "index.html"))

