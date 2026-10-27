# -*- coding: utf-8 -*-
"""第 18 轮 E3 接口：设备台账与失效风险、保养、点检（二维码）、维修与备件、老师调可靠性和注入保养逾期。"""
import io

from fastapi import Body, Depends, HTTPException, Request
from fastapi.responses import Response

from hub import maint as MT
from wqbus import UNITS

MANAGE = ("maintenance", "manager")
VERIFY = ("maintenance", "manager", "safety")


def mount(app, H, user_of, who):
    def can(u, roles=MANAGE):
        return bool(u.get("teacher")) or u.get("role") in roles

    def need(u, what, roles=MANAGE):
        if not can(u, roles):
            raise HTTPException(403, "{}由维修工或厂长操作".format(what))

    def wrap(fn, *a, **k):
        try:
            return fn(*a, **k)
        except KeyError as e:
            raise HTTPException(404, "没有：{}".format(e))
        except PermissionError as e:
            raise HTTPException(403, str(e))
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.get("/api/maint/assets")
    def assets(u=Depends(user_of)):
        return {"assets": MT.assets(H.db, u["mode"]), "kpis": MT.kpis(H.db, u["mode"]), "can_manage": can(u), "horizon_h": MT.HORIZON_H}

    @app.get("/api/maint/assets/{unit}")
    def asset(unit: str, u=Depends(user_of)):
        if unit not in UNITS or not MT.REL.params(unit):
            raise HTTPException(404, "没有这台设备")
        db, mode = H.db, u["mode"]
        rk = MT.risk(db, mode, unit)
        a, mt = MT.asset_of(db, mode, unit)
        rows = lambda sql: [dict(r) for r in db.q(sql, (mode, unit))]                     # noqa: E731
        return {"unit": unit, "name": UNITS[unit][1], "risk": rk, "asset": a, "maintenance": mt, "pm_text": MT.PM_TEXT.get(unit),
                "pm_minutes": MT.pm_minutes(unit), "modes": MT.REL.params(unit)["modes"],
                "failures": rows("select id, code, name, part, at, run_h, down_min, repair_id from maint_failure where mode=%s and unit=%s order by id desc limit 30"),
                "repairs": rows("select id, title, status, parts, created_at, fixed_at, closed_at, cost, erp_repair from maint_repair where mode=%s and unit=%s order by id desc limit 30"),
                "pms": rows("select id, status, minutes, delay_minutes, run_h, created_at, fixed_at, closed_at from maint_pm where mode=%s and unit=%s order by id desc limit 30"),
                "inspections": rows("select id, by_name, at, abnormal, status from maint_inspection where mode=%s and unit=%s order by id desc limit 20"),
                "mtbf": MT.mtbf(db, mode, unit)}

    # ---------------------------------------------------------------- 点检
    @app.get("/api/maint/checklist/{unit}")
    def checklist(unit: str, u=Depends(user_of)):
        return {"unit": unit, "name": UNITS.get(unit, ("", unit))[1], "items": wrap(MT.checklist, H.db, u["mode"], unit)}

    @app.post("/api/maint/inspections")
    def inspect(body: dict = Body(...), u=Depends(user_of)):
        return wrap(MT.inspect, H.db, u["mode"], body.get("unit"), body.get("results") or [], who(u), body.get("photo_ids"), body.get("note") or "")

    @app.get("/api/maint/inspections")
    def inspections(u=Depends(user_of)):
        MT.init(H.db)
        rows = H.db.q("select * from maint_inspection where mode=%s order by id desc limit 200", (u["mode"],))
        return {"inspections": [dict(r, key="IC-{:05d}".format(r["id"]), at=r["at"].isoformat()) for r in rows], "can_manage": can(u)}

    @app.post("/api/maint/inspections/{iid}/watch")
    def inspection_watch(iid: int, u=Depends(user_of)):
        need(u, "处理点检异常")
        MT.inspection_watch(H.db, iid, who(u))
        return {"ok": True}

    @app.get("/api/maint/qr/{unit}.svg")
    def qr(unit: str, request: Request):
        """设备点检二维码（可打印，贴在设备上）：扫码打开这台设备的点检表"""
        import segno
        if unit not in UNITS:
            raise HTTPException(404, "没有这台设备")
        base = str(request.base_url).rstrip("/")
        buf = io.BytesIO()
        segno.make("{}/maint?tab=inspect&unit={}".format(base, unit), error="m").save(buf, kind="svg", scale=6, border=2)
        return Response(buf.getvalue(), media_type="image/svg+xml")

    # ---------------------------------------------------------------- 维修与保养
    @app.get("/api/maint/repairs")
    def repairs(u=Depends(user_of)):
        MT.init(H.db)
        rows = H.db.q("select * from maint_repair where mode=%s order by (status<>'closed') desc, id desc limit 200", (u["mode"],))
        pms = H.db.q("select * from maint_pm where mode=%s order by (status<>'closed') desc, id desc limit 100", (u["mode"],))
        spares = [{"item_code": k, "stock": MT.stock_of(H.db, u["mode"], k), "min": v} for k, v in MT.SPARE_MIN.items()]
        return {"repairs": [dict(r, key="MR-{:05d}".format(r["id"]), status_label=MT.STATUS[r["status"]], created_at=r["created_at"].isoformat()) for r in rows],
                "pms": [dict(r, key="PM-{:05d}".format(r["id"]), status_label=MT.PM_STATUS[r["status"]], created_at=r["created_at"].isoformat()) for r in pms],
                "spares": spares, "can_manage": can(u), "can_verify": can(u, VERIFY)}

    @app.post("/api/maint/repairs")
    def repair_new(body: dict = Body(...), u=Depends(user_of)):
        need(u, "开维修单")
        if body.get("unit") not in UNITS:
            raise HTTPException(400, "选设备")
        rid = MT.open_repair(H, u["mode"], body["unit"], "manual", (body.get("title") or "维修")[:200], body.get("parts") or [], who(u),
                             inspection_id=body.get("inspection_id"))
        return {"id": rid, "key": "MR-{:05d}".format(rid)}

    @app.post("/api/maint/repairs/{rid}/done")
    def repair_done(rid: int, body: dict = Body(default={}), u=Depends(user_of)):
        need(u, "完成维修")
        return wrap(MT.finish_repair, H, u["mode"], rid, who(u), (body.get("note") or "")[:300])

    @app.post("/api/maint/repairs/{rid}/verify")
    def repair_verify(rid: int, u=Depends(user_of)):
        need(u, "验收", VERIFY)
        return wrap(MT.verify_repair, H, u["mode"], rid, who(u))

    @app.post("/api/maint/pms/{pid}/done")
    def pm_done(pid: int, body: dict = Body(default={}), u=Depends(user_of)):
        need(u, "完成保养")
        return wrap(MT.finish_pm, H, u["mode"], pid, who(u), (body.get("note") or "")[:300])

    @app.post("/api/maint/pms/{pid}/verify")
    def pm_verify(pid: int, u=Depends(user_of)):
        need(u, "验收", VERIFY)
        return wrap(MT.verify_pm, H, u["mode"], pid, who(u))

    @app.get("/api/maint/risk/{unit}")
    def risk(unit: str, hours: float = MT.HORIZON_H, u=Depends(user_of)):
        return wrap(MT.risk, H.db, u["mode"], unit, float(hours))

    @app.get("/api/maint/kpis")
    def kpis(u=Depends(user_of)):
        return MT.kpis(H.db, u["mode"])

    # ---------------------------------------------------------------- 教学
    @app.post("/api/maint/reliability")
    def reliability(body: dict = Body(...), u=Depends(user_of)):
        if not (u.get("teacher") and u["mode"] == "teach"):
            raise HTTPException(403, "只有老师在教学模式下能调")
        f = float(body.get("factor", 1))
        if not 0 <= f <= 10:
            raise HTTPException(400, "系数 0–10")
        return MT.set_factor(H, u["mode"], f, who(u))
