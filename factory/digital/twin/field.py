# -*- coding: utf-8 -*-
"""客户现场模拟器（第 15 轮 T2）：出厂的 WQR-105 分到三类客户，按各自工况每个“现场日”出一条运行摘要。

一条运行摘要（消息 twin.telemetry，主题 wq/gearbox/field/<序列号>/telemetry）就是现场的边缘采集器每天上报的内容，
真设备按同样格式发上来即可（见 docs/帮助/数字孪生.md“接入真设备”）：
  serial, day（现场日期）, period_h（这条覆盖多少小时：24 或 168）, run_h（运行小时）, starts（起动次数）,
  n_in_rpm（输入转速）, torque_mean_nm / torque_max_nm（输出转矩，运行时的平均、最大）,
  rainflow（输出转矩雨流计数 [[幅值, 平均值, 次数], ...]，边缘端算好）, load_hist（[[转矩, 运行小时], ...]）,
  t_amb_c（环境温度）, oil_t_c / oil_t_max_c（油温，运行时平均、最高）, vib_mm_s（振动烈度，运行时有效值）。
同一台、同一天的数据每次生成都一样（随机数按序列号和日期定种子），便于复现和测试。
"""
import datetime as dt
import math
import random
import zlib

from twin import models as M

# 三类客户：每天运行小时、每周运行天数、平均负载率（相对额定 350 N·m）、起动次数、起动冲击倍数、卡料（次 / 天、倍数）、
# 环境温度（年平均、季节幅值）、输入转速（变频降速）
SITES = {
    "mine": {"label": "矿山皮带机", "customer": "北方矿业 · 2 号主运皮带", "run_h": 16, "days_week": 7, "load": (0.80, 0.90),
             "starts": (4, 8), "start_peak": (1.6, 1.8), "jam_per_day": 0.12, "jam_peak": (2.0, 2.3), "amb": (14, 12),
             "n_in": 1450, "note": "重载、多冲击、粉尘大"},
    "port": {"label": "港口输送", "customer": "东港码头 · 散货输送线", "run_h": 20, "days_week": 7, "load": (0.65, 0.75),
             "starts": (8, 14), "start_peak": (1.4, 1.6), "jam_per_day": 0.03, "jam_peak": (1.8, 2.0), "amb": (22, 10),
             "n_in": 1450, "note": "中载、户外、夏天热"},
    "food": {"label": "食品厂包装线", "customer": "鲜丰食品 · 包装线", "run_h": 8, "days_week": 5, "load": (0.40, 0.50),
             "starts": (15, 25), "start_peak": (1.3, 1.5), "jam_per_day": 0.0, "jam_peak": (1.5, 1.5), "amb": (22, 2),
             "n_in": 1160, "note": "轻载、室内恒温、变频 80%"},
}
# 可以“制造”的故障（老师控制台，T4）
FAULTS = {
    "cooling": "散热变差（风扇坏 / 表面积灰）：散热系数在 2 天内降到 70%",
    "bearing": "轴承早期损坏（中间轴轴承 B）：振动按指数上升，约 25 天进入 D 区，油温略升",
    "overload": "过载：皮带上料过多，平均转矩 ×1.3，卡料增多",
}


def _rng(serial, day):
    return random.Random(zlib.crc32("{}|{}".format(serial, day).encode()))


def _unit_base(serial):
    r = random.Random(zlib.crc32(serial.encode()))
    return {"vib0": r.uniform(0.45, 0.85), "k_fac": r.uniform(0.98, 1.02), "load_fac": r.uniform(0.97, 1.03)}


def season(day, mean, amp):
    doy = day.timetuple().tm_yday
    return mean + amp * math.sin(2 * math.pi * (doy - 110) / 365)


