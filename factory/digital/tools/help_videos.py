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


# ---------------------------------------------------------------- 第 30 轮 §八 8-4：首页和六个领域（客户、供应、人员、安全、能源、经营）
# 每段 30–60 秒；要先“出事”的，用帮助里“当场动手”同一个接口（/api/help/try/<动作>，老师 5 秒一次）
async def _try(r, name):
    try:
        return await r.api("/help/try/" + name, {})
    except Exception as e:  # noqa: BLE001 —— 没做成（比如没有未收的发票）就照常录，字幕说明
        print("当场动手没做成：{}：{}".format(name, e), file=sys.stderr, flush=True)
        return None


async def _anomaly(r, text, seconds=60):
    """到厂情中枢等这条异常出来、点开它、指一下推演与建议"""
    await r.go("/ont?view=anomalies", 2000)
    item = "[data-help=ont-list] li:has-text('{}')".format(text)
    if not await _wait_for(r, item, seconds):
        await r.cap("厂情中枢几十秒内会报出来（这次没等到，换个时间再看）", 3000)
        return False
    await r.click(item, 2500)
    await r.point("[data-help=ont-chain]")
    await r.cap("因果链：往前是原因，往后是影响；每一环都有依据", 3500)
    if await r.has("[data-help=ont-options]", 8000):
        await r.point("[data-help=ont-options]")
        await r.cap("推演与建议：每个方案算好交期和花费，第一个标“建议”", 3500)
    return True


async def teach_home(r):
    await r.go("/", 2500)
    await r.title("首页：一眼看全厂", "简报、指标、车间实况、订单、质量")
    await r.point("[data-help=home-brief]")
    await r.cap("AI 今日简报：现在最该关注的几件事，每条写着数据来源", 3500)
    await r.point("[data-help=home-kpis]")
    await r.cap("关键指标：准时交付、在制品、设备综合效率、一次合格率", 3500)
    await r.point("[data-help=home-shop]")
    await r.cap("车间实况：每台设备此刻的状态", 2500)
    await _try(r, "stop-grinder")
    await r.cap("现在让磨床停机 2 小时（帮助里“当场动手”同一个按钮）……", 5000)
    await r.point("[data-help=home-shop]")
    await r.cap("GRD-01 变红：停机。点设备卡片，弹出状态和对应的帮助", 3500)
    await r.point("[data-help=home-orders]")
    await r.cap("订单与交期：磨床是瓶颈，排在它上面的订单延期风险会变高", 4000)


async def teach_service(r):
    await r.go("/service?tab=complaints", 2000)
    await r.title("客户与服务", "投诉 → 追溯 → 召回范围 → 派工决定")
    await r.point("[data-help=svc-kpis]")
    await r.cap("上方：满意度、开着的投诉、待上门的服务、保修成本、漏斗金额", 3500)
    if await r.has("[data-help=svc-complaint] input[list=serials]"):
        await r.point("[data-help=svc-complaint]")
        await r.cap("客户来电：填设备序列号（会带出客户）、现象、严重度", 2000)
        await r.pg.locator("[data-help=svc-complaint] input[list=serials]").focus()
        opt = await r.pg.evaluate("() => (document.querySelector('#serials option') || {}).value || ''")
        if opt:
            await r.fill("[data-help=svc-complaint] input[list=serials]", opt)
            await r.fill("[data-help=svc-complaint] input[placeholder^='例如：异响']", "减速器异响，振动比以前大")
            await r.click("[data-help=svc-complaint] button:has-text('登记')", 2500)
            await r.cap("登记：同时在 ERPNext 开投诉单；20 秒内厂情中枢开异常", 3500)
    if await _anomaly(r, "客户投诉"):
        await r.cap("有序列号就能追到出厂数据：输出轴是哪片砂轮磨的，同一片砂轮还磨了哪些", 4000)
        await r.cap("方案 A 只修这一台、B 加高风险点检、C 整批排查——推荐不漏高风险里最便宜的", 4500)


async def teach_supply(r):
    await r.go("/supply?tab=inspect", 2000)
    await r.title("采购与来料", "来料检验 → 不合格 → 退货还是换供应商")
    await r.point("[data-help=sup-kpis]")
    await r.cap("上方：在途、到货待检、不合格待处理、准时率和合格率", 3500)
    await r.point("[data-help=sup-inspect]")
    await r.cap("每次到货是一个批次。点“检验”看抽样数据", 3000)
    btn = "[data-help=sup-inspect] button:has-text('检验')"
    if not await r.has(btn):
        btn = "[data-help=sup-inspect] button:has-text('看检验')"
    if await r.has(btn):
        await r.click(btn, 2000)
        await r.cap("抽 5 件，逐件对照上下限：任何一件、任何一项超差，整批不合格", 4500)
    await r.go("/supply?tab=suppliers", 2000)
    await r.cap("供应商评分卡：价格、提前期、准时率、合格率；便宜的不一定便宜", 4000)
    await r.cap("一批判不合格，厂情中枢给方案：退货等补发、向备选供应商下急单、让步接收全检", 4500)


