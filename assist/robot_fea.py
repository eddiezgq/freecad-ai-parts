"""自制支架的强度有限元（ADR-0115 44.3 之二第 6 步）：三维装配里每个承力的支架（U 形支架、舵盘法兰、壳体底座、基座），
单独拿出来做静力有限元（analysis/fea，fea-study/1，带网格收敛与反力平衡核查），按屈服与弯曲疲劳出安全系数。

载荷（每个支架一样的做法，不调用 AI）：
  - 姿态：检验动作的起点（水平伸直，assist/robot_build.duty），各杆件的姿态由正运动学算；重力方向按安装方式。
  - 支架挑起的是“装在它下游的全部零件”加末端负载：输出支架（U 形支架、舵盘法兰）挑起本杆件上其余零件与之后的全部杆件；
    壳体底座、基座挑起本关节的模组与之后的全部杆件。各零件按三维装配的质量集中在重心。
  - 静重乘动载系数（复核时多体动力学的峰值力矩 / 起点静重力矩，取各关节最大，至少 1），作为一个远端载荷（力 + 力矩）
    加在载荷接口（套管孔或模组安装孔）上；固定接口（舵盘螺钉孔、父杆套管孔、基座底面）固定。
  - 支承与载荷的反力自然平衡：输出支架舵盘孔上的反力矩就是关节力矩。

判定：有限元的可信度核查通过才给安全系数（屈服）；疲劳按材料的弯曲疲劳极限除以同一处的最大当量应力。
两者都 ≥ 需求的安全系数为 pass，有不到的为 fail；有限元核查不通过或缺材料数据为 unknown。
"""

from __future__ import annotations

import json
import math
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path

import numpy as np

G = 9.81
TOL_MM = 0.02
MESH_MM = 2.0                   # 板厚 4 mm：两层二阶单元；收敛核查在最大应力处再加密两层
LIMITS = ["载荷取检验动作起点的静重乘动载系数，不是逐时刻的动载荷；起点是水平伸直，弯矩最大",
          "零件按点质量挂在重心上；螺钉按孔壁全固定（不计螺钉预紧、接触与孔边滑移），孔边应力的峰值已由收敛核查判断",
          "模组壳体当刚体（支架装在上面的那一面不变形），实际壳体有弹性，支架受力会更均匀"]


class FeaError(ValueError):
    pass


def _quat_rot(q: str) -> np.ndarray:
    w, x, y, z = (float(v) for v in q.split())
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def gravity_base(mount: str) -> np.ndarray:
    """重力加速度在基座坐标系里的方向（单位向量）"""
    from analysis.robot.mjcf import BASE_QUAT

    if mount not in BASE_QUAT:
        raise FeaError(f"安装方式 {mount}：重力方向判不了")
    return _quat_rot(BASE_QUAT[mount]).T @ np.array([0.0, 0.0, -1.0])


def downstream(concept: Mapping, part: Mapping, parts) -> list[Mapping]:
    """支架挑起的零件：输出支架——本杆件上其余零件与之后的全部杆件；壳体底座、基座——本关节的模组与之后的全部杆件"""
    from analysis.robot import kinematics as K

    m = K.build(concept)
    j = next(x for x in m.joints if x.id == part["joint"])
    later: set[str] = set()
    todo = [j.child]
    while todo:
        b = todo.pop()
        later.add(b)
        todo += [c.child for c in m.joints if c.parent == b]
    if part["role"] == "output":
        return [p for p in parts if p is not part and p.get("body") in later and p.get("mass_kg")]
    return [p for p in parts if p.get("mass_kg") and (p.get("body") in later
                                                      or (p["kind"] == "actuator" and p.get("joint") == part["joint"]))]


def dynamic_factor(verify_result: Mapping) -> float:
    """复核的多体动力学：各关节峰值力矩 / 起点静重力矩，取最大（静重力矩小于最大值 5% 的不算）；至少 1"""
    st = {k: abs(v) for k, v in ((verify_result.get("static") or {}).get("gravity_torque_nm") or {}).items()}
    if not st or max(st.values()) <= 0:
        return 1.0
    big = max(st.values())
    ks = [c["peak_nm"] / st[c["joint"]] for c in verify_result["compare"] if st.get(c["joint"], 0) > 0.05 * big]
    return max([1.0, *ks])


def interface_point(itf: Mapping) -> np.ndarray:
    """远端载荷的作用点：套管孔取插入段中点，孔组取各孔中点的平均"""
    if itf["type"] == "socket":
        return np.asarray(itf["start"], float) + np.asarray(itf["dir"], float) * itf["length_mm"] / 2
    if itf["type"] == "holes":
        return np.mean(np.asarray(itf["centers"], float), axis=0)
    return np.asarray(itf["point"], float)


