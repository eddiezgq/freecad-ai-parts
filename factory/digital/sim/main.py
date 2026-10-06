# -*- coding: utf-8 -*-
"""仿真车间服务入口：接总线，收指令，按仿真时钟推进。

环境变量：WQ_MQTT_HOST / WQ_MQTT_PORT、WQ_MODE（teach / prod）、
WQ_SIM_SPEED（倍速，默认 20：1 分钟真实时间 = 20 分钟仿真时间）、
WQ_SIM_AUTOSTART（1 = 派工即开工，不等终端点“开工”）、WQ_TZ（工厂所在时区）。

仿真器自身的指令发到 wq/gearbox/machining/sim/cmd（仅教学模式）：
  load_scenario  重新开始并载入“实验 7”教学情景（历史库应先由工作台清空）
  set_speed      改倍速，data.speed
  set_problem    注入隐藏的加工问题（data.problem、data.magnitude，见 sim/errors.py）；clear_problems 清除
  apply_fix      下发 8D 的纠正措施（data.fix）：对症的问题消失
  snapshot       发出全部内存状态（sim.snapshot，推演用；两种模式都可）
  set_calendar   换班次日历（data.calendar：24 小时连续 / 按班次与加班；两种模式都可）
"""
import logging
import os
import queue
import signal
import sys
import time

sys.path[:0] = [os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))]

from wqbus.client import Bus  # noqa: E402
from wqbus.topics import topic  # noqa: E402
from sim.engine import Clock, Engine  # noqa: E402
from sim import scenario  # noqa: E402

log = logging.getLogger("sim")


class Service:
    def __init__(self):
        self.mode = os.environ.get("WQ_MODE", "teach")
        self.speed = float(os.environ.get("WQ_SIM_SPEED", "20"))
        self.auto = os.environ.get("WQ_SIM_AUTOSTART", "0") == "1"
        self.tz = os.environ.get("WQ_TZ", "America/New_York")
        self.bus = Bus("wq-sim", mode=self.mode)
        self.inbox = queue.Queue()
        self.eng = self._new_engine()
        # 虚拟 PLC（第 18 轮第 8 步）：压装工位、分拣线由学生的 PLC 程序控制，按本车间的倍速回放班次
        from vplc.runner import VirtualPLC
        self.vplc = VirtualPLC(lambda tp, ty, src, d, corr: self._publish(tp, ty, src, d, corr), speed=lambda: self.speed)

    def _publish(self, tp, type_, source, data, corr, ts=None):
        self.bus.publish(tp, type_, source, data, corr=corr, ts=ts)

    def _new_engine(self, speed=None):
        return Engine(lambda tp, ty, src, d, corr: self._publish(tp, ty, src, d, corr), Clock(speed or self.speed),
                      mode=self.mode, auto_start=self.auto)

    def sim_command(self, data, corr):
        cmd = data.get("command")
        # 第 17 轮 C 期：快照和班次日历两种模式都接受（推演、加班在生产模式也要用）
        if cmd == "snapshot":
            self._publish(topic("machining", "sim", "snapshot"), "sim.snapshot", "sim",
                          {"snapshot": self.eng.snapshot(), "request": data.get("request") or ""}, corr)
            return True, "已发出快照"
        if cmd == "set_calendar":
            from sim.calendar import Calendar
            try:
                cal = Calendar.from_dict(data.get("calendar"))
            except (ValueError, KeyError) as e:
                return False, "班次日历不对：{}".format(e)
            self.calendar = cal
            self.eng.set_calendar(cal)
            return True, "班次：{}".format("按班次" if cal.mode == "shift" else "24 小时连续")
        if self.mode != "teach":
            return False, "生产模式下不能控制仿真器"
        if cmd == "set_speed":
            sp = float(data.get("speed", 20))
            if not 0.1 <= sp <= 600:
                return False, "倍速应在 0.1–600 之间"
            self.speed = sp
            self.eng.clock.set_speed(sp)
            return True, "倍速已改为 {:g}".format(sp)
        if cmd == "load_scenario":
            speed = float(data.get("speed", 1))
            self.eng = self._new_engine(speed)
            t = scenario.load(self.eng, self._publish, tz=self.tz)
            self.eng.clock = Clock(speed)
            self.eng.clock.t0_sim = t
            if getattr(self, "calendar", None) is not None:   # 情景的历史按连续运转跑完，之后沿用当前班次设置
                self.eng.set_calendar(self.calendar)
            self.speed = speed
            self.eng.publish_all_status()
            return True, "已载入实验 7 情景，倍速 {:g}".format(speed)
        if cmd == "set_problem":            # 第 13 轮：老师注入隐藏的加工问题
            try:
                self.eng.errors.inject(data.get("problem"), data.get("magnitude"))
            except KeyError:
                return False, "没有这个问题情景：" + str(data.get("problem"))
            return True, "已注入问题情景"
        if cmd == "clear_problems":
            self.eng.errors.clear()
            return True, "已清除全部问题情景"
        if cmd == "apply_fix":              # 8D 的纠正措施经老师批准后下发
            try:
                gone = self.eng.errors.apply_fix(data.get("fix"))
            except KeyError:
                return False, "没有这项措施：" + str(data.get("fix"))
            return True, "措施已实施" + ("" if gone else "（数据是否改善请看后续零件）")
        return False, "仿真器不支持指令 " + str(cmd)

    def run(self):
        self.bus.subscribe("wq/gearbox/+/+/cmd", lambda t, m: self.inbox.put((t, m)))
        self.bus.start()
        log.info("仿真车间已接总线 %s:%s，模式 %s，倍速 %s，自动开工 %s",
                 self.bus.host, self.bus.port, self.mode, self.speed, self.auto)
        self.eng.publish_all_status()
        stop = []
        signal.signal(signal.SIGTERM, lambda *a: stop.append(1))
        try:
            while not stop:
                try:
                    while True:
                        t, m = self.inbox.get_nowait()
                        unit = t.split("/")[3]
                        if self.vplc.handle(unit, m):
                            log.info("虚拟 PLC：%s 收到程序（班次 %s）", unit, m["data"].get("run_id"))
                            continue
                        if unit == "sim":
                            if m.get("mode") and m["mode"] != self.mode and m["data"].get("command") in ("set_calendar", "snapshot"):
                                continue          # 另一个模式的班次 / 快照（教学、生产各有一套），不是发给这台仿真车间的
                            ok, reason = self.sim_command(m["data"], m.get("corr"))
                            self.bus.publish(topic("machining", "sim", "cmd/ack"), "machine.ack", "sim",
                                             {"accepted": ok, "reason": reason, "command": m["data"].get("command")},
                                             corr=m.get("corr"))
                        else:
                            ok, reason = self.eng.command(unit, m["data"], m.get("corr"))
                        log.info("指令 %s %s → %s %s", unit, m["data"].get("command"), ok, reason)
                except queue.Empty:
                    pass
                self.eng.run_due()
                time.sleep(0.05)
        except KeyboardInterrupt:
            pass
        self.bus.stop()


def main():
    logging.basicConfig(level=os.environ.get("WQ_LOG", "INFO"), format="%(asctime)s sim %(levelname)s %(message)s")
    Service().run()


if __name__ == "__main__":
    main()
