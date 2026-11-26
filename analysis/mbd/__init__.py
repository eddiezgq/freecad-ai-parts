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
           {"joint", "kind": "hold"}、{"joint", "kind": "torque", "value"}（N·m 或 N）、
           {"joint", "kind": "path", "segments": [{"to", "t0_s", "t1_s", "accel_ratio"}, …]}  多段点到点（取—放节拍，ADR-0115 44.5.5）]
  payloads: [{"body", "mass_kg", "pos_mm"}]、forces: [{"body", "force_n": [x, y, z], "pos_mm"}]
  reactions: [构件名]  要输出关节反力的构件（父构件作用在它上的力与力矩，世界坐标，力矩对它的关节中心）

结果 data：
  drives: 每个驱动的峰值、均方根（N·m 或 N）、稳定峰值 peak_settled（去掉加速度突变后 settle_window_s 内的软约束过冲）、最高转速（rpm 或 mm/s）、峰值与平均功率（W）、最大等效惯量（kg·m²）
  series: 时间与各驱动关节的位置、速度、驱动力矩（按 sample_hz 记录）
  static: 机械臂初始姿态的重力矩（几何算法，与动力学求解独立，用于核对）
  reactions: {构件: {"force_n": {x, y, z}, "moment_nm": {x, y, z}（按 series 的时间点）, "max_abs": {fx…mz}（全部计算点）, "max_abs_settled"（同 peak_settled）}}
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
COUPLING_DEV_MM = 1.0      # 传动比约束（丝杠等移动输出）允许的最大偏差
COUPLING_DEV_DEG = 1.0     # 转动输出（齿轮、蜗轮、带轮）允许的最大偏差
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
        elif k == "path":
            drives.append({"joint": j, "kind": "path", "segments": [
                {"to": ang(j, g["to"]), "t0": float(g["t0_s"]), "t1": float(g["t1_s"]), "accel": float(g.get("accel_ratio", 0.25))}
                for g in d.get("segments") or []]})
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


def needs(setup: Mapping) -> list[str]:
    """新写法（ADR-0097：setup = {"model": mbd-model/1 模型}）只要 numpy、scipy；旧写法要 mujoco"""
    if _is_model(setup):
        return ["numpy", "scipy"]
    return MODULE["python"]


def _is_model(setup) -> bool:
    m = setup.get("model") if isinstance(setup, Mapping) else None
    return isinstance(m, Mapping) and m.get("format") == "mbd-model/1"


def _run_model(setup: Mapping) -> dict:
    """ADR-0097：模型（schema/mbd-model.schema.json）→ 自写的精确求解器（analysis/mbd/dae）"""
    import scipy

    from analysis.mbd.dae import model as dmodel
    from analysis.mbd.dae import run as drun
    from analysis.mbd.dae import solve as dsolve

    t0 = time.time()
    try:
        data, messages = drun.run_model(setup["model"])
    except (dmodel.ModelError, dsolve.SolveError) as exc:
        return result.failed("mbd", MODULE["version"], setup, f"模型或计算有误：{exc}")
    lim = ["刚体：构件不变形（柔性体在 ADR-0097 D6）；梁、衬套是构件之间的线性弹性连接",
           "运动副摩擦、接触摩擦用速度光滑过渡的库仑模型，静平衡不计摩擦",
           "接触几何只支持 ADR-0097 补充五列出的配对；网格只能是凸体；齿轮只有直齿外啮合",
           "删掉的冗余约束方向上，运动副反力不唯一（与 ADAMS 相同），这些运动副的反力标为不完整"]
    return result.make("mbd", MODULE["version"], setup, data, limitations=lim, messages=messages,
                       solver={"name": "问渠多体求解器（绝对坐标 + 坐标分块，ADR-0097 D1；scipy 积分器）",
                               "version": scipy.__version__}, elapsed_s=time.time() - t0)


