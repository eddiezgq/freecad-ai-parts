# -*- coding: utf-8 -*-
"""异常判断（第 15 轮 T4）：模型和实测对不上、寿命快到、保养过期，就报警，并说出最可能的原因和依据。纯函数。

规则（每条都能对着数据手算）：
  散热：油温残差（实测 − 热平衡模型）的指数平均 > 6 ℃ 警告、> 12 ℃ 严重。振动正常 → 散热变差（风扇、积灰、通风）或油少；
        振动同时上升 → 轴承摩擦发热。
  油温绝对值：最近 7 天运行时最高油温 > 90 ℃，但残差正常 → 不是故障，是工况（重载、环境热），建议加风扇或降载。
  振动：ISO 10816-1 第 I 类，≥ 1.8 mm/s（C 区）且最近 7 天在上升 → 轴承早期损坏，警告；≥ 4.5（D 区）→ 严重。
        哪个轴承：按孪生里寿命消耗最高的轴承推断，并说明依据。
  过载：最近 7 天平均转矩 > 额定 → 警告；最近 30 天超过 2 倍额定的天数 ≥ 10 → 提示冲击偏多。
  寿命：轴承 L10 消耗 ≥ 80% 警告、≥ 100% 严重；输出轴疲劳损伤 ≥ 50% 警告。
  保养：换油过期 → 警告；14 天内到期 → 提示。
"""
import datetime as dt
import math

from twin import engine as E
from twin import models as M

LEVEL = {"info": 0, "warn": 1, "critical": 2}


def _slope(points):
    """最小二乘斜率（每天），points = [(天序, 值)]"""
    n = len(points)
    if n < 3:
        return 0.0
    mx = sum(p[0] for p in points) / n
    my = sum(p[1] for p in points) / n
    sxx = sum((p[0] - mx) ** 2 for p in points)
    return sum((p[0] - mx) * (p[1] - my) for p in points) / sxx if sxx else 0.0


