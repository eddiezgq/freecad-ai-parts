# -*- coding: utf-8 -*-
"""企业功能挂到工作台枢纽上（本仓库 ADR-0067，M19）。

数字工厂的代码与问渠仓库共有（factory/SYNC.md）；本仓库独有的企业功能都从这里挂上，共有的 hub/app.py 只留一处口子：
有 hub/enterprise_api.py 就调用 mount(app, H, 枢纽模块)。问渠那边没有这个文件，什么也不挂。

挂上的内容：
- 企业账号（ADR-0063）：WQ_AUTH=enterprise 时登录用用户名 + 密码、换角色按账号授权、凭证随账号停用或改密码失效；
  账号管理 /api/accounts、改自己的密码 /api/me/password
- FreeCAD 方案发布到工厂（ADR-0058）：/api/cad/release、/api/cad/designs
- 选型零件库（ADR-0058）：/api/fap/components
- 新产品进工厂（ADR-0061、0062）：方案转为生产物料、登记的产品、到货入库；/api/config 的可接单产品加上登记的产品
- 孪生运行记录导出给 FreeCAD（ADR-0058 第 4 条）：/api/twin/units/{serial}/records.csv
- 浮动席位（ADR-0066）：hub/seats_api.py

做法（不改共有文件）：
- 同一路径的接口（登录、换角色、/api/config）放在路由表最前面，先于共有的同名接口匹配；
- 凭证检查用 FastAPI 的 dependency_overrides 换成“先按原样验签，企业版再查账号是否还有效”；
- 启动时（数据库建表之后）建本模块的表、把登记过的产品并回主数据（包一层 H.db.init）。
"""
import logging
import time

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Request

log = logging.getLogger("hub.enterprise")


def init_db(db, auth):
    """建企业功能的表；登记过的产品并入主数据（枢纽每次启动）。"""
    from hub import cad_link, products
    cad_link.init(db)
    products.init(db)
    if auth == "enterprise":
        from hub import accounts
        accounts.init(db)