def run(setup: dict) -> dict:
    if _is_model(setup):
        return _run_model(setup)
    from analysis.mbd import core, mechanisms

    t0 = time.time()
    try:
        spec, mid = _spec(setup.get("model") or {})
        slides = _slide_joints(spec)
        internal = _internal(setup, slides)
        loop_tau = None
        if mid is not None:
            given = (setup.get("model") or {}).get("params")
            internal = mechanisms.prepare_setup(mid, given, internal)
            if mid in mechanisms.LOOP_MIDS:
                # 线索第 23 条：闭环软约束的 τ 按驱动转速选，闭合点拉开不超过最短构件的 0.1 %
                loop_tau, h = mechanisms.loop_tau(mid, given, _drive_speed_max(internal, mechanisms.DRIVER[mid]))
                spec = core.load_spec(xml=mechanisms.mjcf(mid, given, loop_tau_s=loop_tau, timestep_s=h))
                internal["dt"] = min(float(internal.get("dt") or h), h)
        summ, ch, _anim = core.simulate(spec, internal)
        dae, dae_ratio = None, None
        if mid is not None:
            go, dae_ratio = mechanisms.dae_route(mid, internal, summ["timestep_s"], _drive_speed_max(internal, mechanisms.DRIVER[mid]))
            if go and not setup.get("reactions"):
                dae = _dae_drive(mid, (setup.get("model") or {}).get("params"), internal, ch)
    except (SetupError, core.SetupError, KeyError, TypeError, ValueError) as exc:
        return result.failed("mbd", MODULE["version"], setup, f"设置有误：{exc}")
    drives, series = [], {"t_s": _downsample(ch["t"])}
    for d in summ["drives"]:
        j, slide = d["joint"], d["joint"] in slides
        drives.append({
            "joint": j, "kind": d["kind"], "unit_force": "N" if slide else "N·m",
            "peak": d["peak"], "rms": d["rms"], "peak_settled": d["peak_settled"],
            "speed_max": d["speed_max"] * (1000 if slide else RPM), "unit_speed": "mm/s" if slide else "rpm",
            "power_peak_w": d["power_peak"], "power_mean_w": d["power_mean"], "inertia_max_kgm2": d["inertia_max"]})
        k = 1000 if slide else 180 / math.pi
        series[j] = {"q": _downsample(ch["q." + j] * k), "speed": _downsample(ch["qd." + j] * (1000 if slide else RPM)),
                     "drive": _downsample(ch["drive." + j])}
        if slide:
            series[j]["accel"] = _downsample(ch["qdd." + j] * 1000)
    if dae is not None:
        # 线索第 71 条：一转时间只有给定运动约束时间常数的几十倍时，MuJoCo 的软约束跟不上（平缝机 5000 rpm 峰值 +49 %、
        # 恒速一转平均功率 367 W），主动件的力矩、功率改用 DAE 内核的精确值，MuJoCo 只出动画和其余关节的运动
        drv = mechanisms.DRIVER[mid]
        d0 = next(x for x in drives if x["joint"] == drv)
        d0.update(dae["stats"])
        series[drv].update(dae["series"])
        series["t_s"] = dae["series_t"]
    data = {"drives": drives, "series": series, "tracking_error": summ["tracking_error_max"],
            "timestep_s": summ["timestep_s"], "settle_window_s": summ["settle_window_s"]}
    reactions, keep = {}, core.settled_mask(ch["t"], internal.get("drives") or [], summ["timestep_s"])
    for b in setup.get("reactions") or []:
        if f"rf.{b}.x" not in ch:
            return result.failed("mbd", MODULE["version"], setup, f"设置有误：模型里没有构件“{b}”，输出不了反力")
        reactions[b] = {"force_n": {a: _downsample(ch[f"rf.{b}.{a}"]) for a in "xyz"},
                        "moment_nm": {a: _downsample(ch[f"rm.{b}.{a}"]) for a in "xyz"},
                        "max_abs": {**{f"f{a}": float(abs(ch[f"rf.{b}.{a}"]).max()) for a in "xyz"},
                                    **{f"m{a}": float(abs(ch[f"rm.{b}.{a}"]).max()) for a in "xyz"}},
                        "max_abs_settled": {**{f"f{a}": float(abs(ch[f"rf.{b}.{a}"][keep]).max()) for a in "xyz"},
                                            **{f"m{a}": float(abs(ch[f"rm.{b}.{a}"][keep]).max()) for a in "xyz"}}
                        if keep.any() else None}
    if reactions:
        data["reactions"] = reactions
    # 传动比耦合的实际偏差（问渠 CAD 0.3.6 细则 C2）：从动 − k × 主动，全程最大值；超限就不给结果——约束没守住时力矩看着对、位置是错的
    over = []
    if mid is not None:
        devs = []
        for out, inp, k in mechanisms.ratio_couplings(mid, mechanisms.params(mid, (setup.get("model") or {}).get("params"))):
            v = float(abs(ch["q." + out] - k * ch["q." + inp]).max())
            slide = out in slides
            val, unit, lim = (v * 1000, "mm", COUPLING_DEV_MM) if slide else (math.degrees(v), "°", COUPLING_DEV_DEG)
            devs.append({"follower": out, "driver": inp, "ratio": k, "max_dev": round(val, 6), "unit": unit, "limit": lim})
            if val > lim:
                over.append(f"{out} 与 {inp} 的传动比约束最大偏差 {val:.3g} {unit}，超过 {lim:g} {unit}")
        if devs:
            data["coupling_max_dev"] = devs
    messages, lims = [], list(LIMITATIONS)
    if mid in mechanisms.LOOP_MIDS:
        given = (setup.get("model") or {}).get("params")
        names = [j for j in ("crank", "coupler", "rocker", "rod", "slider") if "q." + j in ch]
        gap = mechanisms.loop_gap(mid, given, {j: ch["q." + j] for j in names})
        k = int(gap.argmax())
        lim_mm = mechanisms.LOOP_GAP_REL * min(mechanisms._links(mid, mechanisms.params(mid, given))) * 1000
        data["loop"] = {"max_gap_mm": round(float(gap[k]) * 1000, 6), "t_s": round(float(ch["t"][k]), 6),
                        "limit_mm": lim_mm, "tau_s": loop_tau}
        lims.append("闭环（连杆与摇杆 / 滑块的连接）是软约束：闭合点会拉开约 τ² × 闭合点向心加速度，"
                    f"τ 按驱动转速自动选（本次 {loop_tau * 1000:.3g} ms），实际最大拉开见 data.loop")
        if gap[k] * 1000 > lim_mm:
            messages.append("闭环拉开 {:.3g} mm（t = {:.3g} s），超过最短构件的 0.1 %（{:.3g} mm）："
                            "驱动力矩和铰链反力的误差可能超过 1 %；可加密时间步，或改用 DAE 内核（model 格式）".format(
                                gap[k] * 1000, ch["t"][k], lim_mm))
    if dae is not None:
        data["force_solver"] = {"driver": mechanisms.DRIVER[mid], "name": "DAE", "rev_over_tau": round(dae_ratio, 3)}
        lims.append("主动件的驱动力矩、功率由 DAE 内核按给定运动精确算出（一转时间只有给定运动约束时间常数的 "
                    f"{dae_ratio:.3g} 倍，MuJoCo 软约束跟不上）；动画和其余关节的运动仍来自 MuJoCo")
    else:
        messages += _loop_checks(mid, internal, data, setup)
    if mid in mechanisms.LOOP_MIDS:
        data["energy_balance"] = eb = _energy_balance(ch, summ, setup)
        if eb["status"] == "fail":
            messages.append("能量平衡差 {:.1%}（输入功 {:.4g} J，机械能增加 {:.4g} J；超过 {:.0%}）：闭环软约束和积分耗散了能量，"
                            "转角、速度、力矩待确认；可加密时间步，或改用 DAE 内核（model 格式）".format(
                                eb["rel_error"], eb["work_in_j"], eb["energy_gain_j"], ENERGY_REL))
    if dae is None and dae_ratio is not None and dae_ratio < mechanisms.DAE_RATIO:
        messages.append(f"一转时间只有给定运动约束时间常数的 {dae_ratio:.3g} 倍（小于 {mechanisms.DAE_RATIO:g}），MuJoCo 软约束跟不上，驱动力矩可能偏差"
                        "超过 1 %；这次因为有附加负载、外力、摩擦、反力输出或非匀速驱动没有改用 DAE 内核，"
                        "要精确值请用 model 格式（DAE 内核）")
    if mid == "C-BLT-BELT":
        # 线索第 38 条：带传动按主动轮力矩峰值核打滑、给出轴上拉力；没给初拉力、摩擦系数判 unknown
        bc = mechanisms.belt_check((setup.get("model") or {}).get("params"), float(abs(ch["drive.pulley1"]).max()))
        data["belt"] = {k: (round(v, 6) if isinstance(v, float) else v) for k, v in bc.items()}
        if bc["status"] == "fail":
            messages.append("带会打滑：主动轮力矩峰值 {:.3g} N·m 超过打滑极限 {:.3g} N·m（初拉力、摩擦系数、包角 {:.1f}° 决定），"
                            "传动比 1:{:.3g} 的结果不成立；加大初拉力或包角".format(
                                float(abs(ch["drive.pulley1"]).max()), bc["torque_limit_driver_nm"], bc["wrap_small_deg"],
                                mechanisms.ratio("C-BLT-BELT", (setup.get("model") or {}).get("params"))))
        elif bc["status"] == "unknown":
            messages.append("带传动按刚性传动比算，打滑没有核查：没给初拉力 initial_tension_n、摩擦系数 mu")
    if over:
        return result.failed("mbd", MODULE["version"], setup,
                             "传动比约束没守住，结果不可信：" + "；".join(over) + "。可减小负载、加密时间步，或改用 DAE 内核（model 格式）")
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

    return result.make("mbd", MODULE["version"], setup, data, limitations=lims, messages=messages,
                       solver={"name": "MuJoCo", "version": mujoco.__version__}, elapsed_s=time.time() - t0)


