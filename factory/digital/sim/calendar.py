# -*- coding: utf-8 -*-
"""班次日历（第 17 轮 C 期 C1）：仿真车间什么时候开工、什么时候下班、哪天哪台加班。

两种模式：
- continuous：24 小时连续运转（教学模式默认，与以前一样）；
- shift：按班次开停，默认周一至周五 08:00–17:00；加班 = 某天某台（或全厂）延长下班时间（每天最多 4 小时）。
下班时正在加工的那一件做完再停（由引擎保证）。时间都按工厂所在时区（WQ_TZ）。"""
import datetime as dt
from zoneinfo import ZoneInfo

MAX_OT_MIN = 240


def _hm(s):
    h, m = s.split(":")
    return int(h) * 60 + int(m)


class Calendar:
    def __init__(self, mode="continuous", tz="America/New_York", start="08:00", end="17:00", workdays=(0, 1, 2, 3, 4),
                 overtime=None):
        if mode not in ("continuous", "shift"):
            raise ValueError("班次模式只能是 continuous 或 shift")
        self.mode = mode
        self.tz = tz
        self.tzi = ZoneInfo(tz)
        self.start, self.end = start, end
        self.workdays = tuple(workdays)
        self.overtime = {}                    # (日期 iso, 设备或 "*") → 加班分钟
        for k, v in (overtime or {}).items():
            day, unit = k.split("|") if isinstance(k, str) else k
            self.add_overtime(day, unit, v)

    # ---- 加班
    def add_overtime(self, day, unit, minutes):
        minutes = int(minutes)
        if not 0 <= minutes <= MAX_OT_MIN:
            raise ValueError("加班每天 0–{} 分钟".format(MAX_OT_MIN))
        if minutes:
            self.overtime[(str(day)[:10], unit or "*")] = minutes
        else:
            self.overtime.pop((str(day)[:10], unit or "*"), None)

    def overtime_min(self, day, unit):
        d = str(day)[:10]
        return max(self.overtime.get((d, unit), 0), self.overtime.get((d, "*"), 0))

    # ---- 某天某台的班次（本地时间，分钟）
    def window(self, unit, day):
        if day.weekday() not in self.workdays:
            ot = self.overtime_min(day, unit)
            return (_hm(self.start), _hm(self.start) + ot) if ot else None      # 休息日加班：从上班时间起算
        return _hm(self.start), _hm(self.end) + self.overtime_min(day, unit)

    def is_open(self, unit, when):
        """when：带时区的 datetime"""
        if self.mode == "continuous":
            return True
        lt = when.astimezone(self.tzi)
        w = self.window(unit, lt.date())
        m = lt.hour * 60 + lt.minute + lt.second / 60
        return bool(w) and w[0] <= m < w[1]

    def next_open(self, unit, when):
        """when 之后（含）最早开工的时刻；连续模式就是 when"""
        if self.mode == "continuous" or self.is_open(unit, when):
            return when
        lt = when.astimezone(self.tzi)
        for i in range(0, 15):
            day = lt.date() + dt.timedelta(days=i)
            w = self.window(unit, day)
            if not w:
                continue
            t0 = dt.datetime(day.year, day.month, day.day, tzinfo=self.tzi) + dt.timedelta(minutes=w[0])
            t1 = dt.datetime(day.year, day.month, day.day, tzinfo=self.tzi) + dt.timedelta(minutes=w[1])
            if t1 > lt:
                return max(t0, lt).astimezone(dt.timezone.utc)
        return None

    def close_at(self, unit, when):
        """当前班次的下班时刻（不在班内返回 None）"""
        if self.mode == "continuous" or not self.is_open(unit, when):
            return None
        lt = when.astimezone(self.tzi)
        w = self.window(unit, lt.date())
        return (dt.datetime(lt.year, lt.month, lt.day, tzinfo=self.tzi) + dt.timedelta(minutes=w[1])).astimezone(dt.timezone.utc)

    def open_minutes(self, unit, day):
        if self.mode == "continuous":
            return 24 * 60
        w = self.window(unit, day)
        return (w[1] - w[0]) if w else 0

    # ---- 序列化（总线下发、快照）
    def to_dict(self):
        return {"mode": self.mode, "tz": self.tz, "start": self.start, "end": self.end, "workdays": list(self.workdays),
                "overtime": {"{}|{}".format(d, u): m for (d, u), m in sorted(self.overtime.items())}}

    @classmethod
    def from_dict(cls, d):
        d = d or {}
        return cls(mode=d.get("mode", "continuous"), tz=d.get("tz", "America/New_York"), start=d.get("start", "08:00"),
                   end=d.get("end", "17:00"), workdays=d.get("workdays", (0, 1, 2, 3, 4)), overtime=d.get("overtime"))
