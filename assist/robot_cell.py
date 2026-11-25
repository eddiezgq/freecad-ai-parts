"""取放类需求（案例 B 裁片上下料，ADR-0115 44.5.1）：节拍、取放点的条件与初筛。

案例 A 的请求一个字不改（录制按请求哈希回放）：AI 列出的机器人类型不是串联臂、也不是移动底盘时，才再问一次取放条件。

条件（每个数附原话引用，代码核对；原话没有的不补）：节拍、单片质量、裁片尺寸、一叠高度、台面离地高度、取放水平距离、
取放两处同高。节拍、单片质量、取放距离三个缺一个就不往下做（要问人）。

初筛（纯函数）：
- 构型的 workspace.points_mm 第 1 点是取料点（一叠最底下一片）、第 2 点是放料点；两点水平距离 = 取放距离（±1 mm），
  原话说同高时两点同高（±1 mm），装在地面时取料点高度 = 台面离地高度；程序再加“一叠最高处”的点查够不够得着；
- 节拍：tasks 里的直线动作首尾相连成一圈（从取料点出发、经过放料点、回到取料点），各段 move_s + dwell_s 之和 ≤ 节拍；
  各段按梯形速度曲线（加速、减速各占 ACCEL 的用时）算末端最高速度与加速度，只报数——能不能做到要选件后按直线模组或电机核。
"""

from __future__ import annotations

import math
from typing import Any

from assist.fea_draft import _in_statement, _value_with_unit

PROMPT_VERSION = "robot-cell/1"
ACCEL = 0.25                    # 加速段、减速段各占一段用时的比例（同 assist.robot_build.ACCEL）
TOL_MM = 1.0
G = 9.80665

_V = {"type": "object", "properties": {"value": {"type": "number"}, "unit": {"type": "string"}, "quote": {"type": "string"}},
      "required": ["value", "quote"]}
FIELDS = (                       # (键, 标准单位字段, 名称, 单位)
    ("cycle", "cycle_s", "节拍", "s"),
    ("part_mass", "mass_kg", "单片最大质量", "kg"),
    ("part_length", "length_mm", "裁片最大长度", "mm"),
    ("part_width", "length_mm", "裁片最大宽度", "mm"),
    ("stack_height", "length_mm", "一叠最高", "mm"),
    ("work_height", "length_mm", "台面离地高度", "mm"),
    ("pick_to_place", "length_mm", "取料区到放料区的水平距离", "mm"),
)
REQUIRED = ("cycle", "part_mass", "pick_to_place")
CELL_TOOL = {"name": "list_cell_conditions", "description": "列出取放类机器人的节拍与取放条件（每个数附原话引用）", "input_schema": {
    "type": "object", "properties": {
        "cycle": {**_V, "description": "节拍：取一件、放好、回到取料位的总时间（s）"},
        "part_mass": {**_V, "description": "单件最大质量（原话的单位，如 g、kg）"},
        "part_length": {**_V, "description": "单件最大长度（mm）"},
        "part_width": {**_V, "description": "单件最大宽度（mm）"},
        "stack_height": {**_V, "description": "工件叠放时一叠的最大高度（mm）"},
        "work_height": {**_V, "description": "取料、放料台面离地高度（mm）"},
        "pick_to_place": {**_V, "description": "取料区中心到放料区中心的水平距离（mm）"},
        "same_height": {"type": "object", "properties": {"quote": {"type": "string"}}, "required": ["quote"],
                        "description": "原话说取料、放料两处台面同高时，给出引用"},
        "questions": {"type": "array", "items": {"type": "string"}, "description": "原话没说清、要问工程师的"}},
    "required": []}}
SYSTEM_CELL = """你在帮机器人工程师设计一台取放（上下料）机器人。工程师原话里的机器人类型、负载、精度已经列过了；
现在只列节拍与取放条件，程序会逐项核对。
规则：
1. 每个数都要给原话里的引用（照抄原话里连续的一段），数值和单位照原话写；原话没有的数不要补、不要估、不要换算。
2. 原话没说清的写进 questions。
必须调用一次工具 list_cell_conditions。"""


def applies(cond: dict) -> bool:
    """要不要问取放条件：AI 列出的类型不是串联臂、也不是移动底盘"""
    return cond.get("kind") not in (None, "serial_arm", "mobile_base")


