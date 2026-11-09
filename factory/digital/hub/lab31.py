# -*- coding: utf-8 -*-
"""实验 31“关节终检抱闸报警的排查”（第 123 轮，机器人厂）：六个任务的自动评分（60 分）+ 报告（40 分）。

学生是关节模组终检的质量工程师。每人分到 3 台终检报故障 7（抱闸故障）的关节模组（L、M、S 各一台），三种故障各一种：
抱闸线断、抱闸线圈短路、驱动板抱闸开关管 Q7 击穿（谁是哪种按用户名打乱）。测试记录直接取第 114 轮 Renode 仿真的真实输出
（designs/drv-joint-b/fw/out/sim_motor.json 的场景 ⑮ brk_open、⑯ brk_short、⑰ brk_fet），不另造数据。
学生要：① 解报警帧（故障码、子码）；② 判坏件；③ 读波形（线圈短路那台：报警到抱住、到关输出各多少 ms）；④ 说安全逻辑
（Q7 击穿那台心跳写“抱闸抱住”，固件为什么不关输出）；⑤ 定处置；⑥ 复测放行。任务成绩编号加前缀 l31_。"""
import json
import os
import re
import zlib

from sim import errors as ERR

FW_SIM = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                      "designs", "drv-joint-b", "fw", "out", "sim_motor.json")
SCEN = ("brk_open", "brk_short", "brk_fet")
SIZES = ("L", "M", "S")
TRUTH = {                                 # 每种故障的标准答案：子码（报警帧 [3]，最后一条）、坏件、处置
    "brk_open": {"sub": 1, "part": "open", "action": "harness"},
    "brk_short": {"sub": 2, "part": "short", "action": "motor"},
    "brk_fet": {"sub": 3, "part": "fet", "action": "board"},
}
PARTS = [
    ("open", "抱闸线圈或线束断开（伺服电机里的抱闸线圈、到驱动板 J6 插头这一路）"),
    ("short", "抱闸线圈短路（伺服电机里的抱闸线圈）"),
    ("fet", "驱动板上抱闸开关管 Q7 击穿常通"),
    ("ok", "没有坏，是测试台误报"),
]
ACTIONS = [
    ("harness", "先查 J6 插头和抱闸线束、重插或重新压接；线圈本身断了再换伺服电机"),
    ("motor", "换伺服电机（抱闸在电机里），驱动板留用"),
    ("board", "换驱动板 DRV-JOINT-B，坏板退电路板厂分析"),
    ("pass", "清故障后直接放行"),
]
T4_CHOICES = [
    ("cmd_vs_current", "心跳里的“抱闸抱住”只是固件发出的抱闸指令；线圈电流一直在，说明抱闸其实松着，这时关输出摆臂会落下，所以电机在原地一直顶着"),
    ("delay", "固件还在等 60 ms 的抱闸时间，等够了就会关输出"),
    ("bug", "这是固件的错误，应该立刻关输出"),
    ("comm", "主站发了“停”，固件在执行受控停车"),
]
BRAKE_RETEST = {"L": 223.6, "M": 111.4, "S": 56.1}     # 复测的抱闸保持力矩（示例值，N·m，与清单规格对照）
BRAKE_SPEC = {"L": (160, 320), "M": (80, 160), "S": (40, 80)}
TASKS = [
    {"id": "l31_t1", "points": 10, "title": "解报警帧",
     "desc": "三台关节的报文里各找出报警帧（ID 0x081），按协议摘录写出故障码和子码。有两条报警的，填最后一条。",
     "hint": "报警帧数据第 [0] 字节是故障码，第 [3] 字节是子码（1 断线、2 过流、3 抱不住）。数据按十六进制两位一字节读。"},
    {"id": "l31_t2", "points": 10, "title": "判坏件",
     "desc": "三台各坏在哪？",
     "hint": "看抱闸线圈电流：一直是 0；冲到额定的好几倍；撤了驱动电流还在——分别说明什么？"},
    {"id": "l31_t3", "points": 10, "title": "读波形",
     "desc": "线圈短路的那台：从报警帧发出，到线圈电流降下来（抱住）用了多少 ms？到关输出（输出开关变 0）用了多少 ms？",
     "hint": "报警时刻看报文表 0x081 那一行的时间。固件判“抱住”：报警（撤抱闸驱动）后过了 60 ms，且线圈电流已连续 20 ms 低于额定的 30%（0.126 A）。关输出看“输出开关”那条线变 0。"},
    {"id": "l31_t4", "points": 10, "title": "安全逻辑",
     "desc": "开关管 Q7 击穿的那台，心跳帧里写着“抱闸抱住”，固件却一直不关输出。为什么？",
     "hint": "心跳 [3] 字节报的是什么？同一时刻抱闸线圈电流是多少？"},
    {"id": "l31_t5", "points": 10, "title": "定处置",
     "desc": "三台各怎么返修？",
     "hint": "抱闸线圈在伺服电机里，开关管 Q7 在驱动板上；断线先查最便宜、最常见的地方。"},
    {"id": "l31_t6", "points": 10, "title": "复测放行",
     "desc": "处置定对后，点“复测”：三台按返修后的状态重测上电抱闸时序和抱闸保持力矩，合格才放行。",
     "hint": "要先把任务 5 做对。"},
]
REPORT_POINTS = 40

