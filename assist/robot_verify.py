"""整机复核（ADR-0115 44.3 之二第 5 步）：用三维装配的真实零件质量重算多体动力学，与选件时的估算对照，并重新校核所选模组。

选件时（assist/robot_build.py）质量是估的：杆件按方案的截面与关节距算、模组集中在关节处、支架不计。
三维装配之后（assist/robot_cad.py）每个零件的质量、重心都有了——支架、套管、壳体底座都算进去，杆件按实际下料长度。
这里用同一个检验动作再算一遍，得出各关节的峰值、均方根力矩与最高转速，按模组组重新出需求、重新校核所选模组；
不通过就要回到选件或构型。不调用 AI。
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from pathlib import Path


def verify(concept: Mapping, build_result: Mapping, cad_result: Mapping, payload_kg: float) -> dict:
    import analysis
    from analysis.robot import mjcf
    from assist import robot_build as RB
    from engine import smart_actuator

    dt = build_result["duty"]
    xml = mjcf.mjcf_parts(concept, cad_result["parts"], payload_kg=payload_kg)
    res = analysis.run("mbd", {"force_solver": "soft", "model": {"kind": "mjcf", "xml": xml}, "duration_s": RB.T0 + dt["move_s"] + 0.2,
                               "sample_hz": 200, "initial": dt["initial"], "drives": dt["drives"]})
    if res.get("status") != "ok":
        raise RB.BuildError(f"多体动力学没算成：{res.get('error')}")
    est = {d["joint"]: d for d in build_result["rounds"][-1]["drives"]}
    real = {d["joint"]: d for d in res["data"]["drives"]}
    compare = [{"joint": j, "peak_est_nm": round(est[j]["peak"], 3), "peak_nm": round(real[j]["peak"], 3),
                "rms_est_nm": round(est[j]["rms"], 3), "rms_nm": round(real[j]["rms"], 3),
                "change": None if est[j]["peak"] < 0.01 else round(real[j]["peak"] / est[j]["peak"] - 1, 3)}
               for j in real if j in est]
    lib = RB._library()
    checks = {}
    for g, js in RB.groups(concept).items():
        pick = build_result["picks"][g]
        req = RB.group_requirement(res, js, RB.BASE_REQ)
        if pick.get("chain") == "smart":
            comp = lib.get(pick["components"][0])
            r = smart_actuator.check(req, comp, RB.operating_points(res, js))
        else:
            r = {"overall": "unknown", "checks": [], "note": "伺服链的复核走引擎选型，这一步只做一体化模组"}
        checks[g] = {"requirement": {k: req[k] for k in ("output_torque_cont_nm", "output_torque_peak_nm", "output_speed_rpm")},
                     "overall": r["overall"], "checks": r["checks"]}
    st = {c["overall"] for c in checks.values()}
    status = "fail" if "fail" in st else "unknown" if "unknown" in st else "pass"
    moving = sum(p["mass_kg"] for p in cad_result["parts"] if p.get("body") not in (None, "base") and p.get("mass_kg"))
    return {"status": status, "compare": compare, "checks": checks, "moving_mass_kg": round(moving, 4),
            "static": res["data"].get("static"), "duty": dt}


def summary(v: Mapping) -> str:
    lines = [f"复核：{v['status']}（会动的部分 {v['moving_mass_kg']} kg）"]
    for c in v["compare"]:
        ch = "" if c["change"] is None else f"（{c['change']:+.0%}）"
        lines.append(f"  {c['joint']}：峰值 估 {c['peak_est_nm']} → 实 {c['peak_nm']} N·m{ch}；均方根 估 {c['rms_est_nm']} → 实 {c['rms_nm']}")
    for g, c in v["checks"].items():
        bad = [f"{x['check']} {x['status']}：{x.get('message', '')}" for x in c["checks"] if x["status"] != "pass"]
        lines.append(f"  模组组 {g}：{c['overall']}" + ("；" + "；".join(bad) if bad else ""))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="python -m assist.robot_verify", description="整机复核（ADR-0115 44.3）")
    ap.add_argument("concept_result", type=Path)
    ap.add_argument("build_result", type=Path)
    ap.add_argument("cad_result", type=Path)
    ap.add_argument("-o", "--out", type=Path)
    a = ap.parse_args(argv)
    cr = json.loads(a.concept_result.read_text(encoding="utf-8"))
    v = verify(cr["chosen"], json.loads(a.build_result.read_text(encoding="utf-8")),
               json.loads(a.cad_result.read_text(encoding="utf-8")), float(cr["conditions"]["payload"]))
    print(summary(v), file=sys.stderr)
    if a.out:
        a.out.write_text(json.dumps(v, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return 0 if v["status"] != "fail" else 1


if __name__ == "__main__":
    raise SystemExit(main())
