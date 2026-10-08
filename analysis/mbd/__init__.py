"""运动学 · 多体动力学（ADR-0056，M10 第二步）：机构与机械臂在给定运动下各关节需要的力矩、转速、功率。

设置（对外单位：长度 mm、角度 °、时间 s、质量 kg、力 N、力矩 N·m、转速 rpm）：
  model:
    {"kind": "mechanism", "id": "C-LNK-SLIDER", "params": {...}}   常用机构（参数为米，见 mechanisms.DEFAULTS）
    {"kind": "arm", "base_height_mm", "links": [{"length_mm", "mass_kg"}], "joint_masses_kg": [...], "payload_kg"}
    {"kind": "mjcf", "xml": "<mujoco>…</mujoco>"}                   自带模型（SI 单位）
  duration_s（≤ 60）、gravity（缺省 true）、sample_hz（≤ 5000，记录点数 ≤ 20000；高速机构每转要几十个点）
  initial: {关节: 初值}（转动关节 °，移动关节 mm）
  drives: [{"joint", "kind": "move", "to", "t0_s", "t1_s", "accel_ratio"}    点到点（梯形速度，加减速各占 accel_ratio）
           {"joint", "kind": "speed", "value"}（转动 rpm，移动 mm/s）、{"joint", "kind": "sine", "amp", "freq_hz"}、
           {"joint", "kind": "hold"}、{"joint", "kind": "torque", "value"}（N·m 或 N）]
  payloads: [{"body", "mass_kg", "pos_mm"}]、forces: [{"body", "force_n": [x, y, z], "pos_mm"}]

结果 data：
  drives: 每个驱动的峰值、均方根（N·m 或 N）、最高转速（rpm 或 mm/s）、峰值与平均功率（W）、最大等效惯量（kg·m²）
  series: 时间与各驱动关节的位置、速度、驱动力矩（按 sample_hz 记录）
  static: 机械臂初始姿态的重力矩（几何算法，与动力学求解独立，用于核对）
"""

from __future__ import annotations

import math
import time
from collections.abc import Mapping

from analysis.common import result

MODULE = {
    "id": "mbd", "name": "运动学 · 多体动力学", "version": "1",
    "description": "机构与机械臂在给定运动下的关节力矩、转速、功率；结果可直接生成选型需求",
    "python": ["mujoco", "numpy"], "solvers": [], "install": '安装：pip install -e ".[mbd]"（FreeCAD 中用 FreeCAD 自带的 Python 安装）',
}
LIMITATIONS = ["刚体动力学：构件不变形，关节无间隙", "给定运动的驱动按理想伺服（跟踪误差见 tracking_error）",
               "机械臂模型为参数化串联臂：杆为均布质量，关节模组为集中质量；质量由使用者给出"]
RPM = 60 / (2 * math.pi)


class SetupError(ValueError):
    pass


def _spec(model: Mapping):
    from analysis.mbd import arm, core, mechanisms

    kind = model.get("kind") if isinstance(model, Mapping) else None
    if kind == "mechanism":
        mid = model.get("id")
        try:
            return core.load_spec(xml=mechanisms.mjcf(mid, model.get("params"))), mid
        except ValueError as exc:
            raise SetupError(str(exc)) from exc
    if kind == "arm":
        try:
            return core.load_spec(xml=arm.mjcf(model)), None
        except arm.ArmError as exc:
            raise SetupError(str(exc)) from exc
    if kind == "mjcf":
        if not isinstance(model.get("xml"), str) or "<mujoco" not in model["xml"]:
            raise SetupError("mjcf 模型须给 xml 文字")
        return core.load_spec(xml=model["xml"]), None
    raise SetupError("model.kind 须为 mechanism、arm 或 mjcf")


def _slide_joints(spec) -> set[str]:
    import mujoco

    return {j.name for j in spec.joints if j.type == mujoco.mjtJoint.mjJNT_SLIDE}


def _internal(setup: Mapping, slides: set[str]) -> dict:
    """对外单位 → 内部 SI。"""
    def ang(j, v):
        return float(v) / 1000 if j in slides else math.radians(float(v))

    def vel(j, v):  # rpm 或 mm/s
        return float(v) / 1000 if j in slides else float(v) / RPM

    s: dict = {"duration_s": float(setup.get("duration_s", 2)), "gravity": bool(setup.get("gravity", True)),
               "sample_hz": float(setup.get("sample_hz", 100))}
    s["initial"] = {j: ang(j, v) for j, v in (setup.get("initial") or {}).items()}
    drives = []
    for d in setup.get("drives") or []:
        j, k = d.get("joint"), d.get("kind")
        if k == "move":
            drives.append({"joint": j, "kind": "move", "to": ang(j, d["to"]), "t0": float(d.get("t0_s", 0)),
                           "t1": float(d["t1_s"]), "accel": float(d.get("accel_ratio", 0.25))})
        elif k == "speed":
            drives.append({"joint": j, "kind": "speed", "value": vel(j, d["value"])})
        elif k == "sine":
            drives.append({"joint": j, "kind": "sine", "amp": ang(j, d["amp"]), "freq": float(d["freq_hz"])})
        elif k in ("hold", "torque"):
            drives.append({"joint": j, "kind": k, **({"value": float(d["value"])} if k == "torque" else {})})
        else:
            raise SetupError(f"不认识的驱动方式：{k!r}")
    s["drives"] = drives
    s["payloads"] = [{"body": p["body"], "mass": float(p["mass_kg"]), "pos": [x / 1000 for x in p.get("pos_mm") or [0, 0, 0]]}
                     for p in setup.get("payloads") or []]
    s["forces"] = [{"body": f["body"], "force": [float(x) for x in f["force_n"]],
                    "pos": [x / 1000 for x in f.get("pos_mm") or [0, 0, 0]]} for f in setup.get("forces") or []]
    if setup.get("friction"):
        s["friction"] = dict(setup["friction"])
    return s