def load_on(concept: Mapping, part: Mapping, parts, payload_kg: float, q: Mapping, factor: float) -> dict:
    """支架载荷接口上的力与力矩（零位坐标，也就是 STEP 里的坐标）：下游零件与负载在姿态 q 下的重力 × 动载系数，对作用点取矩"""
    from analysis.robot import kinematics as K

    m = K.build(concept)
    T0, Tq = K.fk(m), K.fk(m, q)
    g = gravity_base(concept["base"]["mount"]) * G
    pts = [(float(p["mass_kg"]), p["body"], np.asarray(p["cog_mm"], float)) for p in downstream(concept, part, parts)]
    if payload_kg > 0:
        tl = m.tool_link
        pts.append((payload_kg, tl, (T0[tl] @ np.append(m.tool_offset, 1.0))[:3]))
    b = part["body"]
    to_q = {k: Tq[k] @ np.linalg.inv(T0[k]) for k in T0}               # 零位 → 姿态 q（每根杆件一个刚体变换）
    P0 = interface_point(part["interfaces"]["load"])
    Pq = (to_q[b] @ np.append(P0, 1.0))[:3]
    F, M = np.zeros(3), np.zeros(3)
    for mass, body, c0 in pts:
        f = mass * g * factor
        cq = (to_q[body] @ np.append(c0, 1.0))[:3]
        F += f
        M += np.cross((cq - Pq) / 1000.0, f)
    R = to_q[b][:3, :3].T                                               # 姿态 q 的向量 → 支架零位坐标
    return {"point_mm": [round(float(x), 4) for x in P0], "force_n": [round(float(x), 5) for x in R @ F],
            "moment_nm": [round(float(x), 6) for x in R @ M], "mass_kg": round(sum(x[0] for x in pts), 4),
            "gravity_m_s2": [round(float(x), 5) for x in R @ (g * factor)]}


# ---------------- 几何：从装配里取出单个支架、按接口选面 ----------------

def extract(assembly_step: str | Path, part: Mapping, out_step: str | Path) -> None:
    """从装配 STEP 里按体积与重心认出这个零件，单独写成 STEP（坐标不变）"""
    from analysis.fea.geometry import _LOCK, _gmsh

    with _LOCK:
        gm = _gmsh()
        gm.clear()
        gm.model.add("pick")
        gm.option.setString("Geometry.OCCTargetUnit", "MM")
        gm.model.occ.importShapes(str(assembly_step))
        gm.model.occ.synchronize()
        hit, rest = [], []
        for _, t in gm.model.getEntities(3):
            v = gm.model.occ.getMass(3, t)
            c = np.array(gm.model.occ.getCenterOfMass(3, t))
            same = abs(v - part["volume_mm3"]) <= 1e-3 * part["volume_mm3"] + 0.5 and np.linalg.norm(c - part["cog_mm"]) < 0.05
            (hit if same else rest).append(t)
        if len(hit) != 1:
            gm.clear()
            raise FeaError(f"装配里认不出 {part['name']}（匹配到 {len(hit)} 个实体）")
        gm.model.occ.remove([(3, t) for t in rest], recursive=True)
        gm.model.occ.synchronize()
        gm.write(str(out_step))
        gm.clear()


def _face_nodes(step: str | Path) -> dict[int, np.ndarray]:
    from analysis.fea.geometry import _LOCK, _gmsh, load_step

    with _LOCK, tempfile.TemporaryDirectory() as tmp:
        gm = _gmsh()
        load_step(gm, step, tmp)
        gm.option.setNumber("Mesh.MeshSizeMax", 1.0)
        gm.model.mesh.generate(2)
        out = {}
        for _, tag in gm.model.getEntities(2):
            _, xyz, _ = gm.model.mesh.getNodes(2, tag, includeBoundary=True)
            out[int(tag)] = np.asarray(xyz, float).reshape(-1, 3)
        gm.clear()
    return out


def _on_hole(P: np.ndarray, c, ax, r: float, L: float) -> bool:
    d = P - np.asarray(c, float)
    a = d @ ax
    rad = np.linalg.norm(d - np.outer(a, ax), axis=1)
    return bool(np.all(np.abs(rad - r) < TOL_MM) and np.all(np.abs(a) <= L / 2 + TOL_MM))