def cell_request(statement: str, *, model: str) -> dict:
    return {"model": model, "prompt_version": PROMPT_VERSION, "system": SYSTEM_CELL,
            "user": f"工程师原话：\n{statement}", "tool": CELL_TOOL}


def check_cell(ti: Any, statement: str) -> tuple[dict, list[str], list[str], list[dict]]:
    """核对取放条件 → (条件, 退回的项, 缺的项, 核对通过的引用)"""
    cond: dict = {}
    rej: list[str] = []
    quotes: list[dict] = []
    if not isinstance(ti, dict):
        return cond, ["取放条件不是一个对象"], [w for k, _, w, _ in FIELDS if k in REQUIRED], quotes
    for key, field, what, unit in FIELDS:
        v = ti.get(key)
        if v is None:
            continue
        x, why = _value_with_unit(v, statement, field)
        if why:
            rej.append(f"{what}：{why}")
        elif x <= 0:
            rej.append(f"{what}：要大于 0")
        else:
            cond[key] = x
            quotes.append({"what": what, "value": x, "unit": unit, "quote": v.get("quote")})
    sh = ti.get("same_height")
    if isinstance(sh, dict):
        if _in_statement(sh.get("quote"), statement):
            cond["same_height"] = True
            quotes.append({"what": "取放两处同高", "value": "是", "unit": "", "quote": sh["quote"]})
        else:
            rej.append("取放两处同高：引用不在原话里")
    miss = [w for k, _, w, _ in FIELDS if k in REQUIRED and k not in cond and not any(r.startswith(w) for r in rej)]
    return cond, rej, miss, quotes


NAMES = {"cycle": "节拍 s", "part_mass": "单片最大质量 kg", "part_length": "裁片最大长度 mm", "part_width": "裁片最大宽度 mm",
         "stack_height": "一叠最高 mm", "work_height": "台面离地 mm", "pick_to_place": "取料区到放料区水平距离 mm",
         "same_height": "取放两处同高"}


def notes(cond: dict) -> str:
    """给 AI 的取放写法（只在取放类需求里出现）"""
    stack = f"程序会再加“一叠最高处”（取料点上方 {cond['stack_height']:g} mm）查够不够得着。" if "stack_height" in cond else ""
    return ("取放的写法（程序按这个核）：\n"
            "1. workspace.points_mm 第 1 点写取料点（一叠最底下一片，取料区中心），第 2 点写放料点（放料区中心），都在基座坐标系里；"
            f"两点的水平距离要等于取放距离。{stack}\n"
            "2. tasks 写一个完整节拍：全部用 cartesian_move、首尾相连（上一段的 to_mm = 下一段的 from_mm），从取料点出发、经过放料点、回到取料点；"
            "中间可以有抬起、平移、放下各段；每段写 move_s，取、放时的停留写在 dwell_s。各段 move_s + dwell_s 之和要不大于节拍。\n"
            f"3. 程序按梯形速度曲线（加速、减速各占每段用时的 {ACCEL:g}）算各段末端的最高速度与加速度，选件后按直线模组或电机核。\n"
            "4. 零件库现在只有转动的伺服电机、减速器、一体化关节模组；直线模组与抓手在选件前从公开目录整本导入，不要写零件型号。"
            "末端型式（真空吸盘、针刺或其他）由你提并说明理由；抓取力、伤不伤布料在选件后按公开数据核，查不到的记待确认。")


def _item(name, status, value=None, limit=None, note=""):
    d = {"item": name, "status": status}
    if value is not None:
        d["value"] = value
    if limit is not None:
        d["limit"] = limit
    if note:
        d["note"] = note
    return d


def _dist(a, b) -> float:
    return math.dist(a, b)


def trapezoid(length_mm: float, move_s: float, accel: float = ACCEL) -> tuple[float, float]:
    """一段直线动作按梯形速度曲线：(最高速度 m/s, 加速度 m/s²)；加速、减速各占 accel × move_s"""
    ta = accel * move_s
    v = length_mm / 1000.0 / (move_s - ta)
    return v, v / ta