def diagnose(state, logs, as_built=None):
    """state：孪生状态；logs：最近的日志行（按日期升序，至少最近 14 天）。返回发现列表：
    {kind, level, title, detail, cause, advice, evidence, action}"""
    out = []
    sm = E.summary(state, as_built)
    recent = [r for r in logs if r.get("run_h", 0) > 0][-7:]
    last_day = state.get("last_day")
    vib = state.get("vib") or []
    v_now = vib[-1][1] if vib else None
    d0 = dt.date.fromisoformat(vib[-1][0]) if vib else None
    v7 = [((dt.date.fromisoformat(d) - d0).days, v) for d, v in vib if d0 and (d0 - dt.date.fromisoformat(d)).days <= 7]
    vslope = _slope(v7)
    vib_rising = v_now is not None and vslope > 0.02 * max(v_now, 0.1)
    worst = sm["worst_bearing"]

    # ---- 振动 / 轴承
    if v_now is not None and v_now >= 1.8 and vib_rising:
        lvl = "critical" if v_now >= 4.5 else "warn"
        days_to_d = None
        if lvl == "warn" and len(v7) >= 3:
            vs = [max(v, 1e-3) for _, v in v7]
            r = _slope([(x, math.log(v)) for (x, _), v in zip(v7, vs)])
            if r > 0:
                days_to_d = math.log(4.5 / v_now) / r
        out.append({
            "kind": "bearing", "level": lvl,
            "title": "振动 {:.2f} mm/s（{} 区）且在上升：轴承早期损坏".format(v_now, M.vib_zone(v_now)),
            "detail": "最近 7 天振动每天增加约 {:.0%}{}。".format(
                math.exp(_slope([(x, math.log(max(v, 1e-3))) for x, v in v7])) - 1,
                "，照这个速度约 {:.0f} 天进入 D 区（> 4.5 mm/s，不允许运行）".format(days_to_d) if days_to_d else ""),
            "cause": "振动烈度按 ISO 10816-1 第 I 类（≤ 15 kW）分区：A/B 0.71、B/C 1.8、C/D 4.5 mm/s。振动持续上升、油温略升，"
                     "最常见的是滚动轴承滚道剥落。寿命模型里消耗最高的是{}（{}，已用 L10 的 {:.0%}），最可能是它。".format(
                         worst["name"], worst["model"], worst["used"]),
            "advice": "安排停机检查{}（听诊、频谱看轴承故障频率），备好 {} 轴承；{}".format(
                worst["name"], worst["model"], "立即停机更换" if lvl == "critical" else "一到两周内更换"),
            "evidence": [{"day": d, "vib_mm_s": v} for d, v in vib[-8:]],
            "action": {"kind": "bearing:" + worst["id"], "label": "开维修单：更换{}".format(worst["name"])}})

    # ---- 油温残差：散热
    res = sm["resid_c"]
    if res is not None and res > 6:
        lvl = "critical" if res > 12 else "warn"
        frictional = vib_rising and v_now is not None and v_now >= 1.8
        lr = recent[-1] if recent else {}
        out.append({
            "kind": "cooling", "level": lvl,
            "title": "油温比模型高 {:.1f} ℃：{}".format(res, "轴承摩擦发热" if frictional else "散热变差"),
            "detail": "最近一天实测油温 {} ℃，按当天转矩 {} N·m、环境 {} ℃ 用热平衡算应该 {} ℃。".format(
                lr.get("oil_t_c"), lr.get("torque_mean_nm"), lr.get("t_amb_c"), lr.get("oil_model_c")),
            "cause": ("振动也在上升：多半是轴承损坏、摩擦发热，先处理轴承。" if frictional else
                      "工况（转矩、环境温度）都算进模型了，实测还是高很多，说明散热系数变小了：风扇坏、箱体表面积了灰 / 油泥、"
                      "通风被挡，或者油少了（搅油、润滑变差）。"),
            "advice": "检查风扇、清理箱体表面和散热筋、检查油位" + ("；油温 > 90 ℃ 先降载运行" if lvl == "critical" else ""),
            "evidence": [{"day": r["day"], "oil_t_c": r.get("oil_t_c"), "oil_model_c": r.get("oil_model_c"), "resid_c": r.get("resid_c")}
                         for r in recent],
            "action": {"kind": "cooling", "label": "开维修单：清洁散热、检查风扇和油位"}})
    elif recent and max((r.get("oil_t_max_c") or 0) for r in recent) > 90:
        out.append({
            "kind": "hot", "level": "warn", "title": "最高油温超过 90 ℃（工况造成，不是故障）",
            "detail": "实测和模型一致（残差 {:.1f} ℃），是负载或环境温度高。".format(res or 0),
            "cause": "油温 = 环境 + 发热 ÷（散热系数 × 面积），重载、夏天户外都会让油温升高。",
            "advice": "轴端加风扇（散热系数 17 → 31）或降载；油温高也会让换油提前",
            "evidence": [{"day": r["day"], "oil_t_max_c": r.get("oil_t_max_c"), "t_amb_c": r.get("t_amb_c")} for r in recent],
            "action": None})

    # ---- 过载：平均转矩超额定 → 警告；只是冲击多（最近 30 天超过 2 倍额定的天数 ≥ 10，正常矿山约 12% 的天会卡料）→ 提示
    if recent:
        tm = sum(r["torque_mean_nm"] * r["run_h"] for r in recent if r.get("torque_mean_nm")) / max(1e-9, sum(r["run_h"] for r in recent))
        days30 = [r for r in logs if r.get("run_h", 0) > 0 and r.get("period_h", 24) <= 24][-30:]
        big = [r for r in days30 if (r.get("torque_max_nm") or 0) > 2.0 * M.RATED_T_NM]
        if tm > M.RATED_T_NM or len(big) >= 10:
            lvl = "warn" if tm > M.RATED_T_NM else "info"
            out.append({
                "kind": "overload", "level": lvl,
                "title": ("过载：最近 7 天平均转矩 {:.0f} N·m（额定 {:.0f}）".format(tm, M.RATED_T_NM) if lvl == "warn" else
                          "冲击偏多：最近 {} 天里有 {} 天超过 2 倍额定".format(len(days30), len(big))),
                "detail": "轴承寿命按载荷的 3 次方缩短：平均转矩高 30%，轴承寿命只剩约一半（1/1.3³ ≈ 0.46）；冲击主要消耗输出轴的疲劳寿命。",
                "cause": "皮带上料过多、卡料，或者选型时低估了负载。",
                "advice": "和客户核对给料量、加过载保护（液力耦合器 / 转矩限制器）；长期如此要换大一号的减速器——数据已可送设计台",
                "evidence": [{"day": r["day"], "torque_mean_nm": r.get("torque_mean_nm"), "torque_max_nm": r.get("torque_max_nm")} for r in recent],
                "action": None})

    # ---- 寿命
    if worst["used"] >= 0.8:
        lvl = "critical" if worst["used"] >= 1 else "warn"
        out.append({
            "kind": "bearing_life", "level": lvl,
            "title": "{}已用 L10 寿命的 {:.0%}".format(worst["name"], worst["used"]),
            "detail": "按最近 30 天的使用强度，{}。".format(
                "已经超过 L10（10% 的同型轴承会在此前损坏）" if worst["used"] >= 1 else
                "约 {:.0f} 天后到 L10".format(worst["remaining_days"]) if worst["remaining_days"] else "近期不会到 L10"),
            "cause": "L10 是 90% 可靠度的寿命，不是“到期必坏”；但越往后坏的概率越大，计划停机时换比坏了再换便宜得多。",
            "advice": "下次计划停机时更换 {}（预防性更换）".format(worst["model"]),
            "evidence": [{"bearing": b["id"], "used": round(b["used"], 3)} for b in sm["bearings"]],
            "action": {"kind": "bearing:" + worst["id"], "label": "开维修单：预防性更换{}".format(worst["name"])}})
    if sm["shaft"]["used"] >= 0.5:
        out.append({"kind": "shaft_life", "level": "warn", "title": "输出轴疲劳损伤已累积 {:.0%}".format(sm["shaft"]["used"]),
                    "detail": "Miner 累积损伤到 1 即预计出现疲劳裂纹。", "cause": "冲击、卡料次数多。",
                    "advice": "检查键槽附近有无裂纹（磁粉探伤）；把现场载荷谱送设计台复核", "evidence": [], "action": None})

    # ---- 保养
    oil = sm["oil"]
    if oil["left_h"] <= 0:
        out.append({"kind": "oil", "level": "warn", "title": "换油已过期 {:.0f} 当量小时".format(-oil["left_h"]),
                    "detail": "本次换油后已累计 {:.0f} 当量小时（油温高于 70 ℃ 每高 10 ℃ 按 2 倍计），应在 {:.0f} 小时换。".format(
                        oil["eq_h"], oil["due_h"]),
                    "cause": "油老化后黏度下降、酸值升高，齿面和轴承磨损加快。", "advice": "尽快换油（L-CKC 220），并取油样化验",
                    "evidence": [], "action": {"kind": "oil", "label": "开维修单：换油"}})
    elif oil["days"] is not None and oil["days"] < 14:
        out.append({"kind": "oil", "level": "info", "title": "约 {:.0f} 天后该换油".format(oil["days"]),
                    "detail": "还剩 {:.0f} 当量小时。".format(oil["left_h"]), "cause": "例行保养。",
                    "advice": "安排下次停机时换油", "evidence": [], "action": {"kind": "oil", "label": "开维修单：换油"}})
    for f in out:
        f["day"] = last_day
    return out


def health(findings):
    lv = max([LEVEL[f["level"]] for f in findings] or [-1])
    return {2: "red", 1: "yellow"}.get(lv, "green")