_cache = {}


def sim():
    """第 114 轮固件仿真结果；读不到返回 None（页面说明缺失，不编数据）"""
    if "d" not in _cache:
        try:
            with open(FW_SIM, encoding="utf-8") as f:
                d = json.load(f)
            _cache["d"] = {s["id"]: s for s in d["scenarios"]}
        except (OSError, ValueError, KeyError):
            _cache["d"] = None
    return _cache["d"]


def _code(user):
    return "{:04X}".format(zlib.crc32(("lab31|" + user).encode()) % 0xFFFF)


def case(user):
    """三台关节：规格 L/M/S 各一台，故障分配按用户名打乱"""
    c = _code(user)
    k = zlib.crc32(c.encode())
    order = list(SCEN)
    perms = [(0, 1, 2), (0, 2, 1), (1, 0, 2), (1, 2, 0), (2, 0, 1), (2, 1, 0)]
    p = perms[k % 6]
    joints = []
    for i, size in enumerate(SIZES):
        joints.append({"serial": "WQJ-{}-L31-{}-{}".format(size, c, i + 1), "size": size, "scenario": order[p[i]]})
    return {"code": c, "joints": joints}


def alarms(sc):
    """报警帧 → [(t, 故障码, 子码, 原始数据)]"""
    out = []
    for f in sc["frames"]:
        if f["id"] == "0x081":
            b = bytes.fromhex(f["data"])
            out.append((f["t"], b[0], b[3] if len(b) > 3 else None, f["data"]))
    return out


def fw_times():
    """固件自己记的（仿真核对项“先抱住、后关输出”）：报警 → 抱住、报警 → 关输出（ms）"""
    s = sim()["brk_short"]
    det = next(c["detail"] for c in s["checks"] if c["name"].startswith("先抱住"))
    m = re.search(r"(\d+)\s*ms 抱住.*?(\d+)\s*ms 关输出", det)
    return {"engage_ms": int(m.group(1)), "off_ms": int(m.group(2))}


def short_times():
    """任务 3 的标准答案：按提示的判据从页上显示的波形算（与固件自己记的差在 ±15 ms 内，测试核对）"""
    return from_page(record(sim()["brk_short"]))


def from_page(rec):
    """学生照提示从页上的波形算（测试用来核对这道题做得出来）：报警 → 抱住、报警 → 关输出（ms）"""
    se = rec["series"]
    ta = next(f["t"] for f in rec["frames"] if f["id"] == "0x081")
    low = None
    eng = None
    for t, i in zip(se["t"], se["brake_i"]):
        if t <= ta:
            continue
        low = (low if low is not None else t) if i < 0.3 * 0.42 else None
        if low is not None and t - low >= 0.020 and t - ta >= 0.060:
            eng = t
            break
    off = next(t for t, m in zip(se["t"], se["moe"]) if t > ta and m == 0)
    return {"engage_ms": round((eng - ta) * 1000), "off_ms": round((off - ta) * 1000)}


