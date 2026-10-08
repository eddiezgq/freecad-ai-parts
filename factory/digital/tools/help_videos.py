# -*- coding: utf-8 -*-
"""帮助的操作视频（本仓库 ADR-0065）：用浏览器自动化在真实系统里操作一遍并录下来。

字幕、片头、光标都画在页面里，直接录进画面；不配音。界面改了重录即可。

    python factory/digital/tools/help_videos.py --hub http://localhost:8100 --edition teach --out help-media
    python factory/digital/tools/help_videos.py --hub https://factory.example.com --edition enterprise \
        --user admin --password ... --cafile root.crt --out help-media

要 playwright（pip install playwright==1.55.0；python -m playwright install chromium，或 --chrome 指定浏览器）。
每段视频的“剧本”在下面的 SCRIPTS 里；名字与 web/src/help/videos.json 一致。哪段录失败了会列出来，退出码 1。
"""
import argparse
import asyncio
import json
import os
import shutil
import ssl
import sys
import tempfile
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
MANIFEST = os.path.join(os.path.dirname(HERE), "web", "src", "help", "videos.json")
W, H = 1280, 720

OVERLAY = r"""
(() => {
  if (window.__hv) return;
  const css = `
  #hv-cap{position:fixed;left:50%;bottom:24px;transform:translateX(-50%);max-width:88%;z-index:99999;padding:12px 22px;border-radius:10px;
    background:rgba(23,33,43,.92);color:#fff;font:600 30px/1.45 "Noto Sans SC","PingFang SC",sans-serif;text-align:center;
    box-shadow:0 8px 24px rgba(0,0,0,.25);opacity:0;transition:opacity .3s}
  #hv-cap.on{opacity:1}
  #hv-cur{position:fixed;left:0;top:0;width:22px;height:22px;margin:-11px 0 0 -11px;border-radius:50%;z-index:100000;pointer-events:none;
    background:rgba(242,183,5,.85);border:2px solid #17212B;transition:left .6s ease,top .6s ease,transform .15s}
  #hv-cur.down{transform:scale(.7)}
  #hv-title{position:fixed;inset:0;z-index:100001;background:#17212B;color:#F4F6F3;display:flex;flex-direction:column;justify-content:center;
    padding:0 120px;font-family:"Noto Sans SC","PingFang SC",sans-serif;transition:opacity .4s}
  #hv-title b{font-size:52px;line-height:1.2}
  #hv-title span{font-size:24px;color:#C9D3DA;margin-top:16px}
  #hv-title i{font-style:normal;color:#F2B705;font-size:20px;margin-bottom:18px}`;
  const add = () => {
    const st = document.createElement('style'); st.textContent = css; document.head.appendChild(st);
    for (const id of ['hv-cap', 'hv-cur']) { const d = document.createElement('div'); d.id = id; document.body.appendChild(d); }
    const s = JSON.parse(sessionStorage.getItem('hv') || '{}');
    if (s.cap) { const c = document.getElementById('hv-cap'); c.textContent = s.cap; c.classList.add('on'); }
    if (s.x !== undefined) { const c = document.getElementById('hv-cur'); c.style.transition = 'none'; c.style.left = s.x + 'px'; c.style.top = s.y + 'px'; }
  };
  const save = (k, v) => { const s = JSON.parse(sessionStorage.getItem('hv') || '{}'); s[k] = v; sessionStorage.setItem('hv', JSON.stringify(s)); };
  window.__hv = {
    cap(t) { const c = document.getElementById('hv-cap'); if (!c) return; c.textContent = t || ''; c.classList.toggle('on', !!t); save('cap', t || ''); },
    move(x, y) { const c = document.getElementById('hv-cur'); if (!c) return; c.style.transition = ''; c.style.left = x + 'px'; c.style.top = y + 'px'; save('x', x); save('y', y); },
    press(on) { document.getElementById('hv-cur')?.classList.toggle('down', on); },
    title(t, sub, edition) {
      let d = document.getElementById('hv-title');
      if (!d) { d = document.createElement('div'); d.id = 'hv-title'; document.body.appendChild(d); }
      d.innerHTML = `<i>问渠数字工厂 · ${edition}</i><b></b><span></span>`;
      d.querySelector('b').textContent = t; d.querySelector('span').textContent = sub || '';
      d.style.opacity = '1';
    },
    untitle() { const d = document.getElementById('hv-title'); if (d) { d.style.opacity = '0'; setTimeout(() => d.remove(), 450); } },
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', add); else add();
})();
"""


