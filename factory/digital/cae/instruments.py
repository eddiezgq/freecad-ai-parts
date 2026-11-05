# -*- coding: utf-8 -*-
"""虚拟仪器（第 82 轮，电子 E2）：每个学生的传感器参数、6 个测量任务的正确结果（按公式由参数算，不拿模型跑出的数当答案）、核对、实验记录。

参数只有一份：web/src/lib/sensors.json（网页模型 lib/instruments.js 读同一份）。学生参数 variant() 与网页的 JavaScript 实现逐位一致：
同一套 mulberry32 随机数、同样的取数顺序（测试 tests/test_instruments.py 用 Node 跑网页模块核对）。纯计算，不联网。
"""
from __future__ import annotations

import json
import math
import os
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
SENSORS = os.path.join(os.path.dirname(HERE), "web", "src", "lib", "sensors.json")
M32 = 0xFFFFFFFF
TASKS = ["torque", "encoder", "imu", "hall", "ntc", "tof"]
TITLES = {"torque": "力矩传感器标定", "encoder": "编码器测速与解码", "imu": "IMU 静置零偏与 Allan 方差",
          "hall": "霍尔电流传感器：灵敏度与带宽", "ntc": "热敏电阻测温曲线", "tof": "激光测距的噪声与平均"}


def params():
    with open(SENSORS, encoding="utf-8") as f:
        return json.load(f)


def seed_of(user):
    """学生编号 → 种子（同一个人每次相同）"""
    return zlib.crc32(("wq-instr:" + str(user)).encode("utf-8")) & M32


def _imul(a, b):
    return (a * b) & M32


def mulberry32(a):
    state = [a & M32]

    def nxt():
        a_ = (state[0] + 0x6D2B79F5) & M32
        state[0] = a_
        t = _imul(a_ ^ (a_ >> 15), 1 | a_)
        t = ((t + _imul(t ^ (t >> 7), 61 | t)) & M32) ^ t
        return ((t ^ (t >> 14)) & M32) / 4294967296
    return nxt


def task_seed(seed, task):
    no = TASKS.index(task) + 1
    return (seed ^ _imul(no, 0x9E3779B1)) & M32


def variant(task, seed):
    P = params()
    r = mulberry32(task_seed(seed, task))

    def c():
        return 2 * r() - 1
    if task == "torque":
        t = P["torque"]
        return {"s_mv_v": t["s_mv_v"] * (1 + t["var"]["s_mv_v"] * c()), "nl_fs": t["nl_fs"] * (1 + t["var"]["nl_fs"] * c()),
                "hys_fs": t["hys_fs"] * (1 + t["var"]["hys_fs"] * c()), "zero_mv": t["zero_mv"] + t["var"]["zero_mv"] * c()}
    if task == "encoder":
        e = P["encoder"]
        rpm = e["rpm_min"] + (e["rpm_max"] - e["rpm_min"]) * r()
        rpm = math.floor(rpm + 0.5)                  # 与 JS 的 Math.round 一致（正数）
        return {"rpm": rpm, "dir": 1 if r() < 0.5 else -1}
    if task == "imu":
        m = P["imu"]
        return {"arw": m["arw_min"] + (m["arw_max"] - m["arw_min"]) * r(), "bi": m["bi_min"] + (m["bi_max"] - m["bi_min"]) * r(),
                "bias": m["bias_min"] + (m["bias_max"] - m["bias_min"]) * r()}
    if task == "hall":
        h = P["hall"]
        return {"s_mv_a": h["s_mv_a"] * (1 + h["var"]["s_mv_a"] * c()), "vz": h["vz"] + h["var"]["vz_mv"] / 1000 * c(),
                "fb": h["fb_min"] + (h["fb_max"] - h["fb_min"]) * r()}
    if task == "ntc":
        n = P["ntc"]
        return {"b": n["b"] * (1 + n["var"]["b"] * c()), "r25": n["r25"] * (1 + n["var"]["r25"] * c())}
    if task == "tof":
        f = P["tof"]
        return {"sigma0_mm": f["sigma0_mm"] * (1 + f["var"] * c()), "k_mm_m2": f["k_mm_m2"] * (1 + f["var"] * c())}
    raise KeyError(task)


# ---------------------------------------------------------------- 正确结果（公式）
def torque_out(v, T, down=False):
    t = params()["torque"]
    x = T / t["fs_nm"]
    y = x + 4 * v["nl_fs"] * x * (1 - x) + (4 * v["hys_fs"] * x * (1 - x) if down else 0)
    return t["gain"] * v["s_mv_v"] * t["vex"] * y + v["zero_mv"]


def _fit(xs, ys):
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    k = sum((a - mx) * (b - my) for a, b in zip(xs, ys)) / sum((a - mx) ** 2 for a in xs)
    return k, my - k * mx