def _thin(series, n=240):
    keys = ("t", "brake_i", "joint", "moe", "brake")
    m = len(series["t"])
    step = max(1, -(-m // n))
    idx = list(range(0, m, step))
    if idx[-1] != m - 1:
        idx.append(m - 1)
    return {k: [series[k][i] for i in idx] for k in keys}


def record(sc):
    """页面用的测试记录：原始报文（不带中文解释）、三条波形"""
    return {"desc": "关节终检：上电对零 → 转到 90°（摆臂有重力）→ 保持；报故障就停在那里。",
            "frames": [{"t": f["t"], "dir": f["dir"], "id": f["id"], "data": f["data"]} for f in sc["frames"]],
            "series": _thin(sc["series"])}


def _get(db, user, tid):
    return db.one("select * from task_result where user_name=%s and task_id=%s", (user, tid))


def _save(db, user, tid, score, evidence):
    db.x("insert into task_result (user_name, task_id, score, evidence) values (%s,%s,%s,%s) "
         "on conflict (user_name, task_id) do update set score=greatest(task_result.score, excluded.score), "
         "evidence=excluded.evidence, done_at=now()", (user, tid, score, json.dumps(evidence, ensure_ascii=False, default=str)))


def _per_joint(ans, cs, field, truth_of):
    """按序列号逐台判：ans = {序列号: 值} → 对了几台"""
    n = 0
    for j in cs["joints"]:
        v = ans.get(j["serial"])
        if isinstance(v, dict):
            v = v.get(field)
        if truth_of(j, v):
            n += 1
    return n


def _int(v):
    try:
        return int(str(v).strip(), 0) if str(v).strip().lower().startswith("0x") else int(float(v))
    except (TypeError, ValueError):
        return None


def retest(cs):
    """复测记录：上电抱闸时序（第 114 轮场景 ⑪ 的结果）+ 抱闸保持力矩（示例值）"""
    boot = sim()["brk_boot"]
    rows = []
    for j in cs["joints"]:
        lo, hi = BRAKE_SPEC[j["size"]]
        v = BRAKE_RETEST[j["size"]]
        rows.append({"serial": j["serial"], "sequence_ok": bool(boot["passed"]), "brake_hold": v, "lo": lo, "hi": hi,
                     "ok": bool(boot["passed"]) and lo <= v <= hi})
    return {"rows": rows, "sequence": boot["name"], "checks": [c["name"] for c in boot["checks"]],
            "note": "时序取第 114 轮固件仿真场景 ⑪ 的结果；保持力矩是示例值（规格与机器人厂关节测试一致）。"}


def answer(db, user, tid, ans):
    if sim() is None:
        raise RuntimeError("固件仿真结果缺失")
    cs = case(user)
    if tid == "l31_t1":
        n = 0
        for j in cs["joints"]:
            v = ans.get(j["serial"]) if isinstance(ans.get(j["serial"]), dict) else {}
            last = alarms(sim()[j["scenario"]])[-1]
            if _int(v.get("code")) == last[1] and _int(v.get("sub")) == last[2]:
                n += 1
        sc = round(10 * n / 3)
        _save(db, user, tid, sc, {"answer": ans, "right": n})
        return {"score": sc, "of": 10, "feedback": "正确：三台都是故障 7（抱闸），子码各不相同。" if n == 3 else
                "对了 {} 台。报警帧 0x081：第 [0] 字节故障码，第 [3] 字节子码；两条报警的填最后一条。".format(n)}
    if tid == "l31_t2":
        n = _per_joint(ans, cs, "part", lambda j, v: v == TRUTH[j["scenario"]]["part"])
        sc = round(10 * n / 3)
        _save(db, user, tid, sc, {"answer": ans, "right": n})
        return {"score": sc, "of": 10, "feedback": "正确。" if n == 3 else
                "对了 {} 台。线圈电流一直 0 → 回路断；冲到额定好几倍 → 线圈短路；撤了驱动还有电流 → 开关管常通。".format(n)}
    if tid == "l31_t3":
        t = short_times()
        e, o = _int(ans.get("engage_ms")), _int(ans.get("off_ms"))
        sc = (5 if e is not None and abs(e - t["engage_ms"]) <= 15 else 0) + (5 if o is not None and abs(o - t["off_ms"]) <= 15 else 0)
        _save(db, user, tid, sc, {"answer": ans, "truth": t})
        return {"score": sc, "of": 10, "feedback": "正确：先抱住、再关输出，摆臂不落。" if sc == 10 else
                "从 0x081 那一行的时间算起（误差 ±15 ms 以内都算对）；抱住看线圈电流降到接近 0，关输出看输出开关变 0。"}
    if tid == "l31_t4":
        sc = 10 if ans.get("choice") == "cmd_vs_current" else 0
        _save(db, user, tid, sc, {"answer": ans})
        return {"score": sc, "of": 10, "feedback": "正确：报文说的是指令，电流说的是事实。" if sc == 10 else
                "比一比心跳 [3] 字节和同一时刻的线圈电流。"}
    if tid == "l31_t5":
        n = _per_joint(ans, cs, "action", lambda j, v: v == TRUTH[j["scenario"]]["action"])
        sc = round(10 * n / 3)
        _save(db, user, tid, sc, {"answer": ans, "right": n})
        return {"score": sc, "of": 10, "feedback": "正确：可以复测了。" if n == 3 else
                "对了 {} 台。抱闸线圈在伺服电机里，开关管在驱动板上；断线先查插头和线束。".format(n)}
    if tid == "l31_t6":
        r5 = _get(db, user, "l31_t5")
        if not r5 or r5["score"] < 10:
            return {"score": 0, "of": 10, "feedback": "先把任务 5（定处置）做对，再复测。"}
        rt = retest(cs)
        sc = 10 if all(r["ok"] for r in rt["rows"]) else 0
        _save(db, user, tid, sc, {"retest": rt})
        return {"score": sc, "of": 10, "feedback": "三台复测合格，放行。" if sc == 10 else "复测没过。", "retest": rt}
    raise KeyError(tid)


def status(db, user):
    cs = case(user)
    s = sim()
    rows = {r["task_id"]: r for r in db.q("select * from task_result where user_name=%s and task_id like 'l31_%%'", (user,))}
    tasks = []
    for t in TASKS:
        r = rows.get(t["id"])
        tasks.append(dict(t, score=r["score"] if r else 0, done=bool(r and r["score"] >= t["points"]), evidence=r["evidence"] if r else None))
    joints = []
    for j in cs["joints"]:
        d = {"serial": j["serial"], "size": j["size"], "item": "WQJ-" + j["size"], "brake_nominal": ERR.BRAKE_NOMINAL[j["size"]]}
        if s:
            d["record"] = record(s[j["scenario"]])
        joints.append(d)
    r6 = rows.get("l31_t6")
    return {"user": user, "tasks": tasks, "score": sum(t["score"] for t in tasks), "of": sum(t["points"] for t in TASKS),
            "report_points": REPORT_POINTS, "sim_missing": s is None, "joints": joints,
            "parts": [{"value": k, "label": v} for k, v in PARTS], "actions": [{"value": k, "label": v} for k, v in ACTIONS],
            "t4_choices": [{"value": k, "label": v} for k, v in T4_CHOICES],
            "retest": retest(cs) if (s and r6 and r6["score"] >= 10) else None,
            "protocol": [
                "0x081 报警（驱动板 → 主站，出故障时立即发一次）：[0] 故障码，[1..2] 测到的线圈电流 0.01 A（int16，小端），[3] 子码：1 断线、2 过流、3 抱不住（开关管常通）",
                "0x701 心跳（10 Hz）：[0] 状态（0 初始化、1 就绪、2 运行、3 故障），[1..2] 母线电压 0.1 V（uint16，小端），[3] 抱闸指令：0 抱住、1 松开",
                "0x181 状态（100 Hz）：[0] 状态，[1] 故障码，[2..3] 关节角 0.01°，[4..5] 电机转速 rpm，[6..7] q 轴电流 0.01 A（均为 int16，小端）",
                "0x201 指令（主站 → 驱动板）：[0] 模式 0 停、1 速度、2 位置、3 清故障，[1..4] 目标（int32）",
                "故障码 7 = 抱闸故障：先在原地保持，测到线圈电流降下来（确实抱住）才关输出；抱不住就一直保持。",
            ]}


def class_view(db):
    rows = db.q("select user_name, task_id, score from task_result where task_id like 'l31_t%%'")
    out = {}
    for r in rows:
        out.setdefault(r["user_name"], {})[r["task_id"]] = r["score"]
    return [{"user": k, "scores": v, "total": sum(v.values())} for k, v in sorted(out.items())]