class Rec:
    """一段视频的录制助手：字幕、点击（光标先移过去）、填表、等待。"""

    def __init__(self, page, hub, edition):
        self.pg, self.hub, self.ed = page, hub.rstrip("/"), edition

    async def go(self, path, wait=1500):
        await self.pg.goto(self.hub + path, wait_until="networkidle")
        await self.pg.wait_for_timeout(wait)

    async def cap(self, text, ms=3000):
        await self.pg.evaluate("t => window.__hv && window.__hv.cap(t)", text)
        await self.pg.wait_for_timeout(ms)

    async def title(self, text, sub="", ms=2400):
        await self.pg.evaluate("([t, s, e]) => window.__hv.title(t, s, e)", [text, sub, "教学版" if self.ed == "teach" else "企业版"])
        await self.pg.wait_for_timeout(ms)
        await self.pg.evaluate("() => window.__hv.untitle()")
        await self.pg.wait_for_timeout(500)

    async def point(self, sel, ms=700):
        el = self.pg.locator(sel).first
        await el.scroll_into_view_if_needed()
        b = await el.bounding_box()
        if b:
            await self.pg.evaluate("([x, y]) => window.__hv.move(x, y)", [b["x"] + b["width"] / 2, b["y"] + b["height"] / 2])
            await self.pg.wait_for_timeout(ms)
        return el

    async def click(self, sel, wait=1200):
        el = await self.point(sel)
        await self.pg.evaluate("() => window.__hv.press(true)")
        await el.click()
        await self.pg.evaluate("() => window.__hv.press(false)")
        await self.pg.wait_for_timeout(wait)

    async def fill(self, sel, value, wait=600):
        el = await self.point(sel)
        await el.fill("")
        await el.type(str(value), delay=60)
        await self.pg.wait_for_timeout(wait)

    async def has(self, sel, timeout=1500):
        try:
            await self.pg.locator(sel).first.wait_for(state="visible", timeout=timeout)
            return True
        except Exception:  # noqa: BLE001
            return False

    async def scroll(self, sel):
        await self.pg.locator(sel).first.scroll_into_view_if_needed()
        await self.pg.wait_for_timeout(800)


# ---------------------------------------------------------------- 剧本：教学版（演示工厂、教学模式）
async def teach_login(r):
    await r.go("/login", 600)
    await r.title("登录、选角色、两种模式", "填名字、选角色、选模式，三步进工厂")
    await r.cap("填你的名字：名字就是你的成绩账号，每次用同一个名字登录", 1200)
    await r.fill("#n", "王小明")
    await r.cap("选一个岗位：计划员、工艺员、操作工、质检员", 1200)
    await r.click("button:has-text('计划员')")
    await r.cap("教学模式：有实验任务、提示和评分，机床是仿真的", 1500)
    await r.click("button:has-text('教学模式')")
    await r.click("button:has-text('进入工厂')", 2500)
    await r.cap("进来就是首页：AI 简报、关键指标、车间实况、订单与交期", 3500)
    await r.point(".modes")
    await r.cap("顶栏随时换模式、换角色", 2500)
    await r.point("a.nav:has-text('帮助')")
    await r.cap("不会用？左栏“帮助”里一步一步带你做", 3000)


async def teach_order(r):
    await r.go("/work/planner")
    await r.title("接单与 MRP", "填订单、算料、提交、确认、下达车间")
    await r.cap("计划员在“新建订单”里填客户、产品、数量、交期", 2500)
    await r.fill("[data-help=planner-qty] input", 12)
    await r.cap("点“算料”：按 BOM 展开，扣掉库存和在途，这一步不写任何东西", 1200)
    await r.click("[data-help=planner-calc]", 2500)
    await r.scroll("text=算料结果")
    await r.cap("有底色的行就是有净需求的：要请购，或者要下工单", 3500)
    if await r.has("button:has-text('提交')"):
        await r.cap("看清楚后提交：生成一条“提议”，要人确认才写进 ERPNext", 1500)
        await r.click("button:has-text('提交')", 2000)
        if await r.has("button:has-text('确认执行')", 3000):
            await r.click("button:has-text('确认执行')", 3000)
            await r.cap("确认后，桥接把销售订单、工单、请购单写进 ERPNext", 3000)
    await r.scroll("[data-help=planner-wos]")
    await r.cap("工单表里点“下达车间”，工单按工艺路线逐道派给设备", 3500)


async def teach_dispatch(r):
    await r.go("/work/operator", 2500)
    await r.title("派工与开工", "操作工在车间终端对派来的工序点“开工”")
    await r.point("[data-help=op-units]")
    await r.cap("先选你的工位，圆点颜色就是设备此刻的状态", 3000)
    await r.point("[data-help=op-now]")
    await r.cap("这里是设备正在做的：工单、工序、零件、完成件数、主轴转速", 3500)
    await r.point("[data-help=op-jobs]")
    if await r.has("button.btn.primary.big:has-text('开工')"):
        await r.cap("派到本工位的工序：点“开工”，设备开始加工", 1500)
        await r.click("button.btn.primary.big:has-text('开工')", 2500)
        await r.cap("开工后，状态、进度、件数都实时更新，并发到统一数据总线", 3500)
    else:
        await r.cap("没有派工就没有“开工”按钮：先由计划员把工单下达车间", 3500)


