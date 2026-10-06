# -*- coding: utf-8 -*-
"""数字工厂虚拟 PLC（《PLC 原理及实践》第 18 轮第 8 步）。

一个班次分两段做：
1. 计算：把程序和设备交给 js/tool.mjs（问渠 PLC 引擎 + 虚拟设备 + 模拟操作工，与学习平台实验台同一套代码），
   按 10 ms 扫描周期算完整个班次（8 小时约 20 秒），得到带时刻的事件表和班次汇总。结果只由程序和随机种子决定。
2. 回放：按数字工厂的倍速（仿真车间的时钟，默认 20 倍，一个班次约 24 分钟）把事件发到总线：
   设备状态 machine.status、每个工件 plc.cycle、报警与恢复 machine.event、班次开始与结束 plc.shift。
   来源写 plc/<设备>（第 1 轮为真实 PLC 留的格式）。枢纽据此记录班次、显示“虚拟 PLC”页。

指令：枢纽向 wq/gearbox/<区域>/<设备>/cmd 发 plc.download（run_id、program、hours、seed、speed）。
同一台设备收到新程序时，正在回放的班次作废（cancelled），新班次开始。speed=0 表示不等，立即发完（测试用）。
"""
import json
import logging
import os
import subprocess
import threading
import time

from wqbus.topics import PLC_UNITS, unit_topic

log = logging.getLogger("vplc")
HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "js", "tool.mjs")
NODE = os.environ.get("WQ_NODE", "node")
STATE = {"run": "run", "idle": "idle", "fault": "fault", "down": "down", "stop": "down"}


def tool(job, timeout=180):
    """跑一次 js/tool.mjs；返回它输出的 JSON。"""
    p = subprocess.run([NODE, TOOL], input=json.dumps(job).encode("utf-8"), capture_output=True, timeout=timeout)
    if p.returncode != 0 and not p.stdout:
        raise RuntimeError("虚拟 PLC 计算出错：" + p.stderr.decode("utf-8", "replace")[-500:])
    return json.loads(p.stdout.decode("utf-8"))


def openplc_check(unit, program_st, seconds=90, url=None):
    """同一程序在 OpenPLC 运行时上编译并按真实时间控制同一台虚拟设备 seconds 秒（openplc/control.py）。
    没配 WQ_OPENPLC_CHECK_URL 时返回 None（不做）。"""
    import urllib.request
    url = url or os.environ.get("WQ_OPENPLC_CHECK_URL", "")
    if not url:
        return None
    req = urllib.request.Request(url.rstrip("/") + "/check", data=json.dumps({"st": program_st, "unit": PLC_UNITS[unit], "seconds": seconds}).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=seconds + 900) as r:      # 前面可能有别的设备在排队
            out = json.loads(r.read().decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "stage": "error", "log": "OpenPLC 检查服务没有回应：" + str(e)[:300]}
    for k in ("program", "log"):
        if isinstance(out.get(k), str):
            out[k] = out[k][-60000:]
    out.pop("cycles", None)
    return out


def compute(unit, program_st, hours=8.0, seed=1):
    return tool({"op": "shift", "unit": PLC_UNITS[unit], "program": {"st": program_st}, "hours": hours, "seed": seed},
                timeout=60 + 30 * hours)