def _downsample(xs, n=600):
    step = max(1, len(xs) // n)
    return [float(x) for x in xs[::step]]


def run(setup: dict) -> dict:
    from analysis.mbd import core, mechanisms

    t0 = time.time()
    try:
        spec, mid = _spec(setup.get("model") or {})
        slides = _slide_joints(spec)
        internal = _internal(setup, slides)
        if mid is not None:
            internal = mechanisms.prepare_setup(mid, (setup.get("model") or {}).get("params"), internal)
        summ, ch, _anim = core.simulate(spec, internal)
    except (SetupError, core.SetupError, KeyError, TypeError, ValueError) as exc:
        return result.failed("mbd", MODULE["version"], setup, f"设置有误：{exc}")
    drives, series = [], {"t_s": _downsample(ch["t"])}
    for d in summ["drives"]:
        j, slide = d["joint"], d["joint"] in slides
        drives.append({
            "joint": j, "kind": d["kind"], "unit_force": "N" if slide else "N·m",
            "peak": d["peak"], "rms": d["rms"],
            "speed_max": d["speed_max"] * (1000 if slide else RPM), "unit_speed": "mm/s" if slide else "rpm",
            "power_peak_w": d["power_peak"], "power_mean_w": d["power_mean"], "inertia_max_kgm2": d["inertia_max"]})
        k = 1000 if slide else 180 / math.pi
        series[j] = {"q": _downsample(ch["q." + j] * k), "speed": _downsample(ch["qd." + j] * (1000 if slide else RPM)),
                     "drive": _downsample(ch["drive." + j])}
    data = {"drives": drives, "series": series, "tracking_error": summ["tracking_error_max"],
            "timestep_s": summ["timestep_s"]}
    try:
        import mujoco
        import numpy as np

        model, _ = core.build(_spec(setup.get("model") or {})[0], {**internal, "drives": []})
        d0 = mujoco.MjData(model)
        core._initial(model, d0, internal, [])
        data["static"] = {"gravity_torque_nm": {j: -v for j, v in core.gravity_torques(model, np.array(d0.qpos)).items()}}
    except Exception as exc:  # noqa: BLE001 — 核对附加项，失败不影响主结果
        data["static_error"] = str(exc)[:200]
    import mujoco

    return result.make("mbd", MODULE["version"], setup, data, limitations=LIMITATIONS,
                       solver={"name": "MuJoCo", "version": mujoco.__version__}, elapsed_s=time.time() - t0)


def requirement(res: Mapping, joint: str, *, base: Mapping | None = None) -> dict:
    """动力学结果中一个转动关节 → 选型需求（requirement.schema.json）：连续扭矩取均方根、峰值取峰值、转速取最高转速、
    负载惯量取运动中的最大等效惯量。安全系数、供电、环境等沿用 base。"""
    d = next((x for x in res.get("data", {}).get("drives", []) if x["joint"] == joint), None)
    if d is None:
        raise SetupError(f"结果中没有关节 {joint} 的驱动")
    if d["unit_force"] != "N·m":
        raise SetupError(f"{joint} 是移动关节，不能生成旋转关节的选型需求")
    req = dict(base or {})
    req.update({"output_torque_cont_nm": round(d["rms"], 3), "output_torque_peak_nm": round(d["peak"], 3),
                "output_speed_rpm": round(d["speed_max"], 3), "load_inertia_kgm2": round(d["inertia_max_kgm2"], 6)})
    req.setdefault("statement", f"动力学结果：关节 {joint} 峰值 {d['peak']:.1f} N·m、均方根 {d['rms']:.1f} N·m、"
                                f"最高 {d['speed_max']:.1f} rpm")
    return req


def energy_swing(res: Mapping, joint: str) -> dict:
    """转动驱动关节一转内的最大盈亏功（《机械原理》飞轮设计，ADR-0062）。

    由记录的转角与驱动力矩积分 W(θ) = ∫T dθ，去掉平均力矩做的功后取最大值减最小值。取最后一整转；记录要足够密
    （每转几十个点，见 sample_hz）。返回 {delta_e_j, mean_torque_nm, points_per_rev}；不满一转时抛 SetupError。
    """
    import numpy as np

    s = res.get("data", {}).get("series", {}).get(joint)
    if not s:
        raise SetupError(f"结果中没有关节 {joint} 的记录")
    q = np.radians(np.asarray(s["q"], float))
    tau = np.asarray(s["drive"], float)
    if len(q) < 3 or abs(q[-1] - q[0]) < 2 * np.pi:
        raise SetupError("记录不满一整转，算不了盈亏功")
    sign = 1.0 if q[-1] > q[0] else -1.0
    i0 = int(np.searchsorted(sign * q, sign * q[-1] - 2 * np.pi))       # 最后一整转的起点
    qq, tt = q[i0:], tau[i0:]
    if len(qq) < 24:
        raise SetupError(f"一转只记录了 {len(qq)} 个点，太稀：把 sample_hz 调高（每转至少 24 个点）")
    w = np.concatenate([[0.0], np.cumsum((tt[1:] + tt[:-1]) / 2 * np.diff(qq))])
    mean = w[-1] / (qq[-1] - qq[0])
    dev = w - mean * (qq - qq[0])
    return {"delta_e_j": float(dev.max() - dev.min()), "mean_torque_nm": float(mean), "points_per_rev": len(qq)}