ENERGY_REL = 0.03         # 闭环机构能量平衡（输入功 − 机械能增加）允许的相对误差（线索第 8 条）
ENERGY_ABS_J = 1e-4       # 能量变化本身很小（静止、慢速）时按绝对差判


def _energy_balance(ch, summ, setup):
    """输入功（各驱动力 × 速度的积分）与机械能（动能 + 重力势能）增加之差，相对两者较大者。外力、摩擦阻尼不计入时
    判 unknown（缺这一项不能判 pass）"""
    import numpy as np

    if setup.get("forces") or setup.get("friction"):
        return {"status": "unknown", "rel_error": None, "work_in_j": None, "energy_gain_j": None,
                "note": "有外力或摩擦阻尼，能量平衡没有核"}
    t = ch["t"]
    p = sum((ch["drive." + d["joint"]] * ch["qd." + d["joint"]] for d in summ["drives"]), np.zeros_like(t))
    w = np.concatenate([[0.0], np.cumsum((p[1:] + p[:-1]) / 2 * np.diff(t))])
    de = ch["energy"] - ch["energy"][0]
    scale = max(float(np.max(np.abs(w))), float(np.max(np.abs(de))))
    err = float(np.max(np.abs(w - de)))
    rel = err / scale if scale > 0 else 0.0
    return {"status": "pass" if rel <= ENERGY_REL or err <= ENERGY_ABS_J else "fail", "rel_error": round(rel, 6), "limit": ENERGY_REL,
            "work_in_j": round(float(w[-1]), 9), "energy_gain_j": round(float(de[-1]), 9)}