class VirtualPLC:
    """收 plc.download，算班次，按倍速回放到总线。publish(topic, type, source, data, corr)；speed() 给当前倍速。"""

    def __init__(self, publish, speed=lambda: 20.0, compute_fn=compute, sleep=time.sleep, check_fn=openplc_check):
        self.publish, self.speed, self.compute_fn, self.sleep, self.check_fn = publish, speed, compute_fn, sleep, check_fn
        self.current = {}           # 设备 → 正在回放的班次的取消标志
        self.lock = threading.Lock()

    def handle(self, unit, msg, block=False):
        if unit not in PLC_UNITS or msg.get("type") != "plc.download":
            return False
        d = msg["data"]
        cancel = threading.Event()
        with self.lock:
            old = self.current.get(unit)
            if old:
                old.set()
            self.current[unit] = cancel
        th = threading.Thread(target=self._run, args=(unit, d, cancel, msg.get("corr")), daemon=True, name="vplc-" + unit)
        th.start()
        if block:
            th.join()
        return True

    def _pub(self, unit, category, type_, data, corr):
        self.publish(unit_topic(unit, category), type_, "plc/" + unit, data, corr)

    def _run(self, unit, d, cancel, corr):
        rid = d["run_id"]
        shift = lambda phase, **kw: self._pub(unit, "event", "plc.shift", dict({"run_id": rid, "phase": phase}, **kw), corr)  # noqa: E731
        hours = float(d.get("hours") or 8)
        shift("started", hours=hours)
        try:
            res = self.compute_fn(unit, d["program"], hours, int(d.get("seed") or 1))
        except Exception as e:  # noqa: BLE001
            log.exception("班次计算失败")
            shift("failed", error=str(e)[:500])
            return
        if res.get("error") and not res.get("events"):
            shift("failed", error=res["error"][:500])
            return
        if self.check_fn is not None:            # OpenPLC 兼容性检查与回放同时进行（真实时间约 2–3 分钟）
            def compat():
                r = self.check_fn(unit, d["program"])
                if r is not None:
                    shift("compat", compat=r)
            threading.Thread(target=compat, daemon=True, name="openplc-" + rid).start()
        speed = d.get("speed")
        # 回放的时钟：从 (a_real, a_sim) 起按倍速 sp 走；车间改了倍速就从此刻起按新倍速
        a_real, a_sim = time.monotonic(), 0.0
        sp = float(speed) if speed is not None else float(self.speed())
        n = good = nok = 0
        end_ms = hours * 3600000
        for e in res["events"]:
            if cancel.is_set():
                shift("cancelled")
                return
            while sp > 0 and not cancel.is_set():
                if speed is None:
                    sp2 = float(self.speed())
                    if sp2 > 0 and sp2 != sp:
                        now = time.monotonic()
                        a_sim, a_real, sp = a_sim + (now - a_real) * sp, now, sp2
                left = a_real + (e["t"] / 1000.0 - a_sim) / sp - time.monotonic()
                if left <= 0:
                    break
                self.sleep(min(left, 0.5))
            if cancel.is_set():
                shift("cancelled")
                return
            k, t_s = e["kind"], round(e["t"] / 1000.0, 2)
            if k == "state":
                self._pub(unit, "status", "machine.status", {"state": STATE[e["state"]], "run_id": rid, "t_s": t_s,
                                                              "progress": min(1.0, e["t"] / end_ms)}, corr)
            elif k == "cycle":
                c = int(e.get("count") or 1)
                n += c
                if e["good"]:
                    good += c
                else:
                    nok += c
                data = {"run_id": rid, "good": bool(e["good"]), "n": n, "good_n": good, "nok_n": nok, "t_s": t_s,
                        "progress": min(1.0, e["t"] / end_ms)}
                if e.get("cycle_s") is not None:
                    data["cycle_s"] = e["cycle_s"]
                if e.get("peak_kN") is not None:
                    data["peak_kN"] = e["peak_kN"]
                self._pub(unit, "event", "plc.cycle", data, corr)
            elif k == "alarm":
                self._pub(unit, "event", "machine.event", {"event": "alarm", "code": e["code"], "message": e["text"][0],
                                                            "message_en": e["text"][1], "run_id": rid, "t_s": t_s}, corr)
            elif k == "recover":
                self._pub(unit, "event", "machine.event", {"event": "recover", "run_id": rid, "t_s": t_s}, corr)
            elif k == "hazard":
                self._pub(unit, "event", "machine.event", {"event": "alarm", "code": "E-SAFETY", "message": "危险动作（安全条件失效）",
                                                            "message_en": "Hazardous motion (a safety condition failed)",
                                                            "run_id": rid, "t_s": t_s, "why": e.get("why")}, corr)
            elif k == "stall":
                self._pub(unit, "event", "machine.event", {"event": "alarm", "code": "E-STALL", "message": "停线超过 10 分钟，程序没有动作",
                                                            "message_en": "Line idle for over 10 minutes: the program does nothing",
                                                            "run_id": rid, "t_s": t_s}, corr)
            elif k == "plc_stop":
                self._pub(unit, "event", "machine.event", {"event": "fault", "code": "E-PLC-STOP", "message": "PLC 停机：" + e["error"][:200],
                                                            "run_id": rid, "t_s": t_s}, corr)
        shift("done", summary=res["summary"])
        with self.lock:
            if self.current.get(unit) is cancel:
                del self.current[unit]
