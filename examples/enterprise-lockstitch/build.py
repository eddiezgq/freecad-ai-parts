"""示范缝纫机企业（虚构）：从物料表出发，用三条进料通道建企业库，再重跑平缝机主轴选型（ADR-0099 41.6）。

    python examples/enterprise-lockstitch/build.py                 # 回放录制（不联网），写到 library/ 与 out/
    python examples/enterprise-lockstitch/build.py --record        # 在 CI 上用真实模型录制（经网关，要密钥）

步骤：
1. 通道 C：models/ 里的三维模型 → 代码测量 → 自制件（零件类型、材料按 confirm.yaml 人确认的写；AI 的类型提议一并记下）
2. 通道 B：bom.csv → AI 认列、分类 → 代码查重、对应公共库与企业库、核对品类 → 待补清单
3. 通道 A：外购件的参数来自公共库（安川、NSK 的公开目录，已按 ADR-0040 抽取入库），物料表里的型号对上即用
4. 完整度报告：物料表用到的组件缺什么、缺了哪些校验待确认、去哪找
5. 平缝机主轴选型：物料表里的电机、驱动器 + confirm.yaml 的需求 → 引擎校验 C1–C11

企业库与报告都是示范：企业、物料表、自制件图号都是虚构的；外购件参数是真实公开资料。
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from assist import measure
from ingest import bom
from kb import completeness

ENTERPRISE = "示范缝纫机有限公司（虚构）"
VENDOR_SLUG = "demo-sewing"
ACTOR = "示范企业工程师（虚构）"
KIND_RECORDINGS = ROOT / "tests" / "recordings" / "part_kind"


def _clients(record: bool, provider: str | None):
    from ingest.llm_extract import RecordedClient

    if record:
        from assist.llm import GatewayClient

        c = GatewayClient(provider)
        return GatewayClient(provider, record_dir=bom.RECORDINGS_DIR), GatewayClient(provider, record_dir=KIND_RECORDINGS), c.model
    return RecordedClient(bom.RECORDINGS_DIR), RecordedClient(KIND_RECORDINGS), bom.DEFAULT_MODEL


def build(out_lib: Path, out_dir: Path, *, record: bool = False, provider: str | None = None) -> dict:
    from engine.validate import validate
    from kb.enterprise import EnterpriseLibrary
    from kb.library import JsonLibrary

    confirm = yaml.safe_load((HERE / "confirm.yaml").read_text(encoding="utf-8"))
    bom_client, kind_client, model = _clients(record, provider)
    if out_lib.exists():
        shutil.rmtree(out_lib)
    out_dir.mkdir(parents=True, exist_ok=True)
    lib = EnterpriseLibrary(out_lib, create=True)
    public = JsonLibrary(ROOT / "data" / "library")
    summary: dict = {"enterprise": ENTERPRISE, "custom_parts": [], "notes": []}

    # 1. 通道 C：三维模型 → 自制件
    for drawing, spec in confirm["custom_parts"].items():
        step = HERE / spec["model_file"]
        doc = lib.register_document(step, f"{drawing} {spec['name']} 三维模型", ACTOR)
        meas = measure.measure(step, material=spec.get("material"))
        ai = measure.check_kind(kind_client.complete(measure.kind_request(meas, spec["name"], model=model))["tool_input"], meas)
        comp = measure.to_component(meas, enterprise=ENTERPRISE, drawing_no=drawing, doc=doc["id"],
                                    part_kind=spec["part_kind"], vendor_slug=VENDOR_SLUG,
                                    kind_doc_note=f"零件类型由 {ACTOR} 确认（AI 提议 {ai['part_kind']}）")
        comp["note"] += f"；名称：{spec['name']}" + (f"；材料依据：{spec['material_basis']}" if spec.get("material_basis") else "")
        lib.save_component(comp, ACTOR, f"从三维模型测量（{step.name}）")
        summary["custom_parts"].append({"drawing": drawing, "id": comp["id"], "segments": meas["segments"],
                                        "envelope_mm": meas["envelope_mm"], "mass_kg": meas.get("mass_kg"),
                                        "volume_mm3": meas["volume_mm3"], "ai_part_kind": ai["part_kind"],
                                        "confirmed_part_kind": spec["part_kind"]})

    # 2、3. 通道 B：物料表 → 分类、查重、对应（公共库 + 企业库）
    comps = public.all() + lib.all()
    result = bom.run(HERE / "bom.csv", bom_client, comps, model=model, gaps=completeness.component_gaps)
    for it in result["items"]:                          # 人确认的候选对应（confirm.yaml 的 bom_matches）
        cid = (confirm.get("bom_matches") or {}).get(it["code"])
        if cid and cid in it.get("candidates", []):
            it["component"] = cid
            it["confirm"] = [x for x in it["confirm"] if not x.startswith("型号对上了库里的组件")]
            it["confirmed_match"] = f"{confirm['confirmed_by']}确认（{confirm['date']}）"
    result["to_fill"] = bom.to_fill(result["items"], {c["id"]: c for c in comps}, completeness.component_gaps)
    result["summary"]["matched"] = sum("component" in i for i in result["items"])
    result["summary"]["confirm"] = sum(bool(i["confirm"]) for i in result["items"])
    (out_dir / "bom-result.json").write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    bom.to_excel(result, out_dir / "bom-result.xlsx")

    # 4. 完整度报告：物料表对上的组件
    used = sorted({it["component"] for it in result["items"] if it.get("component")})
    resolve = {c["id"]: c for c in comps + lib.all()}
    rep = completeness.report([resolve[c] for c in used])
    (out_dir / "completeness.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    completeness.to_excel(rep, out_dir / "completeness.xlsx")

    # 5. 平缝机主轴选型：物料表里的电机、驱动器
    sel = confirm["selection"]
    row = {it["code"]: it for it in result["items"]}
    motor, drive = row[sel["motor_row"]].get("component"), row[sel["drive_row"]].get("component")
    check = None
    if motor and drive:
        system = {"id": "wq-ls", "requirement": sel["requirement"],
                  "components": [{"instance": "motor", "component": motor}, {"instance": "drive", "component": drive}],
                  "connections": [{"a": "drive.motor_out", "b": "motor.power_in"}, {"a": "motor.encoder", "b": "drive.encoder_in"}]}
        check = validate(system, resolve.get)
        (out_dir / "selection.json").write_text(json.dumps({"system": system, "report": check}, ensure_ascii=False, indent=1) + "\n",
                                                encoding="utf-8")
    else:
        summary["notes"].append("物料表里的电机或驱动器没有对上公共库组件，选型没有算")
    summary.update(bom=result["summary"], to_fill=len(result["to_fill"]), completeness={"count": rep["count"], "complete": rep["complete"]},
                   selection={"motor": motor, "drive": drive, "overall": check and check["overall"],
                              "checks": check and {c["check"]: c["status"] for c in check["checks"]}},
                   confirm_items=sum(bool(i["confirm"]) for i in result["items"]))
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--record", action="store_true", help="用真实模型录制（经网关，要密钥）")
    ap.add_argument("--provider", choices=("claude", "deepseek"))
    ap.add_argument("--library", type=Path, default=HERE / "library")
    ap.add_argument("--out", type=Path, default=HERE / "out")
    a = ap.parse_args(argv)
    s = build(a.library, a.out, record=a.record, provider=a.provider)
    b = s["bom"]
    print(f"{s['enterprise']}：物料表 {b['rows']} 行 → {b['items']} 条物料，对上已有组件 {b['matched']} 条，待人确认 {s['confirm_items']} 条，"
          f"待补 {s['to_fill']} 条；自制件 {len(s['custom_parts'])} 个（从三维模型测量）；"
          f"完整度：{s['completeness']['complete']}/{s['completeness']['count']} 个组件数据齐全；"
          f"主轴选型 {s['selection']['motor']} + {s['selection']['drive']}：{s['selection']['overall']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