def answers(task, seed):
    """{项: 正确值}，以及每项的允许误差 {项: (方式, 值)}：方式 rel 相对、abs 绝对、eq 相等"""
    P = params()
    v = variant(task, seed)
    if task == "torque":
        t = P["torque"]
        ups = [0, 10, 20, 30, 40, 50]
        yu = [torque_out(v, T) for T in ups]
        k, b = _fit(ups, yu)
        fso = k * t["fs_nm"]
        nl = max(abs(y - (k * T + b)) for T, y in zip(ups, yu)) / fso * 100
        hys = max(abs(torque_out(v, T, True) - torque_out(v, T)) for T in ups) / fso * 100
        return ({"s_mv_v": k * t["fs_nm"] / (t["gain"] * t["vex"]), "zero_mv": b, "nl_pct": nl, "hys_pct": hys},
                {"s_mv_v": ("rel", 0.005), "zero_mv": ("abs", 0.6), "nl_pct": ("abs", 0.03), "hys_pct": ("abs", 0.03)})
    if task == "encoder":
        e = P["encoder"]
        return ({"dir": "cw" if v["dir"] > 0 else "ccw", "rpm": v["rpm"], "cpr": 4 * e["lines"], "z_ms": 60000 / v["rpm"]},
                {"dir": ("eq", None), "rpm": ("rel", 0.005), "cpr": ("abs", 1), "z_ms": ("rel", 0.005)})
    if task == "imu":
        return ({"bias": v["bias"], "arw": v["arw"], "bi": v["bi"]},
                {"bias": ("abs", 0.01), "arw": ("rel", 0.15), "bi": ("rel", 0.4)})
    if task == "hall":
        return ({"s_mv_a": v["s_mv_a"], "vz": v["vz"], "fb": v["fb"]},
                {"s_mv_a": ("rel", 0.01), "vz": ("abs", 0.003), "fb": ("rel", 0.06)})
    if task == "ntc":
        return ({"b": v["b"], "r25": v["r25"]}, {"b": ("rel", 0.01), "r25": ("rel", 0.01)})
    if task == "tof":
        s1 = v["sigma0_mm"] + v["k_mm_m2"] * 1
        s5 = v["sigma0_mm"] + v["k_mm_m2"] * 25
        return ({"sd1": s1, "sd5": s5, "sd5avg": s5 / math.sqrt(P["tof"]["n_avg"])},
                {"sd1": ("rel", 0.15), "sd5": ("rel", 0.15), "sd5avg": ("rel", 0.2)})
    raise KeyError(task)


LABELS = {
    "s_mv_v": ("灵敏度（额定输出）", "mV/V"), "zero_mv": ("零点（放大器输出）", "mV"), "nl_pct": ("非线性", "%FS"), "hys_pct": ("迟滞", "%FS"),
    "dir": ("转向", ""), "rpm": ("转速", "r/min"), "cpr": ("每转计数（四倍频）", ""), "z_ms": ("Z 脉冲间隔", "ms"),
    "bias": ("零偏", "°/s"), "arw": ("角度随机游走 ARW", "°/√h"), "bi": ("零偏不稳定性", "°/h"),
    "s_mv_a": ("灵敏度", "mV/A"), "vz": ("零点", "V"), "fb": ("−3 dB 带宽", "Hz"),
    "b": ("B 值", "K"), "r25": ("25 ℃ 电阻 R25", "Ω"),
    "sd1": ("1 m 处单次标准差", "mm"), "sd5": ("5 m 处单次标准差", "mm"), "sd5avg": ("5 m 处平均 16 次后的标准差", "mm"),
}


def check(task, seed, ans):
    """逐项核对：[{key, label, unit, given, ok, allow}]（不给出正确值，避免抄答案）"""
    right, tol = answers(task, seed)
    rows = []
    for k, exp in right.items():
        how, lim = tol[k]
        g = (ans or {}).get(k)
        ok = False
        if g not in (None, ""):
            if how == "eq":
                ok = str(g).strip().lower() == str(exp).lower()
            else:
                try:
                    x = float(g)
                    ok = abs(x - exp) <= (lim * abs(exp) if how == "rel" else lim)
                except (TypeError, ValueError):
                    ok = False
        lab, unit = LABELS[k]
        rows.append({"key": k, "label": lab, "unit": unit, "given": g, "ok": ok,
                     "allow": None if how == "eq" else ("±{:g}%".format(lim * 100) if how == "rel" else "±{:g} {}".format(lim, unit))})
    return {"task": task, "rows": rows, "all_ok": all(r["ok"] for r in rows)}


def record_docx(task, seed, ans, data_rows, columns, who=""):
    """实验记录（Word）：任务、学生记录的数据表、结果与核对"""
    import datetime as dt
    import io

    from docx import Document
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt
    d = Document()
    st = d.styles["Normal"]
    st.font.name = "Times New Roman"
    st.font.size = Pt(10.5)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
    for name in ("Title", "Heading 1"):
        d.styles[name].element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), "黑体")
    for sec in d.sections:
        sec.left_margin = sec.right_margin = Cm(2.2)

    def table(rows):
        t = d.add_table(rows=len(rows), cols=len(rows[0]))
        t.style = "Table Grid"
        for i, r in enumerate(rows):
            for k, v in enumerate(r):
                t.cell(i, k).text = str(v)
        d.add_paragraph()
    P = params()
    d.add_heading("虚拟仪器实验记录：{}".format(TITLES[task]), 0)
    d.add_paragraph("{}　{}　问渠数字工厂 · 虚拟仪器".format(who, dt.datetime.now().strftime("%Y-%m-%d %H:%M")))
    d.add_heading("一、被测对象（示例值）", 1)
    d.add_paragraph(P[task].get("note", ""))
    d.add_heading("二、记录的数据", 1)
    rows = [list(columns or [])] + [list(r) for r in (data_rows or [])[:200]]
    if len(rows) > 1 and rows[0]:
        table([[str(x) for x in r] for r in rows])
    else:
        d.add_paragraph("（没有记录数据）")
    d.add_heading("三、结果与核对", 1)
    c = check(task, seed, ans)
    table([["项目", "你的结果", "允许误差", "核对"]] + [["{}（{}）".format(r["label"], r["unit"]) if r["unit"] else r["label"],
                                                   "—" if r["given"] in (None, "") else r["given"], r["allow"] or "相等", "✓" if r["ok"] else "✗"]
                                                  for r in c["rows"]])
    d.add_heading("四、说明", 1)
    d.add_paragraph("传感器与仪器都是模型，参数是示例值；每个学生的参数在名义值附近散布（按学号取种子），数据不能互相套用。"
                    "核对按参数用公式算出的值，允许误差考虑了噪声与有限数据。")
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()
