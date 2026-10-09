# -*- coding: utf-8 -*-
"""帮助的操作视频（第 30 轮 H-4；做法同 freecad-ai-parts ADR-0065）：用浏览器自动化在真实系统里操作一遍并录下来。

字幕、片头、光标都画在页面里，直接录进画面；不配音。界面改了重录即可。
教学版在本地版（factory/local/start.sh：教学模式、演示工厂）上录；本地版当老师要老师密码（--teacher-password，
缺省取环境变量 WQ_TEACHER_PASSWORD，CI 从 factory/digital/.env 读）。

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
    box-shadow:0 8px 24px rgba(0,0,0,.25);opacity:0;transition:opacity .3s;pointer-events:none}
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


# ---------------------------------------------------------------- 剧本：教学版（本地版、演示工厂、教学模式）
# 前 7 段沿用 freecad-ai-parts 的剧本（ADR-0065），按这边的界面改了几句字幕；后 3 段是这边新加的（factory/digital/docs/帮助编写/_videos.md）
async def teach_login(r):
    await r.go("/login", 600)
    await r.title("登录、选角色、两种模式", "填名字、选角色、选模式，三步进工厂")
    await r.cap("填你的名字：名字就是你的成绩账号，每次用同一个名字登录", 1200)
    await r.fill("#n", "王小明")
    if await r.has("#t"):
        await r.point("#t")
        await r.cap("学生不勾这一项；老师勾“我是老师”、输老师密码，才能当厂长、用教师控制台", 3500)
    await r.cap("选一个岗位：计划员、操作工、质检员、维修工……", 1200)
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
    await r.title("派工与报工", "操作工在车间终端对派来的工序点“开工”")
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
        if await r.has("[data-help=ont-options]", 4000):
            await r.point("[data-help=ont-options]")
            await r.cap("右栏下方是推演与建议：每个方案的交期和花费，第一个标“建议”", 4000)
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
    await r.fill("aside input[aria-label='问 AI 工厂助手']", "本周瓶颈在哪？")
    await r.pg.keyboard.press("Enter")
    await r.pg.wait_for_timeout(5000)
    await r.cap("回答来自统一数据总线和历史库，结论后面的编号就是依据，点开能看原始记录", 4500)
    await r.cap("它起草的订单、请购都是“提议”，要你确认才生效", 3500)


async def teach_labs(r):
    await r.go("/labs", 2000)
    await r.title("实验与任务", "一个入口：选实验、做任务、看得分")
    await r.point("[data-help=labs-grid]")
    await r.cap("左栏“教学 → 实验与任务”：实验 7、15–23 每个一张卡片", 3500)
    await r.point("[data-help=labs-grid] .lab .sc")
    await r.cap("每张卡片：领域、学时、任务数，自动评的得分和报告分", 3500)
    if await r.has("[data-help=labs-grid] .lab a:has-text('指导书')"):
        await r.point("[data-help=labs-grid] .lab a:has-text('指导书')")
        await r.cap("指导书在这里直接下载", 2500)
    await r.click("a.lab:has-text('实验 18')", 2000)
    await r.point("[data-help=lab-links]")
    await r.cap("实验页顶上：指导书、报告模板", 3000)
    await r.point("[data-help=lab-sum]")
    await r.cap("得分条：平台按事实自动评 60 分，报告 40 分由老师批", 3500)
    if await r.has("h2:has-text('老师：设置')"):
        await r.point("h2:has-text('老师：设置')")
        await r.cap("老师在这里设置情景，学生看不到；下面是全班得分表", 3500)
    await r.point("[data-help=lab-task]")
    await r.cap("任务一个一个做：读说明和提示，填表提交，马上给分", 3500)
    await r.cap("学生先自己选方案、提交；提交之前，指挥台不显示中枢的建议——这叫比对模式", 4000)
    if await r.has("a:has-text('打开这台设备的异常')"):
        await r.click("a:has-text('打开这台设备的异常')", 2500)
        await r.cap("提交以后，到指挥台和中枢的建议对比", 3500)


async def _wait_for(r, sel, seconds, every=2000):
    for _ in range(max(1, int(seconds * 1000 / every))):
        if await r.has(sel, every):
            return True
    return False


async def teach_maint(r):
    # 准备（不录进画面也行）：可靠性“正常”、GRD-01 自上次保养运行 650 小时（保养周期 500）——等于老师在实验 18 页“设置”
    await r.api("/lab18/inject", {"factor": 1, "unit": "grd-01", "hours": 650})
    await r.go("/maint", 2000)
    await r.title("设备维护", "保养工单、挂牌上锁、另一个人验收解锁")
    await r.point("[data-help=maint-kpis]")
    await r.cap("上方：保养逾期、维修单、故障停机、平均故障间隔、点检异常", 3500)
    await r.point("[data-help=maint-assets]")
    await r.cap("设备台账：自上次保养运行了多少小时、保养周期、坏的概率、预期损失", 4000)
    row = "[data-help=maint-assets] tr:has-text('GRD-01')"
    if await r.has(row + " button:has-text('详情')"):
        await r.click(row + " button:has-text('详情')", 1500)
        if await r.has("svg.curve"):
            await r.point("svg.curve")
            await r.cap("失效率曲线：越过保养周期，坏的概率涨得越快", 4000)
    await r.go("/ont?view=anomalies", 2000)
    item = "[data-help=ont-list] li:has-text('保养逾期')"
    if not await _wait_for(r, item, 60):
        await r.cap("厂情中枢几十秒内会报“保养逾期”（这次没等到，换个时间再看）", 3500)
        return
    await r.click(item, 2500)
    await r.cap("厂情中枢报“保养逾期”，因果链连到排在磨床上的工单和订单", 4000)
    if not await r.has("[data-help=ont-options]", 8000):
        return
    await r.point("[data-help=ont-options]")
    await r.cap("三个方案：不做、现在保养、下班后保养；每个算交期和“花费 + 预期损失”", 4500)
    adopt = "[data-help=ont-options] .opt:has-text('现在保养') button:has-text('采纳，生成动作')"
    if not await r.has(adopt, 15000):
        return
    await r.click(adopt, 2000)
    await r.cap("采纳，生成保养工单；要厂长批准", 3000)
    await r.go("/ont/actions", 2000)
    if await r.has("button:has-text('批准并执行')"):
        await r.click("button:has-text('批准并执行')", 2000)
        await r.cap("批准后，到时间设备挂牌上锁停下", 3000)
    await r.go("/maint", 1500)
    for _ in range(10):
        if await r.has(row + ":has-text('🔒')", 1000):
            await r.point(row)
            await r.cap("设备显示 🔒：车间终端不能复位", 3500)
            break
        await r.pg.wait_for_timeout(2000)
        await r.pg.reload(wait_until="networkidle")
    await r.go("/maint?tab=pm", 1500)
    await r.point("[data-help=maint-pm]")
    if await r.has("[data-help=maint-pm] button:has-text('保养完成')"):
        await r.click("[data-help=maint-pm] button:has-text('保养完成')", 2000)
        await r.cap("维修工做完点“保养完成”", 3000)
    if await r.has("[data-help=maint-pm] button:has-text('验收解锁')", 3000):
        await r.point("[data-help=maint-pm] button:has-text('验收解锁')")
        await r.cap("另一个人点“验收解锁”：做活的人、申请这把锁的人不能自己解锁", 4000)
        await r.click("[data-help=maint-pm] button:has-text('验收解锁')", 2000)
        if await r.has("text=不能自己", 1500):
            await r.cap("要换一个人来验收", 3000)
        else:
            await r.cap("设备恢复，“自上次保养”回到 0，ERPNext 多一条保养记录", 4000)


async def teach_maint_after(r):
    await r.api("/lab18/inject", {"factor": 0, "hours": 0})          # 收尾：可靠性设回“关”


async def teach_director(r):
    # 会重置教学模式的车间历史和情景：排在其他教学版视频最后录（ORDER_LAST）
    await r.go("/director", 2000)
    await r.title("情景导演", "一张急单串起七个领域：八幕、复盘、教师控制台")
    await r.point("[data-help=dir-timeline]")
    await r.cap("八幕的时间线：每一幕的旁白、讲解要点、去看的页面、谁处理", 4000)
    sp = "[data-help=dir-bar] select[aria-label='车间倍速']"
    await r.point(sp)
    await r.pg.locator(sp).select_option("30")
    await r.cap("先选倍速：课堂 20–30×，演示 30–60×", 2500)
    wrap = "[data-help=dir-bar] label:has-text('自动收尾') input"
    await r.point("[data-help=dir-bar] label:has-text('自动收尾')")
    if not await r.pg.locator(wrap).is_checked():
        await r.pg.locator(wrap).check()
    await r.cap("勾“自动收尾”：整改、保养到时没人收尾，由情景里的人做完", 3500)
    await r.click("button:has-text('开始两周情景'), button:has-text('重新开始')", 1000)
    await r.cap("开始：清空教学模式的车间历史、重新载入情景；学生得分保留", 3000)
    nxt = "button:has-text('下一幕'):enabled"
    await r.cap("载入中，十几秒", 500)
    if not await _wait_for(r, nxt, 40):
        return
    await r.cap("", 300)
    await r.click(nxt, 1000)
    await r.cap("第 1 幕：客户下急单，订单、工单、请购单进 ERPNext", 4000)
    if not await _wait_for(r, nxt, 40):
        return
    await r.click(nxt, 1000)
    await r.cap("第 2 幕：缺料。厂情中枢 20 秒内报出异常", 3000)
    link = "[data-help=dir-timeline] .seen .pill a"
    if await _wait_for(r, link, 60):
        await r.point(link)
        await r.cap("点异常名，直接打开指挥台", 3000)
        await r.click(link, 2500)
        if await r.has("[data-help=ont-options]", 8000):
            await r.point("[data-help=ont-options]")
            await r.cap("学生在这里比较方案、采纳生成动作；老师在动作收件箱批准", 4000)
        await r.go("/director", 2000)
    await r.point("button:has-text('复盘')")
    await r.cap("订单做完后点“复盘”：毛利分解、每一幕花的钱、跨领域因果链", 4000)
    await r.point("[data-help=dir-bar] label:has-text('自动演示')")
    await r.cap("演示时勾“自动演示”：异常出来后停一会儿自动进下一幕", 3500)
    await r.scroll("[data-help=dir-console]")
    await r.point("[data-help=dir-console]")
    await r.cap("页面最下面是教师控制台：倍速、注入故障、车间班次、重置实验 7 情景", 4000)


async def teach_director_after(r):
    if await r.has("button:has-text('结束')", 1000):     # 不要留着情景在跑
        await r.pg.locator("button:has-text('结束')").first.click()
        await r.pg.wait_for_timeout(1500)


# ---------------------------------------------------------------- 剧本：企业版（这边只有 AI 设置；账号、新产品进工厂是那边的企业功能）
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
    "teach-anomaly": teach_anomaly, "teach-8d": teach_8d, "teach-ai": teach_ai,
    "teach-labs": teach_labs, "teach-director": teach_director, "teach-maint": teach_maint,
    "ent-ai": ent_ai,
}
AFTER = {"teach-maint": teach_maint_after, "teach-director": teach_director_after}   # 录完的收尾（录失败也做）
ROLE = {"teach-order": "planner", "teach-dispatch": "operator", "teach-8d": "quality"}   # 学生岗位；其余用厂长（老师）
ORDER_LAST = ("teach-director",)       # 会重置情景，放最后


def _api(hub, path, body, ctx, token=None):
    headers = {"content-type": "application/json", **({"x-wq-token": token} if token else {})}
    req = urllib.request.Request(hub.rstrip("/") + "/api" + path, data=json.dumps(body).encode(), headers=headers)
    return json.loads(urllib.request.urlopen(req, timeout=60, context=ctx).read())


def _login(args, name, ctx):
    if args.edition == "enterprise":
        return _api(args.hub, "/login", {"username": args.user, "password": args.password, "role": "manager", "mode": "prod"}, ctx)
    role = ROLE.get(name, "manager")
    body = {"name": "帮助视频", "role": role, "mode": "teach"}
    if role == "manager" and args.teacher_password:        # 本地版：当老师要老师密码
        body["teacher_password"] = args.teacher_password
    return _api(args.hub, "/login", body, ctx)


def order(names):
    return [n for n in names if n not in ORDER_LAST] + [n for n in names if n in ORDER_LAST]


async def record(args):
    from playwright.async_api import async_playwright

    with open(MANIFEST, encoding="utf-8") as f:
        manifest = json.load(f)
    names = order([n for n, v in manifest.items() if v["edition"] == args.edition and (not args.only or n in args.only)])
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
            context = None
            try:
                tok = _login(args, name, ctx)
                context = await browser.new_context(viewport={"width": W, "height": H}, record_video_dir=tmp,
                                                    record_video_size={"width": W, "height": H}, locale="zh-CN",
                                                    ignore_https_errors=bool(args.cafile))
                await context.add_init_script(OVERLAY)
                if name != "teach-login":
                    await context.add_init_script("localStorage.setItem('wq-df-session', JSON.stringify(%s));"
                                                  % json.dumps({"token": tok["token"], "user": tok["user"]}))
                page = await context.new_page()
                page.on("dialog", lambda d: asyncio.ensure_future(d.accept()))      # “开始”“结束”会弹确认框
                rec = Rec(page, args.hub, args.edition)
                rec.api = lambda path, body, _t=tok["token"]: asyncio.to_thread(_api, args.hub, path, body, ctx, _t)
                try:
                    await SCRIPTS[name](rec)
                    await page.evaluate("() => window.__hv && window.__hv.cap('')")
                    await page.wait_for_timeout(600)
                finally:
                    if name in AFTER:
                        try:
                            await AFTER[name](rec)
                        except Exception as e:  # noqa: BLE001
                            print("收尾没做完：{}：{}".format(name, e), file=sys.stderr, flush=True)
                video = page.video
                await context.close()
                context = None
                shutil.move(await video.path(), os.path.join(args.out, name + ".webm"))
                size = os.path.getsize(os.path.join(args.out, name + ".webm")) / 1e6
                print("已录：{}（{:.0f} 秒，{:.1f} MB）".format(name, time.time() - t0, size), flush=True)
            except Exception as e:  # noqa: BLE001 —— 一段失败不影响别的，最后汇总
                failed.append(name)
                print("没录成：{}：{}".format(name, e), file=sys.stderr, flush=True)
                if context is not None:
                    await context.close()
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
        await browser.close()
    return failed


def main(argv=None):
    ap = argparse.ArgumentParser(description="录帮助的操作视频（第 30 轮 H-4）")
    ap.add_argument("--hub", required=True)
    ap.add_argument("--edition", choices=("teach", "enterprise"), required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--teacher-password", default=os.environ.get("WQ_TEACHER_PASSWORD"),
                    help="本地版的老师密码（factory/digital/.env 的 WQ_TEACHER_PASSWORD）")
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
