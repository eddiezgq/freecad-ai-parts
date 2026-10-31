# -*- coding: utf-8 -*-
"""车间要有人（第 18 轮 E4-4）：每台需要人的设备按排班看这一班有没有能开它的人。

- 两个班：早班 06:00–18:00、晚班 18:00–次日 06:00（工厂本地时间）；晚班过了半夜仍算前一天的晚班。
- 平台（hub/people.py）按排班、出勤和技能矩阵算出每天每班每台设备的“人员等级”下发：
  0 没人（设备停在“缺人”）、1 只有学徒（按 60% 速度开）、2 熟练以上（正常）。
- 没下发的（设备、日子、班）按“有人”算：平台还没排班时车间照常；没人的班平台明确下发 0。关闭时和以前完全一样。
- 测试台、检验台是自动设备，不需要人。"""
import datetime as dt

NEEDS = ("saw-01", "cnc-l01-a", "cnc-l01-b", "ht-01", "key-01", "grd-01", "hob-01", "vmc-01", "hmc-01", "press-01", "asm-01")
SHIFTS = {"day": ("早班", 6 * 60, 18 * 60), "night": ("晚班", 18 * 60, 30 * 60)}
APPRENTICE_RATE = 0.6
try:                                    # 第 61 轮：清单写了产品的厂（机器人厂等）：要有人的设备取自 factory/staff.py（自动测试台、跑合台不用人）
    from factory import staff as _ST
    _S = _ST.active()
except ImportError:
    _S = None
if _S:
    NEEDS = tuple(_S["needs"])


def shift_of(local):
    """本地时间 → (这一班算哪天, 'day' / 'night')"""
    m = local.hour * 60 + local.minute
    if 6 * 60 <= m < 18 * 60:
        return local.date(), "day"
    if m >= 18 * 60:
        return local.date(), "night"
    return local.date() - dt.timedelta(days=1), "night"


def shift_start(day, shift, tzi):
    start = SHIFTS[shift][1]
    return dt.datetime(day.year, day.month, day.day, tzinfo=tzi) + dt.timedelta(minutes=start)


def next_change(local):
    """下一次换班的时刻（本地时间）"""
    day, sh = shift_of(local)
    if sh == "day":
        return shift_start(day, "night", local.tzinfo)
    return shift_start(day + dt.timedelta(days=1), "day", local.tzinfo)


class Staffing:
    def __init__(self, enabled=False, levels=None, days=None):
        self.enabled = bool(enabled)
        self.levels = dict(levels or {})          # "2026-10-07|day|grd-01" → 0/1/2
        self.days = set(days or [])               # 下发过的日子

    def update(self, enabled=None, levels=None, days=None, replace=False):
        if enabled is not None:
            self.enabled = bool(enabled)
        if replace:
            self.levels, self.days = {}, set()
        if levels:
            self.levels.update({k: int(v) for k, v in levels.items()})
        if days:
            self.days.update(days)
        if levels and not days:
            self.days.update(k.split("|")[0] for k in levels)

    def set_level(self, day, shift, unit, level):
        self.levels["{}|{}|{}".format(day, shift, unit)] = int(level)
        self.days.add(str(day))

    def level(self, unit, local):
        """local：带时区的本地时间。返回 0 / 1 / 2"""
        if not self.enabled or unit not in NEEDS:
            return 2
        day, sh = shift_of(local)
        return int(self.levels.get("{}|{}|{}".format(day.isoformat(), sh, unit), 2))

    def to_dict(self):
        return {"enabled": self.enabled, "levels": dict(self.levels), "days": sorted(self.days)}

    @classmethod
    def from_dict(cls, d):
        d = d or {}
        return cls(d.get("enabled", False), d.get("levels"), d.get("days"))