TRACK_DEG = 1.0           # 给定运动的跟踪误差超过它要提示（线索第 71 条）
CYCLE_MEAN_REL = 0.02     # 恒速一转平均力矩超过峰值的这个比例：数值耗散（纯惯性、重力的机构应为 0）


def _loop_checks(mid, internal, data, setup):
    """MuJoCo 路线的两项核对（线索第 71 条）：给定运动的跟踪误差；闭环机构恒速时最后一整转的平均力矩
    （没有外力、摩擦时，惯性力和重力一转做功为 0，平均力矩不为 0 就是软约束和积分耗散的能量）"""
    from analysis.mbd import mechanisms

    out = []
    te = math.degrees(float(data.get("tracking_error") or 0.0))
    if te > TRACK_DEG:
        out.append(f"给定运动的最大跟踪误差 {te:.3g}°（超过 {TRACK_DEG:g}°）：MuJoCo 的给定运动是软约束，驱动力矩会有偏差，"
                   "可加密时间步，或改用 DAE 内核（model 格式）")
    if mid not in mechanisms.LOOP_MIDS or setup.get("forces") or setup.get("friction"):
        return out
    drv = mechanisms.DRIVER[mid]
    d = next((x for x in internal.get("drives") or [] if x["joint"] == drv), None)
    if d is None or d["kind"] != "speed" or len(internal.get("drives") or []) != 1:
        return out
    try:
        sw = energy_swing({"data": data}, drv)
    except SetupError:
        return out
    peak = next(x for x in data["drives"] if x["joint"] == drv)["peak_settled"] or 0.0
    if peak and abs(sw["mean_torque_nm"]) > CYCLE_MEAN_REL * peak:
        out.append("恒速时最后一整转的平均驱动力矩 {:.3g} N·m（峰值的 {:.0%}）：没有外力和摩擦时应为 0，这是软约束和积分耗散的"
                   "能量，驱动力矩待确认；可加密时间步，或改用 DAE 内核（model 格式）".format(
                       sw["mean_torque_nm"], abs(sw["mean_torque_nm"]) / peak))
    return out