def _on_socket(P: np.ndarray, s: Mapping) -> bool:
    d0, u = np.asarray(s["start"], float), np.asarray(s["dir"], float)
    xd = np.asarray(s["xdir"], float)
    xd = xd - (xd @ u) * u
    xd /= np.linalg.norm(xd)
    yd = np.cross(u, xd)
    D = P - d0
    a, x, y = D @ u, D @ xd, D @ yd
    if np.any(a < -TOL_MM) or np.any(a > s["length_mm"] + TOL_MM):
        return False
    bottom = np.abs(a) < TOL_MM
    sec = s["section"]
    if sec["shape"] == "circle":
        r = np.hypot(x, y)
        R = sec["outer"] / 2
        return bool(np.all(bottom & (r <= R + TOL_MM)) or np.all(np.abs(r - R) < TOL_MM))
    w, h = sec["outer"]
    inside = (np.abs(x) <= w / 2 + TOL_MM) & (np.abs(y) <= h / 2 + TOL_MM)
    wall = (np.abs(np.abs(x) - w / 2) < TOL_MM) | (np.abs(np.abs(y) - h / 2) < TOL_MM)
    return bool(np.all(inside & (bottom | wall)) and (np.all(bottom) or np.all(np.abs(np.abs(x) - w / 2) < TOL_MM)
                                                         or np.all(np.abs(np.abs(y) - h / 2) < TOL_MM)))


def select_faces(nodes: Mapping[int, np.ndarray], itf: Mapping) -> list[int]:
    """接口上的面（面编号与 analysis fea 的面清单一致）；孔组要每个孔都选到面"""
    if itf["type"] == "holes":
        ax = np.asarray(itf["axis"], float)
        out = []
        for c in itf["centers"]:
            fs = [f for f, P in nodes.items() if len(P) and _on_hole(P, c, ax, itf["radius_mm"], itf["length_mm"])]
            if not fs:
                raise FeaError(f"孔 {c} 在零件上找不到孔壁")
            out += fs
        return sorted(set(out))
    if itf["type"] == "socket":
        out = [f for f, P in nodes.items() if len(P) and _on_socket(P, itf)]
    else:
        p, n = np.asarray(itf["point"], float), np.asarray(itf["normal"], float)
        out = [f for f, P in nodes.items() if len(P) and np.all(np.abs((P - p) @ n) < TOL_MM)]
    if not out:
        raise FeaError(f"接口 {itf['type']} 在零件上找不到面")
    return sorted(out)


# ---------------- 算例与判定 ----------------

def study(part: Mapping, step: str | Path, load: Mapping, *, mesh_mm: float = MESH_MM, convergence: bool = True) -> dict:
    nodes = _face_nodes(step)
    fixed = select_faces(nodes, part["interfaces"]["fixed"])
    li = part["interfaces"]["load"]
    loaded = select_faces(nodes, li)
    if li.get("seat"):                                   # 载荷经贴合面与孔壁一起传进来（只加在孔壁上，孔边是加载造成的奇异点）
        loaded = sorted(set(loaded) | set(select_faces(nodes, dict(li["seat"], type="plane"))))
    if set(fixed) & set(loaded):
        raise FeaError(f"{part['name']}：固定面与受载面重叠")
    return {"format": "fea-study/1", "name": part["name"],
            "bodies": [{"id": "b", "step_path": str(step), "material": part.get("material") or "6061-T6"}],
            "supports": [{"type": "fixed", "body": "b", "faces": fixed}],
            "loads": [{"type": "remote_load", "body": "b", "faces": loaded, "point_mm": load["point_mm"],
                       "force_n": load["force_n"], "vector_nm": load["moment_nm"]},
                      {"type": "gravity", "body": "b", "acceleration_m_s2": load["gravity_m_s2"]}],
            "steps": [{"id": "s1", "type": "static"}], "mesh": {"size_mm": mesh_mm},
            "checks": {"convergence": convergence}}


def judge(res: Mapping, material: str, required: float | None) -> dict:
    from analysis.common import materials

    if res.get("status") != "ok":
        return {"status": "unknown", "note": f"有限元没算成：{'；'.join(res.get('messages') or [])}"}
    s = res["data"]["steps"][0]
    tr = (s.get("trust") or {}).get("verdict")
    vm = s.get("vm_max_mpa")
    mat = materials.get(material)
    se = mat.get("fatigue_limit_bending_mpa")
    out = {"vm_max_mpa": None if vm is None else round(vm, 2), "u_max_mm": s.get("u_max_mm"), "trust": tr,
           "safety_yield": s.get("safety_factor"), "safety_fatigue": None if (vm is None or not se) else round(se / vm, 2),
           "balance": s.get("balance")}
    if tr != "pass" or out["safety_yield"] is None:
        bad = [f"{i['name']}：{i['text']}" for i in (s.get("trust") or {}).get("items", []) if i.get("verdict") != "pass"]
        return dict(out, status="unknown", note=f"有限元可信度 {tr}：" + ("；".join(bad) or s.get("safety_factor_withheld") or ""))
    if out["safety_fatigue"] is None:
        return dict(out, status="unknown", note=f"材料 {material} 缺弯曲疲劳极限")
    if required is None:
        return dict(out, status="unknown", note="需求没给安全系数要求")
    worst = min(out["safety_yield"], out["safety_fatigue"])
    return dict(out, status="pass" if worst >= required else "fail",
                note=f"最大当量应力 {vm:.1f} MPa；对屈服 {out['safety_yield']:.1f}、对弯曲疲劳 {out['safety_fatigue']:.1f}，要求 ≥ {required:g}")


