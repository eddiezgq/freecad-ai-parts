"""整机案例的支架减薄（ADR-0115 44.3 之二第 9 步）：代码做，不用 AI。

跟着关节转的 U 形支架，从当前板厚按 6061 铝板常用规格往下试一级：重出三维装配、重算多体动力学（跟着转的质量变了）、
重算这一件的有限元；有限元可信、对弯曲疲劳的安全系数 ≥ THIN_FATIGUE_MIN 才接受，再试下一级；不合格就停在上一级。
从末端往基座试（下游轻了，上游的载荷只会更小）。结果写案例目录的 `plates.json`（三维装配按它出图）和 `out/thin-result.json`。

基座、舵盘法兰、壳体底座不减：法兰与底座的 6 mm 是沉头孔深 + 压紧定的；基座底面在有限元里整面固定，
桌面固定方式没设计之前，算不出底板和立板根部的真实受力。

    python -m assist.robot_thin examples/robots/teaching-arm
"""

from __future__ import annotations

import json
import sys
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path

THIN_FATIGUE_MIN = 2.0          # 需求 1.2 之外多留的部分抵有限元的简化（fea-result.json · limits）
RULE = (f"板厚只在铝板常用规格里选；有限元可信、对弯曲疲劳 ≥ {THIN_FATIGUE_MIN:g} 才接受（需求的安全系数照旧另判）；"
        "从末端往基座试；基座、舵盘法兰、壳体底座不减")


def candidates(cad: Mapping) -> list[tuple[str, str]]:
    """可减的零件：U 形支架 (名字, 关节)，从末端往基座排"""
    rows = [(p["name"], p["joint"]) for p in cad["parts"] if p["kind"] == "bracket" and p["name"].endswith("U 形支架")]
    return rows[::-1]


def thinner(t: float) -> float | None:
    from assist.robot_cad import PLATE_STOCK_MM

    lower = [s for s in PLATE_STOCK_MM if s < t - 1e-9]
    return max(lower) if lower else None


def accept(item: Mapping) -> bool:
    return item.get("status") == "pass" and (item.get("safety_fatigue") or 0.0) >= THIN_FATIGUE_MIN


def snapshot(out_dir: Path) -> dict:
    """减薄前的样子：每个支架的板厚、质量、安全系数，各关节峰值力矩"""
    cad = json.loads((out_dir / "cad" / "cad-result.json").read_text(encoding="utf-8"))
    fea_p = out_dir / "fea-result.json"
    fea = {x["part"]: x for x in json.loads(fea_p.read_text(encoding="utf-8"))["items"]} if fea_p.exists() else {}
    ver = json.loads((out_dir / "verify-result.json").read_text(encoding="utf-8"))
    parts = {}
    for p in cad["parts"]:
        if p["kind"] != "bracket":
            continue
        f = fea.get(p["name"]) or {}
        t = p.get("plate_mm")
        if t is None and p["name"].endswith("U 形支架"):     # 第 9 步之前出的装配没记板厚：U 形支架当时都是 plate_mm
            from assist.robot_cad import DESIGN

            t = DESIGN["plate_mm"]
        parts[p["name"]] = {k: v for k, v in {"plate_mm": t, "mass_kg": p["mass_kg"], "moving": p["body"] != "base",
                                              "safety_yield": f.get("safety_yield"), "safety_fatigue": f.get("safety_fatigue")}.items()
                            if v is not None}
    return {"parts": parts, "mass_kg": cad["mass_kg"],
            "peak_nm": {x["joint"]: x["peak_nm"] for x in ver.get("compare") or []}}


def real_trial(case_dir: Path) -> Callable[[Mapping, str, str], dict]:
    """在临时目录里按给定板厚重出装配、重算多体动力学、只算这一件的有限元"""
    from analysis.robot import fit
    from assist import robot_cad, robot_fea, robot_verify
    from kb.library import JsonLibrary

    out = case_dir / "out"
    cr = json.loads((out / "concept-result.json").read_text(encoding="utf-8"))
    br = json.loads((out / "build-result.json").read_text(encoding="utf-8"))
    comp = JsonLibrary(Path(__file__).resolve().parents[1] / "data" / "library").get(
        next(iter(br["picks"].values()))["components"][0])
    concept = cr["chosen"]
    payload = float(cr["conditions"]["payload"])

    def trial(plates: Mapping, name: str, jid: str) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            wd = Path(tmp)
            fr = fit.check(concept, {j["id"]: comp for j in concept["joints"]})
            cad = robot_cad.build(concept, fr, comp, wd / "cad", plates)
            if cad["status"] != "pass":
                return {"status": "fail", "note": "三维装配不通过：" + "；".join(cad["problems"] or [str(cad["interferences"])])}
            ver = robot_verify.verify(concept, br, cad, payload)
            r = robot_fea.analyse(concept, br, cad, ver, wd / "cad" / "assembly.step", payload, parts_only=[name])
            item = r["items"][0]
            part = next(p for p in cad["parts"] if p["name"] == name)
            return dict(item, mass_kg=part["mass_kg"])
    return trial


def run(case_dir: str | Path, *, trial: Callable[[Mapping, str, str], dict] | None = None, log=None) -> dict:
    case_dir = Path(case_dir)
    out = case_dir / "out"
    pp = case_dir / "plates.json"
    plates = json.loads(pp.read_text(encoding="utf-8")) if pp.exists() else {}
    plates.setdefault("clevis_mm", {})
    before = snapshot(out)
    cad = json.loads((out / "cad" / "cad-result.json").read_text(encoding="utf-8"))
    trial = trial or real_trial(case_dir)
    trials = []
    for name, jid in candidates(cad):
        t = float(plates["clevis_mm"].get(jid) or before["parts"][name]["plate_mm"])
        while (nt := thinner(t)) is not None:
            test = {**plates, "clevis_mm": {**plates["clevis_mm"], jid: nt}}
            r = trial(test, name, jid)
            ok = accept(r)
            trials.append({"part": name, "from_mm": t, "to_mm": nt, "accepted": ok,
                           **{k: r[k] for k in ("status", "safety_yield", "safety_fatigue", "mass_kg", "note") if k in r}})
            if log:
                log(trials[-1])
            if not ok:
                break
            t = nt
            plates = test
    pp.write_text(json.dumps(plates, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    res = {"format": "robot-thin/1", "rule": RULE, "fatigue_min": THIN_FATIGUE_MIN, "before": before, "trials": trials,
           "plates": plates}
    (out / "thin-result.json").write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return res


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="python -m assist.robot_thin", description="整机案例的支架减薄（ADR-0115 44.3 第 9 步）")
    ap.add_argument("case_dir", type=Path, help="案例目录（out/ 里要有前面各步的结果）")
    a = ap.parse_args(argv)
    r = run(a.case_dir, log=lambda t: print(f"{t['part']} {t['from_mm']:g} → {t['to_mm']:g} mm："
                                            f"{'接受' if t['accepted'] else '不接受'}；{t.get('note', '')}", file=sys.stderr, flush=True))
    print(f"板厚：{r['plates']}；写入 {a.case_dir / 'plates.json'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
