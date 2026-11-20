"""刀具库 cam-tool/1（ADR-0105）：读文件、校验、按刀具样本的范围核对切削参数、从 FreeCAD CAM 刀具（.fctb / .fctl）导入。

- `load(path)`：一个刀具库 JSON；`EXAMPLE` 是仓库带的示例库（虚构）。
- `check_cutting(tool, iso_group, vc=…, fz=…, f=…, ap=…, ae=…)`：给定的参数是否在刀具样本给的范围内。
  范围缺了（样本没给这一项、或没有这个材料组）结果是“未知”，不当“通过”。**AI 和程序给的参数超出范围就退回**（ADR-0104 第 7 节）。
- `from_freecad(fctl_or_fctb)`：FreeCAD CAM 刀具 → cam-tool/1。FreeCAD 的刀具没有刀柄外形、切削参数和出处，
  导入后 `source.kind` 记为 enterprise（企业自己的刀具表），缺的项不写，用户在刀具库里补。
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

FORMAT = "cam-tool/1"
ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "schema" / "cam-tool.schema.json"
EXAMPLE = Path(__file__).resolve().parent / "tools_example.json"
BUILTIN = Path(__file__).resolve().parent / "libraries"          # 厂商样本刀具库（只读，ADR-0106 Q4b）
MILLING = {"flat_endmill", "ball_endmill", "bull_endmill", "drill", "center_drill", "chamfer_mill", "face_mill", "tap", "reamer"}
TURNING = {"turn", "groove", "thread_turn", "bore"}


class ToolError(ValueError):
    pass


@lru_cache(maxsize=1)
def _validator():
    from jsonschema import Draft202012Validator

    return Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8")))


def validate(lib: dict) -> list[str]:
    errs = sorted(_validator().iter_errors(lib), key=lambda e: list(e.absolute_path))
    return [f"{'/'.join(map(str, e.absolute_path)) or '（顶层）'}：{e.message}" for e in errs]


def check(lib: dict, where: str = "") -> dict:
    errs = validate(lib)
    if not errs:
        ids = [t["id"] for t in lib["tools"]]
        dup = sorted({i for i in ids if ids.count(i) > 1})
        if dup:
            errs = [f"刀具 id 重复：{', '.join(dup)}"]
    if errs:
        raise ToolError(f"{where + '：' if where else ''}刀具库 {lib.get('name', '')} 不符合 cam-tool/1：" + "；".join(errs[:5]))
    return lib


def load(path: str | Path = EXAMPLE) -> dict:
    p = Path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ToolError(f"{p}：读不了刀具库：{exc}") from exc
    return check(data, str(p))


# ---------------- 刀具库窗口用（ADR-0106 Q4a）----------------
TOOL_KINDS = ("flat_endmill", "ball_endmill", "bull_endmill", "drill", "center_drill", "chamfer_mill", "face_mill", "tap", "reamer",
              "thread_mill", "turn", "groove", "thread_turn", "bore")


def user_dir(env=None) -> Path:
    """用户刀具库所在文件夹（FAP_TOOLS 可改）"""
    import os

    env = os.environ if env is None else env
    return Path(env["FAP_TOOLS"]) if env.get("FAP_TOOLS") else Path.home() / ".freecad-ai-parts" / "tools"


def libraries(env=None) -> list[dict]:
    """可选的刀具库：示例库（只读）在前，用户文件夹里的 *.json 在后 → [{"name", "path", "readonly", "error"}]"""
    out = [{"name": json.loads(EXAMPLE.read_text(encoding="utf-8"))["name"], "path": str(EXAMPLE), "readonly": True, "error": ""}]
    for p in sorted(BUILTIN.glob("*.json")):
        out.append({"name": json.loads(p.read_text(encoding="utf-8"))["name"], "path": str(p), "readonly": True, "error": ""})
    d = user_dir(env)
    for p in sorted(d.glob("*.json")) if d.is_dir() else []:
        try:
            out.append({"name": load(p)["name"], "path": str(p), "readonly": False, "error": ""})
        except ToolError as exc:
            out.append({"name": p.stem, "path": str(p), "readonly": False, "error": str(exc)})
    return out


def engineering_errors(lib: dict) -> list[str]:
    """schema 管不到的工程规则：范围下限不大于上限、刀号不重复"""
    out = []
    nums = [t["number"] for t in lib.get("tools") or [] if "number" in t]
    dup = sorted({n for n in nums if nums.count(n) > 1})
    if dup:
        out.append(f"刀号重复：{', '.join(map(str, dup))}")
    for t in lib.get("tools") or []:
        for c in t.get("cutting") or []:
            for k, v in c.items():
                if isinstance(v, dict) and "min" in v and "max" in v and v["min"] > v["max"]:
                    out.append(f"{t.get('id')}：{c.get('iso_group')} 组 {k} 的下限 {v['min']:g} 大于上限 {v['max']:g}")
    return out


def readonly(path: str | Path) -> bool:
    """示例库和厂商样本库只读"""
    p = Path(path).resolve()
    return p == EXAMPLE.resolve() or p.parent == BUILTIN.resolve()


def save(lib: dict, path: str | Path) -> Path:
    """核对后保存（不合格不存，ToolError 写明哪一项）；示例库不能覆盖"""
    p = Path(path)
    if readonly(p):
        raise ToolError("示例刀具库是只读的：另存为自己的刀具库")
    errs = validate(lib) + engineering_errors(lib)
    if not errs:
        ids = [t["id"] for t in lib["tools"]]
        dup = sorted({i for i in ids if ids.count(i) > 1})
        errs = [f"刀具 id 重复：{', '.join(dup)}"] if dup else []
    if errs:
        raise ToolError("不能保存：" + "；".join(errs[:8]))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(lib, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return p


def template(kind: str, tool_id: str, number: int) -> dict:
    """新建刀具的空模板：只写种类必需的字段（数值留给用户填，不编）"""
    if kind not in TOOL_KINDS:
        raise ToolError(f"没有这种刀具：{kind}")
    t = {"id": tool_id, "number": int(number), "kind": kind, "source": {"kind": "enterprise", "ref": "企业自己的刀具（出处待写明）"}}
    if kind in TURNING:
        t["insert"] = {}
    return t


def get(lib: dict, tool_id: str) -> dict:
    for t in lib["tools"]:
        if t["id"] == tool_id:
            return t
    raise ToolError(f"刀具库 {lib['name']} 里没有刀具 {tool_id!r}")


def cutting_for(tool: dict, iso_group: str) -> dict | None:
    return next((c for c in tool.get("cutting") or [] if c["iso_group"] == iso_group), None)


def _range_item(name: str, value: float, rng: dict | None, unit: str) -> dict:
    if rng is None:
        return {"item": name, "value": value, "level": "unknown", "text": f"{name} {value:g} {unit}：刀具样本没给范围，待确认"}
    lo, hi = rng.get("min"), rng.get("max")
    if (lo is not None and value < lo - 1e-12) or (hi is not None and value > hi + 1e-12):
        span = f"{'' if lo is None else f'{lo:g}'}–{'' if hi is None else f'{hi:g}'}"
        return {"item": name, "value": value, "level": "error", "text": f"{name} {value:g} {unit} 超出刀具样本范围 {span} {unit}"}
    return {"item": name, "value": value, "level": "pass", "text": f"{name} {value:g} {unit} 在样本范围内"}


def check_cutting(tool: dict, iso_group: str, *, vc: float | None = None, fz: float | None = None,
                  f: float | None = None, ap: float | None = None, ae: float | None = None) -> list[dict]:
    """逐项核对；每项 level 为 pass / error / unknown。给了哪个参数就核哪个。"""
    c = cutting_for(tool, iso_group)
    if c is None:
        return [{"item": "材料组", "value": iso_group, "level": "unknown",
                 "text": f"刀具 {tool['id']} 的样本没有 {iso_group} 组材料的切削参数，待确认"}]
    out = []
    if vc is not None:
        out.append(_range_item("切削速度 vc", vc, c.get("vc_m_min"), "m/min"))
    if fz is not None:
        out.append(_range_item("每齿进给 fz", fz, c.get("fz_mm"), "mm"))
    if f is not None:
        out.append(_range_item("每转进给 f", f, c.get("f_mm_rev"), "mm/r"))
    if ap is not None:
        out.append(_range_item("切深 ap", ap, None if "ap_max_mm" not in c else {"max": c["ap_max_mm"]}, "mm"))
    if ae is not None:
        out.append(_range_item("切宽 ae", ae, None if "ae_max_mm" not in c else {"max": c["ae_max_mm"]}, "mm"))
    return out


def verdict(items: list[dict]) -> str:
    """整体：有 error 为 error；否则有 unknown 为 unknown；全 pass 才 pass"""
    levels = {i["level"] for i in items}
    return "error" if "error" in levels else "unknown" if ("unknown" in levels or not items) else "pass"


# ---------------- FreeCAD CAM 刀具导入 ----------------

_SHAPES = {"endmill": "flat_endmill", "ballend": "ball_endmill", "bullnose": "bull_endmill", "drill": "drill",
           "chamfer": "chamfer_mill", "v-bit": "chamfer_mill", "vbit": "chamfer_mill"}
_Q = re.compile(r"^\s*([-+0-9.eE]+)\s*(mm|°|deg)?\s*$")


def _num(s) -> float | None:
    if isinstance(s, (int, float)):
        return float(s)
    m = _Q.match(str(s or ""))
    return float(m.group(1)) if m else None


def from_fctb(bit: dict, number: int, tool_id: str | None = None) -> dict | None:
    """一个 .fctb（已读成 dict）→ 一把 cam-tool/1 刀具；认不出的形状（探头、锯片、螺纹铣刀）返回 None"""
    shape = Path(str(bit.get("shape", ""))).stem.lower()
    kind = _SHAPES.get(shape)
    if kind is None:
        return None
    p = bit.get("parameter") or {}
    t = {"id": tool_id or f"T{number}", "number": int(number), "name": str(bit.get("name") or shape), "kind": kind}
    for key, field in (("Diameter", "diameter_mm"), ("CuttingEdgeHeight", "flute_length_mm"), ("Length", "overall_length_mm"),
                       ("ShankDiameter", "shank_diameter_mm")):
        v = _num(p.get(key))
        if v is not None and v > 0:
            t[field] = v
    if kind == "bull_endmill":
        d, flat = _num(p.get("Diameter")), _num(p.get("FlatRadius"))
        if d is not None and flat is not None and d / 2 - flat > 0:
            t["corner_radius_mm"] = round(d / 2 - flat, 6)
    if kind == "drill" and _num(p.get("TipAngle")):
        t["tip_angle_deg"] = _num(p.get("TipAngle"))
    if _num(p.get("Flutes")):
        t["flutes"] = int(_num(p.get("Flutes")))
    t["source"] = {"kind": "enterprise", "ref": "由 FreeCAD CAM 刀具导入：" + str(bit.get("name") or shape)}
    return t


def from_freecad(path: str | Path, name: str | None = None) -> tuple[dict, list[str]]:
    """.fctl（刀具表）或单个 .fctb → (cam-tool/1 刀具库, 没导入的说明)"""
    p = Path(path)
    data = json.loads(p.read_text(encoding="utf-8"))
    entries = [(e.get("nr", i + 1), p.parent.parent / "Bit" / e["path"] if not (p.parent / e["path"]).is_file()
                else p.parent / e["path"]) for i, e in enumerate(data.get("tools") or [])] if "tools" in data else [(1, p)]
    tools, skipped = [], []
    for nr, bp in entries:
        try:
            bit = data if bp == p else json.loads(Path(bp).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            skipped.append(f"T{nr} {Path(bp).name}：读不了（{exc}）")
            continue
        t = from_fctb(bit, nr)
        if t is None:
            skipped.append(f"T{nr} {bit.get('name', Path(bp).stem)}：形状 {bit.get('shape')} 还不支持，没导入")
        else:
            tools.append(t)
    lib = {"format": FORMAT, "name": name or p.stem, "tools": tools}
    return check(lib, str(p)), skipped