async def teach_3d(r):
    await r.go("/3d", 4000)
    await r.title("3D 车间", "设备、物流小车、状态都是实时的")
    await r.cap("每台设备顶上的灯是它此刻的状态：绿运行、灰空闲、黄调整、红停机", 3500)
    box = await r.pg.locator("[data-help=\"3d-scene\"]").bounding_box()
    if box:
        cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        await r.cap("拖动旋转", 600)
        await r.pg.mouse.move(cx, cy)
        await r.pg.mouse.down()
        for i in range(30):
            await r.pg.mouse.move(cx + i * 8, cy + i * 2)
            await r.pg.wait_for_timeout(40)
        await r.pg.mouse.up()
        await r.cap("滚轮缩放", 600)
        for _ in range(6):
            await r.pg.mouse.wheel(0, -200)
            await r.pg.wait_for_timeout(150)
    await r.cap("点一台设备，右边显示它在做的工单、刀具寿命，还能回放刀路", 3500)


async def teach_publish(r):
    await r.go("/cad", 1500)
    await r.title("从 FreeCAD 到工厂", "方案发布到工厂，再转为生产物料")
    await r.point("[data-help=cad-list]")
    await r.cap("在 FreeCAD 的 AI Parts 工作台“发布到工厂”的方案，都在这里", 3000)
    if await r.has("[data-help=cad-list] tbody tr"):
        await r.click("[data-help=cad-list] tbody tr", 1500)
        await r.cap("BOM 里每个零件都来自零件库，带资料出处和校验结论", 3500)
        await r.scroll("[data-help=cad-production]")
        await r.cap("填外购件的采购提前期和单价；不知道就空着，系统标“交期待确认”", 3500)
        await r.point("button:has-text('转为生产物料')")
        await r.cap("点“转为生产物料”：确认后在 ERPNext 建物料、工艺路线和 BOM", 3500)


async def teach_anomaly(r):
    await r.go("/ont?view=anomalies", 2500)
    await r.title("厂情中枢：追因与推演", "发现异常、找原因、算影响、比较处理办法")
    await r.point("[data-help=ont-list]")
    await r.cap("规则每 20 秒看一遍全厂，开着的异常列在左边", 3000)
    if await r.has("[data-help=ont-list] li"):
        await r.click("[data-help=ont-list] li", 2500)
        await r.point("[data-help=ont-chain]")
        await r.cap("中间是因果链：往前是原因，往后是影响，每一环都有依据", 4000)
        await r.point("[data-help=ont-actions]")
        await r.cap("右边处理：确认、开始处理，或者先去推演", 3000)
    await r.go("/ont/sim", 2500)
    await r.cap("推演工作台：在快进副本里试几种办法，比较结果再决定", 4000)


async def teach_8d(r):
    await r.go("/work/quality", 2500)
    await r.title("质量异常单（8D）", "从控制图发现问题，到措施验证、关闭")
    await r.point("[data-help=q-chart]")
    await r.cap("控制图：每个点是一件零件；连续上升、靠近公差线就要处理", 4000)
    await r.point("[data-help=q-8d]")
    await r.cap("发现异常，为这个特性开一张质量异常单，按 D1–D8 填写", 3500)
    await r.go("/quality/8d", 2000)
    await r.cap("D5 选纠正措施；批准后下发车间，只有对症的措施能让问题消失", 4000)
    await r.cap("再做 10 件后验证：全部合格且 Cpk ≥ 1.33 才算有效", 3500)


async def teach_ai(r):
    await r.go("/", 2500)
    await r.title("AI 工厂助手", "能看全厂数据、注明出处；只起草，不替你做决定")
    await r.click("a.nav:has-text('AI 工厂助手')", 1000)
    await r.cap("问它：哪张订单会延期？本周瓶颈在哪？", 1500)
    await r.fill("input[aria-label='问 AI 工厂助手']", "本周瓶颈在哪？")
    await r.pg.keyboard.press("Enter")
    await r.pg.wait_for_timeout(5000)
    await r.cap("回答来自统一数据总线和历史库，结论后面的编号就是依据，点开能看原始记录", 4500)
    await r.cap("它起草的订单、请购都是“提议”，要你确认才生效", 3500)


# ---------------------------------------------------------------- 剧本：企业版（企业账号、工厂清单）
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