def analyse(concept: Mapping, build_result: Mapping, cad_result: Mapping, verify_result: Mapping, assembly_step: str | Path,
            payload_kg: float, *, joints=None, work_dir: str | Path | None = None, convergence: bool = True,
            on_item=None) -> dict:
    """on_item：每算完一件回调一次（命令行用它边算边打印，一件要几分钟）"""
    import analysis

    factor = dynamic_factor(verify_result)
    q = build_result["duty"]["initial"]
    required = next(iter(build_result["picks"].values()))["requirement"].get("safety_factor")
    parts = cad_result["parts"]
    items = []
    with tempfile.TemporaryDirectory() as tmp:
        wd = Path(work_dir or tmp)
        wd.mkdir(parents=True, exist_ok=True)
        for k, p in enumerate(parts):
            if p["kind"] != "bracket" or (joints and p["joint"] not in joints):
                continue
            itf = p.get("interfaces") or {}
            row = {"part": p["name"], "joint": p["joint"], "role": p["role"]}
            if not itf.get("load"):
                items.append(dict(row, status="unknown", note="没有载荷接口（末端不接杆件），不分析"))
                continue
            ld = load_on(concept, p, parts, payload_kg, q, factor)
            step = wd / f"bracket-{k:02d}.step"
            try:
                extract(assembly_step, p, step)
                st_ = study(p, step, ld, convergence=convergence)
            except FeaError as ex:                     # 取不出零件、选不到接口面：这一件判不了，其余照算
                items.append(dict(row, load=ld, status="unknown", note=f"建不成算例：{ex}"))
                continue
            res = analysis.run("fea", st_)
            items.append(dict(row, load=ld, **judge(res, p.get("material") or "6061-T6", required)))
            if on_item:
                on_item(items[-1])
    st = {i["status"] for i in items}
    status = "fail" if "fail" in st else "unknown" if ("unknown" in st or not items) else "pass"
    return {"status": status, "items": items, "dynamic_factor": round(factor, 3), "pose_deg": q,
            "required_safety": required, "limits": LIMITS}


def summary(r: Mapping) -> str:
    lines = [f"支架强度：{r['status']}（动载系数 {r['dynamic_factor']}，要求安全系数 ≥ {r['required_safety']}）"]
    for i in r["items"]:
        ld = i.get("load")
        lt = "" if not ld else (f"挑起 {ld['mass_kg']} kg，力 {math.hypot(*ld['force_n']):.1f} N、"
                                f"力矩 {math.hypot(*ld['moment_nm']):.2f} N·m；")
        lines.append(f"  {i['part']}：{i['status']}；{lt}{i.get('note', '')}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="python -m assist.robot_fea", description="自制支架强度有限元（ADR-0115 44.3）")
    ap.add_argument("out_dir", type=Path, help="整机结果目录（concept-result.json、build-result.json、verify-result.json、cad/）")
    ap.add_argument("--joints", help="只算这些关节的支架，逗号分隔")
    ap.add_argument("-o", "--out", type=Path)
    a = ap.parse_args(argv)
    d = a.out_dir
    cr = json.loads((d / "concept-result.json").read_text(encoding="utf-8"))
    r = analyse(cr["chosen"], json.loads((d / "build-result.json").read_text(encoding="utf-8")),
                json.loads((d / "cad" / "cad-result.json").read_text(encoding="utf-8")),
                json.loads((d / "verify-result.json").read_text(encoding="utf-8")), d / "cad" / "assembly.step",
                float(cr["conditions"]["payload"]), joints=a.joints.split(",") if a.joints else None,
                on_item=lambda i: print(f"  {i['part']}：{i['status']}；{i.get('note', '')}", file=sys.stderr, flush=True))
    print(summary(r), file=sys.stderr)
    if a.out:
        a.out.write_text(json.dumps(r, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return 0 if r["status"] != "fail" else 1


if __name__ == "__main__":
    raise SystemExit(main())