async def teach_people(r):
    await r.go("/people?tab=roster", 2000)
    await r.title("人员与排班", "请假 → 缺人 → 调班或加班")
    await r.point("[data-help=people-kpis]")
    await r.cap("上方：出勤率、排班缺口、只有一个人会开的设备、本周加班", 3500)
    await r.point("[data-help=people-roster]")
    await r.cap("排班：每一格是这一班谁开这台设备。红没人能开，黄学徒带着开", 4000)
    cell = "[data-help=people-roster] td.c"
    if await r.has(cell):
        await r.click(cell + " >> nth=3", 1500)
        if await r.has("select[aria-label='谁来顶']"):
            await r.point("select[aria-label='谁来顶']")
            await r.cap("点一个格子换人：列出会开这台设备的人，熟练程度、本来在哪一班", 4000)
            await r.point("label:has-text('加班顶班')")
            await r.cap("调人会让他原来的格子空出来；加班顶班不动别的格子，要付加班费", 4500)
            await r.click("button:has-text('取消')", 800)
    await r.go("/people?tab=skills", 2000)
    await r.cap("技能矩阵：标红的列只有一个人会开——他一请假这台就停，要安排培训", 4500)


async def teach_ehs(r):
    await r.go("/ehs", 2000)
    await r.title("安全环保", "隐患上报 → 评估 → 停机挂牌整改 → 验收解锁")
    await r.point("[data-help=ehs-kpis]")
    await r.cap("上方：开着的隐患、整改按期率、挂牌上锁的设备、培训到期、未遂", 3500)
    await r.point("[data-help=ehs-report]")
    await r.cap("随手拍：谁都能报。选设备、种类、等级，写一句话，拍照", 3500)
    await _try(r, "major-hazard")
    await r.cap("刚报了一条：磨床防护门联锁被短接——重大隐患", 3000)
    if await _anomaly(r, "重大隐患"):
        await r.cap("带着重大隐患生产，校验不通过；先停机挂牌上锁，整改后由另一个人验收解锁", 5000)


async def teach_energy(r):
    await r.go("/energy", 2500)
    await r.title("能源与环境", "空转报警 → 自动待机，峰时开炉 → 错峰")
    await r.point("[data-help=energy-kpis]")
    await r.cap("上方：用电、电费、峰时占比、空转电量、碳排放、需量", 3500)
    await r.point("[data-help=energy-curve]")
    await r.cap("车间总表：每 15 分钟一个读数；红峰、黄平、蓝谷，虚线是合同需量", 4000)
    await _try(r, "idle-saw")
    await r.point("[data-help=energy-units]")
    await r.cap("让带锯床下班忘关：开着没活，电量条的灰色（空转）会涨上来", 4000)
    if await _anomaly(r, "空转", 90):
        await r.cap("方案：这台空闲 10 分钟自动待机、30 分钟、全部机加设备——推演未来 24 小时省多少电和钱", 5000)


async def teach_finance(r):
    await r.go("/finance?tab=arap", 2000)
    await r.title("经营与财务", "应收逾期 → 催款 → 现金")
    await r.point("[data-help=fin-kpis]")
    await r.cap("上方：毛利率、应收与逾期、应收周转天数、现金、本月预算已用", 3500)
    res = await _try(r, "overdue-invoice")
    await r.pg.reload(wait_until="networkidle")
    await r.pg.wait_for_timeout(1500)
    if res:
        await r.cap("刚让一张应收发票逾期 15 天：客户不催不付", 3000)
    await r.point("[data-help=fin-tabs]")
    await r.cap("应收应付：每张发票的到期日、逾期天数", 3000)
    if res and await _anomaly(r, "应收逾期"):
        await r.cap("方案：不催、催款、暂停发货——推演未来 8 周的现金", 4500)
    await r.go("/finance?tab=margins", 2000)
    await r.cap("订单毛利：收入减材料、人工、设备、能源，再减违约金、加急费，一张瀑布图看清", 4500)


# ---------------------------------------------------------------- 剧本：企业版（这边只有 AI 设置；账号、新产品进工厂是那边的企业功能）
async def ent_ai(r):
    await r.go("/ont/ai", 2500)
    await r.title("AI 设置", "国内自动用 DeepSeek，其他地方用 Claude")
    if await r.has("[data-help=ai-model]"):
        await r.point("[data-help=ai-model]")
        await r.cap("“自动”按服务器所在地区选；也可以固定用一家", 4000)
        await r.cap("两家都配了密钥时，一家出错自动换另一家，这里显示上次实际用的是哪家", 4000)
    await r.cap("每次 AI 回答都记在这里：问了什么、查了哪些数据、用的哪家模型", 4000)