async def ent_ai(r):
    await r.go("/ont/ai", 2500)
    await r.title("AI 设置", "国内自动用 DeepSeek，其他地方用 Claude")
    if await r.has("[data-help=ai-model]"):
        await r.point("[data-help=ai-model]")
        await r.cap("“自动”按服务器所在地区选；也可以固定用一家", 4000)
        await r.cap("两家都配了密钥时，一家出错自动换另一家，这里显示上次实际用的是哪家", 4000)
    await r.cap("每次 AI 回答都记在这里：问了什么、查了哪些数据、用的哪家模型", 4000)


SCRIPTS = {
    "teach-login": teach_login, "teach-order": teach_order, "teach-dispatch": teach_dispatch, "teach-3d": teach_3d,
    "teach-publish": teach_publish, "teach-anomaly": teach_anomaly, "teach-8d": teach_8d, "teach-ai": teach_ai,
    "ent-accounts": ent_accounts, "ent-new-product": ent_new_product, "ent-ai": ent_ai,
}
ROLE = {"teach-order": "planner", "teach-dispatch": "operator", "teach-8d": "quality", "teach-publish": "engineer"}


def _api(hub, path, body, ctx):
    req = urllib.request.Request(hub.rstrip("/") + "/api" + path, data=json.dumps(body).encode(),
                                 headers={"content-type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=30, context=ctx).read())


async def record(args):
    from playwright.async_api import async_playwright

    with open(MANIFEST, encoding="utf-8") as f:
        manifest = json.load(f)
    names = [n for n, v in manifest.items() if v["edition"] == args.edition and (not args.only or n in args.only)]
    missing = [n for n in names if n not in SCRIPTS]
    if missing:
        raise SystemExit("清单里这些视频没有剧本：" + "、".join(missing))
    ctx = ssl.create_default_context(cafile=args.cafile) if args.cafile else None
    os.makedirs(args.out, exist_ok=True)
    failed = []
    async with async_playwright() as p:
        launch = {"args": ["--use-gl=swiftshader", "--enable-webgl", "--ignore-gpu-blocklist", "--lang=zh-CN"]}
        if args.chrome:
            launch["executable_path"] = args.chrome
        browser = await p.chromium.launch(**launch)
        for name in names:
            tmp = tempfile.mkdtemp(prefix="hv-")
            t0 = time.time()
            try:
                if args.edition == "enterprise":
                    tok = _api(args.hub, "/login", {"username": args.user, "password": args.password,
                                                    "role": "manager", "mode": "prod"}, ctx)
                else:
                    tok = _api(args.hub, "/login", {"name": "帮助视频", "role": ROLE.get(name, "manager"), "mode": "teach"}, ctx)
                context = await browser.new_context(viewport={"width": W, "height": H}, record_video_dir=tmp,
                                                    record_video_size={"width": W, "height": H}, locale="zh-CN",
                                                    ignore_https_errors=bool(args.cafile))
                await context.add_init_script(OVERLAY)
                if name != "teach-login":
                    await context.add_init_script("localStorage.setItem('wq-df-session', JSON.stringify(%s));"
                                                  % json.dumps({"token": tok["token"], "user": tok["user"]}))
                page = await context.new_page()
                await SCRIPTS[name](Rec(page, args.hub, args.edition))
                await page.evaluate("() => window.__hv && window.__hv.cap('')")
                await page.wait_for_timeout(600)
                video = page.video
                await context.close()
                shutil.move(await video.path(), os.path.join(args.out, name + ".webm"))
                size = os.path.getsize(os.path.join(args.out, name + ".webm")) / 1e6
                print("已录：{}（{:.0f} 秒，{:.1f} MB）".format(name, time.time() - t0, size), flush=True)
            except Exception as e:  # noqa: BLE001 —— 一段失败不影响别的，最后汇总
                failed.append(name)
                print("没录成：{}：{}".format(name, e), file=sys.stderr, flush=True)
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
        await browser.close()
    return failed


def main(argv=None):
    ap = argparse.ArgumentParser(description="录帮助的操作视频（ADR-0065）")
    ap.add_argument("--hub", required=True)
    ap.add_argument("--edition", choices=("teach", "enterprise"), required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--user", default=os.environ.get("FAP_FACTORY_USER"))
    ap.add_argument("--password", default=os.environ.get("FAP_FACTORY_PASSWORD"))
    ap.add_argument("--cafile", default=os.environ.get("FAP_FACTORY_CAFILE"))
    ap.add_argument("--chrome", default=os.environ.get("FAP_CHROME"), help="用这个 Chromium（不用 playwright 自带的）")
    ap.add_argument("--only", nargs="*", help="只录这几段")
    a = ap.parse_args(argv)
    if a.edition == "enterprise" and not (a.user and a.password):
        ap.error("企业版要 --user 和 --password（或环境变量 FAP_FACTORY_USER / FAP_FACTORY_PASSWORD）")
    failed = asyncio.run(record(a))
    if failed:
        print("没录成的：" + "、".join(failed), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