def points(concept: dict, cond: dict) -> tuple[list[dict], list[list[float]]]:
    """取放点的核对项，以及要加进工作空间查可达的点（一叠最高处）"""
    pts = ((concept.get("workspace") or {}).get("points_mm")) or []
    if len(pts) < 2:
        return [_item("取放点", "fail", note="workspace.points_mm 前两点要写取料点、放料点")], []
    pick, place = [float(x) for x in pts[0]], [float(x) for x in pts[1]]
    items = []
    d = math.hypot(place[0] - pick[0], place[1] - pick[1])
    L = cond["pick_to_place"]
    items.append(_item("取放水平距离", "pass" if abs(d - L) <= TOL_MM else "fail", round(d, 1), f"{L:g} ± {TOL_MM:g} mm"))
    if cond.get("same_height"):
        dz = place[2] - pick[2]
        items.append(_item("取放两处同高", "pass" if abs(dz) <= TOL_MM else "fail", round(dz, 1), f"0 ± {TOL_MM:g} mm",
                           "放料点比取料点高（mm）"))
    mount = (concept.get("base") or {}).get("mount")
    if "work_height" in cond and mount == "floor":
        items.append(_item("取料点高度（装在地面，基座原点在地面上）", "pass" if abs(pick[2] - cond["work_height"]) <= TOL_MM else "fail",
                           round(pick[2], 1), f"{cond['work_height']:g} ± {TOL_MM:g} mm"))
    extra = [[pick[0], pick[1], pick[2] + cond["stack_height"]]] if "stack_height" in cond else []
    return items, extra


def cycle(concept: dict, cond: dict) -> list[dict]:
    """节拍：直线动作首尾相连成一圈、经过取料点和放料点，用时之和 ≤ 节拍；报各段最高速度与加速度"""
    pts = ((concept.get("workspace") or {}).get("points_mm")) or []
    moves = [t for t in concept.get("tasks") or [] if t.get("type") == "cartesian_move"]
    if not moves:
        return [_item("节拍", "fail", note="tasks 里没有直线动作（cartesian_move），算不了节拍")]
    if len(moves) != len(concept.get("tasks") or []):
        return [_item("节拍", "fail", note="节拍要全部用直线动作（cartesian_move）写")]
    bad = [k + 1 for k in range(len(moves)) if _dist(moves[k]["to_mm"], moves[(k + 1) % len(moves)]["from_mm"]) > TOL_MM]
    if bad:
        return [_item("节拍", "fail", note=f"直线动作没有首尾相连成一圈：第 {'、'.join(map(str, bad))} 段的终点不是下一段的起点"
                                         "（最后一段要回到第一段的起点）")]
    ends = [m["from_mm"] for m in moves]
    if len(pts) >= 2:
        miss = [w for w, p in (("取料点", pts[0]), ("放料点", pts[1])) if min(_dist(p, e) for e in ends) > TOL_MM]
        if miss:
            return [_item("节拍", "fail", note=f"一圈动作没有经过{'、'.join(miss)}（workspace.points_mm 的前两点）")]
    total = sum(float(m["move_s"]) + float(m.get("dwell_s") or 0.0) for m in moves)
    segs, vmax, amax = [], 0.0, 0.0
    for m in moves:
        L = _dist(m["from_mm"], m["to_mm"])
        v, a = trapezoid(L, float(m["move_s"]))
        vmax, amax = max(vmax, v), max(amax, a)
        segs.append(f"{m['name']} {L:.0f} mm / {float(m['move_s']):g} s（最高 {v:.2f} m/s、{a:.1f} m/s²）")
    lim = cond["cycle"]
    out = [_item("节拍", "pass" if total <= lim + 1e-9 else "fail", round(total, 3), f"≤ {lim:g} s",
                 f"{len(moves)} 段直线动作加停留；" + "；".join(segs))]
    out.append(_item("节拍里末端最高速度与加速度", "unknown", f"{vmax:.2f} m/s、{amax:.1f} m/s²", None,
                     "选件后按直线模组或电机的最高速度、推力核（这一步判不了）"))
    if "part_mass" in cond:
        out.append(_item("抓取力", "unknown", f"至少 {cond['part_mass'] * (G + amax) * 2:.2f} N", None,
                         f"单片 {cond['part_mass'] * 1000:g} g ×（g + {amax:.1f} m/s²）× 安全系数 2；选件后按抓手的公开数据核"))
    return out