# ---------------------------------------------------------------- 机器人厂（第 45 轮）：在按 wenquest-robot 清单起的厂里录
async def robot_plant(r):
    await r.go("/3d", 4000)
    await r.title("机器人厂", "问渠数字工业园第二座厂：协作机器人、搬运 AGV、关节模组")
    await r.cap("车间按工厂清单摆好：下料、数控车、加工中心、外圆磨、三坐标在前段", 3500)
    await r.cap("后段是关节装配、关节测试台、整机装配、整机标定、负载跑合、AGV 装配和调试场地", 4000)
    await r.cap("两台物流小车在仓库和各工位之间送料，灯的颜色是设备此刻的状态", 3500)
    await r.go("/", 2500)
    await r.cap("首页的指标、关键物料、订单都是这座厂自己的：问渠减速器厂的 WQR-105 是这里的外购件", 4000)


async def robot_order(r):
    await r.go("/work/planner")
    await r.title("接一台协作机器人的单", "多层物料清单展开、按层下达、做完开票")
    await r.cap("产品选 WQ-CR5（六轴协作机器人），填数量和交期", 2500)
    await r.fill("[data-help=planner-qty] input", 1)
    await r.click("[data-help=planner-calc]", 2500)
    await r.scroll("text=算料结果")
    await r.cap("一台整机展开成三种关节模组、壳体、空心轴、臂管、底座：自制件、部件都要下工单", 4000)
    await r.scroll("[data-help=planner-wos]")
    await r.cap("先下达最底层的自制件，入库后再下关节模组，最后整机装配", 4000)
    await r.cap("整机做完、入库后，系统自动开销售发票（ERPNext 里能看到）", 3500)


async def robot_joint(r):
    await r.go("/work/quality", 2500)
    await r.title("关节测试与整机标定", "测试台的数据进控制图，异常开 8D")
    await r.point("[data-help=q-chart]")
    sel = r.pg.locator("select[aria-label='测量特性']")
    if await sel.count():
        await sel.select_option("WQJ-S|joint_backlash")
        await r.pg.wait_for_timeout(1500)
    await r.cap("特性里选“WQJ-S · 背隙”：每个点是一台小关节在测试台上量出的回差", 4000)
    await r.cap("还有空载摩擦力矩、编码器零位标定残差，整机的位置重复精度和标定后绝对定位误差", 4000)
    await r.point("[data-help=q-8d]")
    await r.cap("点子一路偏向公差线，就为这个特性开一张质量异常单（8D）", 3500)


SCRIPTS = {
    "teach-login": teach_login, "teach-order": teach_order, "teach-dispatch": teach_dispatch, "teach-3d": teach_3d,
    "teach-anomaly": teach_anomaly, "teach-8d": teach_8d, "teach-ai": teach_ai,
    "teach-labs": teach_labs, "teach-director": teach_director, "teach-maint": teach_maint,
    "teach-home": teach_home, "teach-service": teach_service, "teach-supply": teach_supply, "teach-people": teach_people,
    "teach-ehs": teach_ehs, "teach-energy": teach_energy, "teach-finance": teach_finance,
    "ent-ai": ent_ai,
    "robot-plant": robot_plant, "robot-order": robot_order, "robot-joint": robot_joint,
}
AFTER = {"teach-maint": teach_maint_after, "teach-director": teach_director_after}   # 录完的收尾（录失败也做）
ROLE = {"teach-order": "planner", "teach-dispatch": "operator", "teach-8d": "quality", "robot-order": "planner", "robot-joint": "quality"}   # 学生岗位；其余用厂长（老师）
# （第 30 轮 8-4 的几段用老师：要按“当场动手”、要能登记投诉、检验来料）
ORDER_LAST = ("teach-director",)       # 会重置情景，放最后

# 只在 freecad-ai-parts 的企业功能视频（企业账号、新产品进工厂）：剧本在它独有的 tools/help_videos_enterprise.py，
# 清单在各自的 web/src/help/extra.json（factory/SYNC.md）；问渠这边两样都是空的
_ENT = os.path.join(HERE, "help_videos_enterprise.py")
if os.path.exists(_ENT):
    import importlib.util  # noqa: E402
    _spec = importlib.util.spec_from_file_location("help_videos_enterprise", _ENT)
    _ent = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_ent)
    SCRIPTS.update(_ent.SCRIPTS)                           # 剧本只用传进来的录制助手 r（Rec）
    ROLE.update(getattr(_ent, "ROLE", {}))
EXTRA = os.path.join(os.path.dirname(HERE), "web", "src", "help", "extra.json")


def manifest():
    """视频清单：共有的 videos.json 加上本仓库 extra.json 里的 videos"""
    with open(MANIFEST, encoding="utf-8") as f:
        out = json.load(f)
    if os.path.exists(EXTRA):
        with open(EXTRA, encoding="utf-8") as f:
            out.update(json.load(f).get("videos") or {})
    return out


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

    names = order([n for n, v in manifest().items() if v["edition"] == args.edition and (not args.only or n in args.only)])
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
    ap.add_argument("--edition", choices=("teach", "enterprise", "robot"), required=True,
                    help="robot：机器人厂一册，要在按 wenquest-robot 清单起的厂里录（第 45 轮）")
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
