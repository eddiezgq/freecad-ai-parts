# -*- coding: utf-8 -*-
"""企业功能的帮助视频剧本（ADR-0065、ADR-0068）：只在本仓库（factory/SYNC.md）。

共有的 tools/help_videos.py 有这个文件就把这里的 SCRIPTS、ROLE 并进去；清单在 web/src/help/extra.json 的 videos。
剧本只用传进来的录制助手 r（help_videos.Rec）。"""
import time


async def ent_accounts(r):
    await r.go("/accounts", 2000)
    await r.title("开账号、分角色", "管理员给每个人开账号，只给他岗位要用的角色")
    await r.point("[data-help=acct-new]")
    await r.cap("填用户名、姓名、初始密码（至少 10 位，字母加数字）", 1500)
    stamp = time.strftime("%H%M%S")
    await r.fill("[data-help=acct-new] input[placeholder^='用户名']", "planner" + stamp)
    await r.fill("[data-help=acct-new] input[placeholder='姓名']", "计划员小李")
    await r.fill("[data-help=acct-new] input[type=password]", "Planner-pass-2026")
    await r.cap("勾选他能用的角色", 1000)
    await r.click("[data-help=acct-new] label:has-text('计划员')", 800)
    await r.click("[data-help=acct-new] button:has-text('开账号')", 2000)
    await r.point("[data-help=acct-table]")
    await r.cap("账号都在这里：随时改角色、停用、重置密码；停用后对方立即退出", 4000)
    await r.cap("连续输错 5 次密码，账号锁 10 分钟", 3000)


async def ent_new_product(r):
    await r.go("/cad", 2000)
    await r.title("新产品进工厂", "FreeCAD 方案 → 生产物料 → 接单")
    await r.point("[data-help=cad-list]")
    await r.cap("工程师在 FreeCAD 里选型、校验，“发布到工厂”的方案都在这里", 3500)
    if await r.has("[data-help=cad-list] tbody tr"):
        await r.click("[data-help=cad-list] tbody tr", 1500)
        await r.cap("BOM、自制件、总装工艺、校验结论，一起发过来", 3500)
        await r.scroll("[data-help=cad-production]")
        await r.cap("转为生产物料：确认后在 ERPNext 建供应商、物料、工艺路线和 BOM", 4000)
    await r.go("/work/planner", 2000)
    await r.point("[data-help=planner-item]")
    await r.cap("转好的产品，计划员就能在“订单与计划”里选来下单", 4000)


SCRIPTS = {"ent-accounts": ent_accounts, "ent-new-product": ent_new_product}
ROLE = {}