def fault_effects(faults, day):
    """返回 (散热系数倍数, 振动倍数, 负载倍数, 卡料倍数, 油温附加)"""
    k, v, ld, jam, dt_oil = 1.0, 1.0, 1.0, 1.0, 0.0
    for f in faults or []:
        since = (day - dt.date.fromisoformat(f["start"])).days
        if since < 0:
            continue
        if f["kind"] == "cooling":
            k *= 1 - 0.30 * min(1.0, (since + 1) / 2)
        elif f["kind"] == "bearing":
            v *= min(12.0, math.exp(0.085 * since))                # 约 25 天振动 ×8
            dt_oil += min(6.0, 0.25 * since)
        elif f["kind"] == "overload":
            ld *= 1.3
            jam *= 4
    return k, v, ld, jam, dt_oil


def day_summary(serial, site_key, day, faults=None, period_days=1):
    """一台、一段（1 天或 7 天）的运行摘要（不含信封）"""
    st = SITES[site_key]
    base = _unit_base(serial)
    T_r = M.RATED_T_NM
    run_h = starts = 0
    cyc, hist = {}, {}
    tq_sum = tq_max = 0.0
    oil_sum = oil_max = amb_sum = vib_sum = 0.0
    n_run_days = 0
    for k in range(period_days):
        d = day - dt.timedelta(days=period_days - 1 - k)
        r = _rng(serial, d.isoformat())
        amb = season(d, *st["amb"]) + r.gauss(0, 2.0)
        amb_sum += amb
        kf, vf, lf, jf, dto = fault_effects(faults, d)
        if d.weekday() >= st["days_week"]:
            continue
        n_run_days += 1
        h = st["run_h"] * r.uniform(0.9, 1.0)
        mean = T_r * r.uniform(*st["load"]) * base["load_fac"] * lf
        ns = r.randint(*st["starts"])
        peaks = [T_r * r.uniform(*st["start_peak"]) * min(lf, 1.15) for _ in range(ns)]
        if r.random() < st["jam_per_day"] * jf:
            peaks[0] = T_r * r.uniform(*st["jam_peak"]) * min(lf, 1.1)
        for p in peaks:                                            # 起动—停机：0 → 峰值 → 0 一个大循环
            key = (round(p / 2 / 5) * 5, round(p / 2 / 5) * 5)
            cyc[key] = cyc.get(key, 0) + 1
        fl = round(0.08 * T_r / 5) * 5                             # 运行中的波动：幅值约 8% 额定、0.5 Hz
        key = (fl, round(mean / 5) * 5)
        cyc[key] = cyc.get(key, 0) + int(h * 3600 * 0.5)
        for f_, w in ((0.9, 0.25), (1.0, 0.5), (1.1, 0.25)):      # 运行时的转矩分布（给轴承用）
            tb = round(mean * f_ / 25) * 25
            hist[tb] = hist.get(tb, 0.0) + h * w
        run_h += h
        starts += ns
        tq_sum += mean * h
        tq_max = max(tq_max, max(peaks))
        oil = M.oil_temp_model(mean, amb, st["n_in"], M.K_S * base["k_fac"] * kf) + dto + r.gauss(0, 1.0)
        oil_sum += oil * h
        oil_max = max(oil_max, oil + 4 + r.uniform(0, 2))
        vib_sum += base["vib0"] * vf * (1 + 0.15 * (mean / T_r - 0.6)) * r.uniform(0.95, 1.05) * h
    out = {"serial": serial, "item": "WQR-105", "site": site_key, "customer": st["customer"], "day": day.isoformat(),
           "period_h": 24 * period_days, "run_h": round(run_h, 2), "starts": starts, "n_in_rpm": st["n_in"],
           "t_amb_c": round(amb_sum / period_days, 1)}
    if run_h > 0:
        out.update(torque_mean_nm=round(tq_sum / run_h, 1), torque_max_nm=round(tq_max, 1),
                   rainflow=[[a, m, n] for (a, m), n in sorted(cyc.items())],
                   load_hist=[[t, round(h, 2)] for t, h in sorted(hist.items())],
                   oil_t_c=round(oil_sum / run_h, 1), oil_t_max_c=round(oil_max, 1), vib_mm_s=round(vib_sum / run_h, 3))
    else:
        out.update(rainflow=[], load_hist=[])
    return out