def mount(app, H, A):
    """A：共有的枢纽模块（hub.app）。用它的 _sign、check_allowed、who、_emit_as、config 等，不复制。"""
    from factory import data as F
    from hub import cad_link, fap_library, products

    enterprise = A.AUTH == "enterprise"
    orig_user_of = A.user_of

    # ------------------------------------------------------------ 启动：共有的表建好以后建本模块的表
    db = getattr(H, "db", None)
    if db is not None and not getattr(db.init, "_fap_enterprise", False):
        base_init = db.init

        def init():
            base_init()
            init_db(db, A.AUTH)
        init._fap_enterprise = True
        db.init = init

    # ------------------------------------------------------------ 企业账号（ADR-0063）
    def user_of(x_wq_token: str = Header(default="")):
        u = orig_user_of(x_wq_token)
        if enterprise:                     # 账号在用、密码没改过，凭证才有效
            from hub import accounts
            if not u.get("acct") or not accounts.still_valid(H.db, u["acct"], u.get("pw_ver")):
                raise HTTPException(401, "登录已失效，请重新登录")
        return u

    if enterprise:
        app.dependency_overrides[orig_user_of] = user_of
        A.user_of = user_of                # 共有代码里直接调用的地方（ERPNext 单点登录）也走这里

    first = APIRouter()                    # 与共有接口同路径、要先匹配的
    r = APIRouter()

    def acct_roles(username):
        from hub import accounts
        a = accounts.get(H.db, username)
        return list(a["roles"]) if a else None

    if enterprise:
        @first.post("/api/login")
        def login(body: dict = Body(...)):
            from hub import accounts
            try:
                a = accounts.authenticate(H.db, body.get("username"), body.get("password"))
            except accounts.AccountError as e:
                raise HTTPException(401, str(e)) from None
            member = None if a["admin"] else list(a["roles"])
            mode = body.get("mode", "prod")
            role = body.get("role") or ("manager" if a["admin"] else member[0])
            if member and role not in member:
                role = member[0]
            A.check_allowed(a["admin"], role, mode, member)
            u = {"name": a["name"], "uid": "acct:" + a["username"], "acct": a["username"], "pw_ver": a["pw_ver"],
                 "teacher": a["admin"], "role": role, "mode": mode, "exp": int(time.time() + A.TOKEN_DAYS * 86400)}
            if member:
                u["member"] = member
            return {"token": A._sign(u), "user": u}

        @first.post("/api/switch")
        def switch(body: dict = Body(...), u=Depends(user_of)):
            role = body.get("role", u["role"])
            mode = body.get("mode", u["mode"])
            member = None if u["teacher"] else acct_roles(u["acct"])        # 授权随时生效
            A.check_allowed(u["teacher"], role, mode, member)
            nu = dict(u, role=role, mode=mode)
            if member:
                nu["member"] = member
            else:
                nu.pop("member", None)
            return {"token": A._sign(nu), "user": nu}

    def acct_admin(u):
        if not enterprise:
            raise HTTPException(404, "只有企业版用账号管理")
        if not u.get("teacher"):
            raise HTTPException(403, "账号管理要用管理员账号")

    def acct_call(fn, *a, **kw):
        from hub import accounts
        try:
            return fn(H.db, *a, **kw)
        except accounts.AccountError as e:
            raise HTTPException(400, str(e)) from None

    @r.get("/api/accounts")
    def accounts_list(u=Depends(user_of)):
        acct_admin(u)
        from hub import accounts
        return {"accounts": accounts.listing(H.db), "roles": list(accounts.ROLES)}

    @r.post("/api/accounts")
    def accounts_create(body: dict = Body(...), u=Depends(user_of)):
        acct_admin(u)
        from hub import accounts
        return acct_call(accounts.create, body.get("username"), body.get("password"), name=body.get("name"),
                         roles=body.get("roles") or [], admin=bool(body.get("admin")), by=u["acct"])

    @r.post("/api/accounts/{username}")
    def accounts_update(username: str, body: dict = Body(...), u=Depends(user_of)):
        acct_admin(u)
        from hub import accounts
        if body.get("password"):
            acct_call(accounts.set_password, username, body["password"])
        return acct_call(accounts.update, username, name=body.get("name"), roles=body.get("roles"),
                         admin=body.get("admin"), active=body.get("active"), by=u["acct"])

    @r.post("/api/me/password")
    def my_password(body: dict = Body(...), u=Depends(user_of)):
        if not enterprise:
            raise HTTPException(404, "只有企业版有密码")
        from hub import accounts
        acct_call(accounts.set_password, u["acct"], body.get("new") or "", old=body.get("old") or "")
        return {"ok": True, "relogin": True}

    # ------------------------------------------------------------ 可接单的产品：演示工厂的减速器 + 登记的新产品（ADR-0061、0064）
    @first.get("/api/config")
    def config(request: Request):
        c = A.config(request)
        try:
            reg = products.products(H.db)
        except Exception as e:  # noqa: BLE001 —— 数据库还没就绪时只给共有的
            log.warning("读不到登记的产品：%s", e)
            reg = []
        fg = list(c.get("fg") or []) if (c.get("plant") or {}).get("demo", True) else []
        have = {x["item_code"] for x in fg}
        for p in reg:
            if p["code"] not in have:
                it = F.ITEMS.get(p["code"])
                fg.append({"item_code": p["code"], "name": p.get("name") or (it[0] if it else ""),
                           "price": it[3] if it else None})
        c["fg"] = fg
        return c

    # ------------------------------------------------------------ 选型零件库与 CAD 方案（ADR-0058、0061）
    @r.get("/api/fap/components")
    def fap_components(category: str = "", q: str = "", u=Depends(user_of)):
        """选型零件库：公共库叠加企业库，与 FreeCAD 选型同一份数据"""
        return {"categories": fap_library.CATEGORIES, "items": fap_library.search(category, q)}

    @r.get("/api/fap/components/{cid}")
    def fap_component(cid: str, u=Depends(user_of)):
        c = fap_library.get(cid)
        if c is None:
            raise HTTPException(404, "零件库里没有这个组件")
        return c

    @r.post("/api/cad/release")
    def cad_release(body: dict = Body(...), u=Depends(user_of)):
        """FreeCAD 选型方案发布到工厂：存新版本，发 cad.release 到总线"""
        try:
            return cad_link.release(H.db, A._emit_as(u, source="freecad"), u["mode"], A.who(u), body)
        except cad_link.CadError as e:
            raise HTTPException(422, str(e)) from None

    @r.post("/api/cad/designs/{code}/production")
    def cad_production(code: str, body: dict = Body(default={}), u=Depends(user_of)):
        """转为生产物料：预览要在 ERPNext 建的供应商、物料、BOM，生成一条需确认的提议"""
        d = cad_link.design(H.db, u["mode"], code)
        if d is None:
            raise HTTPException(404, "没有这个方案")
        try:
            spec = products.build(d, body)
        except (products.ProductError, KeyError, TypeError, ValueError) as e:
            raise HTTPException(400, str(e))
        title = "转为生产物料：{} {}（{} 种物料）".format(spec["code"], spec["name"], len(spec["items"]))
        pid = H.ai.propose("cad_to_erp", spec, u["mode"], u["name"], title, source="workbench/" + A.who(u), role=u["role"])
        return {"proposal_id": pid, "preview": spec, "title": title}

    @r.get("/api/products")
    def registered_products(u=Depends(user_of)):
        return products.products(H.db)

    @r.post("/api/purchase/receive")
    def purchase_receive(body: dict = Body(...), u=Depends(user_of)):
        """采购到货入库（演示用：供应商送货到原材料库，ERPNext 物料收货单），走需确认的提议"""
        rows = []
        for x in body.get("items") or []:
            code, qty = str(x.get("item_code") or ""), float(x.get("qty") or 0)
            if code not in F.ITEMS or qty <= 0:
                raise HTTPException(400, "物料 {} 不存在或数量不对".format(code))
            rows.append({"item_code": code, "qty": qty, "uom": F.ITEMS[code][2]})
        if not rows:
            raise HTTPException(400, "没有到货物料")
        title = "到货入库：" + "、".join("{} {:g}".format(x["item_code"], x["qty"]) for x in rows)
        pid = H.ai.propose("material_receipt", {"items": rows}, u["mode"], u["name"], title, source="workbench/" + A.who(u),
                           role=u["role"])
        return {"proposal_id": pid, "preview": {"items": rows}, "title": title}

    @r.get("/api/cad/designs")
    def cad_designs(u=Depends(user_of)):
        return cad_link.designs(H.db, u["mode"])

    @r.get("/api/cad/designs/{code}")
    def cad_design(code: str, u=Depends(user_of)):
        d = cad_link.design(H.db, u["mode"], code)
        if d is None:
            raise HTTPException(404, "没有这个方案")
        return d

    # ------------------------------------------------------------ 孪生运行记录导出给 FreeCAD 数字孪生（ADR-0058 第 4 条）
    @r.get("/api/twin/units/{serial}/records.csv")
    def twin_records_csv(serial: str, instance: str = "reducer", days: int = 365, u=Depends(user_of)):
        """每天一行：运行小时、输出平均 / 最大扭矩、输入转速。instance 为 FreeCAD 布局里这台减速器的实例名。"""
        from fastapi.responses import Response
        rows = H.db.q("select day, data from twin_log where serial=%s and mode=%s order by day desc limit %s",
                      (serial, u["mode"], max(1, min(int(days), 3650))))
        if not rows:
            raise HTTPException(404, "没有这台设备的运行记录")
        lines = ["day,instance,hours,output_torque_avg_nm,output_torque_max_nm,input_speed_rpm"]
        for x in reversed(rows):
            d = x["data"]
            if not d.get("run_h"):
                continue
            lines.append("{},{},{},{},{},{}".format(x["day"], instance, d["run_h"], d.get("torque_mean_nm") or "",
                                                    d.get("torque_max_nm") or "", d.get("n_in_rpm") or ""))
        return Response("\n".join(lines) + "\n", media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": 'attachment; filename="{}-records.csv"'.format(serial)})

    # 同一路径先匹配的放到路由表最前面；其余接在后面（都在网页的兜底路由之前挂上）
    app.include_router(first)
    n = len(first.routes)
    if n:
        moved = app.router.routes[-n:]
        del app.router.routes[-n:]
        app.router.routes[:0] = moved
    app.include_router(r)

    # ------------------------------------------------------------ 浮动席位（ADR-0066）：FreeCAD 单机安装版来租席位
    from hub import seats_api
    seats_api.mount(app)