def _dae_drive(mid, given, internal, ch):
    """闭环机构主动件的力矩、功率用 DAE 内核算（运动学分析），统计口径同 core.simulate"""
    import numpy as np

    from analysis.mbd import mechanisms
    from analysis.mbd.dae import model as dmodel
    from analysis.mbd.dae import run as drun
    from analysis.mbd.dae import solve as dsolve

    m = mechanisms.dae_model(mid, given, internal)
    try:
        out, _msgs = drun.run_model(m)
    except (dmodel.ModelError, dsolve.SolveError) as exc:
        raise ValueError(f"高速闭环机构改用 DAE 内核算力矩时出错：{exc}") from exc
    t = np.asarray(out["times_s"], float)
    tau = np.asarray(out["motions"]["drive"]["effort"], float)
    d = next(x for x in internal["drives"] if x["joint"] == mechanisms.DRIVER[mid])
    qd = (np.full_like(t, d["value"]) if d["kind"] == "speed"
          else d["amp"] * 2 * math.pi * d["freq"] * np.cos(2 * math.pi * d["freq"] * t))
    p = tau * qd
    stats = {"peak": float(np.max(np.abs(tau))), "rms": float(np.sqrt(np.mean(tau ** 2))), "peak_settled": float(np.max(np.abs(tau))),
             "speed_max": float(np.max(np.abs(qd))) * RPM, "power_peak_w": float(np.max(np.abs(p))), "power_mean_w": float(np.mean(p))}
    q0 = float((internal.get("initial") or {}).get(mechanisms.DRIVER[mid], 0.0))
    q = q0 + (d["value"] * t if d["kind"] == "speed" else d["amp"] * np.sin(2 * math.pi * d["freq"] * t))
    return {"stats": stats, "series_t": _downsample(t),
            "series": {"q": _downsample(np.degrees(q)), "speed": _downsample(qd * RPM), "drive": _downsample(tau)}}


def _drive_speed_max(internal, driver):
    """主动件的最大转速（rad/s 或 m/s）估计：匀速取给定值，正弦取幅值 × 2πf，点到点取平均速度的两倍"""
    w = 0.0
    for d in internal.get("drives") or []:
        if d["joint"] != driver:
            continue
        if d["kind"] == "speed":
            w = max(w, abs(d["value"]))
        elif d["kind"] == "sine":
            w = max(w, abs(d["amp"]) * 2 * math.pi * d["freq"])
        elif d["kind"] == "move":
            q0 = float((internal.get("initial") or {}).get(driver, 0.0))
            w = max(w, 2 * abs(d["to"] - q0) / max(d["t1"] - d["t0"], 1e-9))
        elif d["kind"] == "path":
            q0 = float((internal.get("initial") or {}).get(driver, 0.0))
            for g in d["segments"]:
                w = max(w, 2 * abs(g["to"] - q0) / max(g["t1"] - g["t0"], 1e-9))
                q0 = g["to"]
    return w


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
