"""算例面引用的“面签名”与重新认面（ADR-0125；问渠 CAD 0.3.6 细则 B3，《有限元》书第 47 章线索第 40 条）。

面编号是 gmsh 读 STEP 时排的，几何一改就可能变。写算例时给被引用的面记下签名（类型、面积、中心、法向 / 轴线）和 STEP 的
SHA-256；计算时散列变了就按签名在新几何里重新认面，认不准就拒绝计算，不静默沿用面号。纯几何比较，不联网、不调用 LLM。
"""

from __future__ import annotations

import copy
import hashlib
import math
from pathlib import Path

ANGLE_DEG = 1.0                  # 法向 / 轴线夹角上限
AREA_RATIO = (0.5, 2.0)          # 面积比在这个范围外：认不准
UNIQUE_FACTOR = 2.0              # 第二近的候选至少要远到最近者的这么多倍（且多出 UNIQUE_MARGIN），才算唯一
UNIQUE_MARGIN = 0.02             # 按包围盒对角线归一的距离


class FaceRefError(ValueError):
    pass


def sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def signature(face: dict) -> dict:
    sig = {"kind": face.get("kind", "other"), "area_mm2": float(face["area_mm2"]), "center_mm": [float(x) for x in face["center"]]}
    if face.get("normal"):
        sig["normal"] = [float(x) for x in face["normal"]]
    if face.get("axis"):
        sig["axis"] = [float(x) for x in face["axis"]]
    return sig


def _refs(study: dict):
    """(实体 id, 装面号的列表) ——支承、载荷、各工况的载荷、连接两侧、探针"""
    for x in (study.get("supports") or []) + (study.get("loads") or []) + (study.get("probes") or []):
        if x.get("body") and x.get("faces"):
            yield x["body"], x["faces"]
    for lc in study.get("load_cases") or []:
        for x in lc.get("loads") or []:
            if x.get("body") and x.get("faces"):
                yield x["body"], x["faces"]
    for c in study.get("connections") or []:
        for side in ("a", "b"):
            s = c.get(side) or {}
            if s.get("body") and s.get("faces"):
                yield s["body"], s["faces"]


def _faces(step_path):
    from analysis.fea import geometry

    fs, _ = geometry.faces(step_path)
    return fs


def sign(study: dict, faces_of=_faces) -> dict:
    """给算例里的每个实体记下 STEP 散列和被引用面的签名（只记引用到的面）。返回新算例，不改原来的"""
    s = copy.deepcopy(study)
    used = {}
    for bid, ids in _refs(s):
        used.setdefault(bid, set()).update(int(i) for i in ids)
    for b in s.get("bodies") or []:
        p = b.get("step_path")
        if not p or not Path(p).is_file() or b["id"] not in used:
            continue
        byid = {int(f["id"]): f for f in faces_of(p)}
        b["step_sha256"] = sha256(p)
        b["face_signatures"] = {str(i): signature(byid[i]) for i in sorted(used[b["id"]]) if i in byid}
    return s


def _dir_ok(a, b, both_ways):
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    d = sum(x * y for x, y in zip(a, b, strict=True)) / (math.hypot(*a) * math.hypot(*b) or 1.0)
    return (abs(d) if both_ways else d) >= math.cos(math.radians(ANGLE_DEG))


def match(sig: dict, faces: list[dict], diag: float):
    """在新面清单里找签名对应的面：返回 (面号, 说明)；认不准返回 (None, 原因)"""
    cand = []
    for f in faces:
        if f.get("kind", "other") != sig["kind"]:
            continue
        if not _dir_ok(sig.get("normal"), f.get("normal"), False) or not _dir_ok(sig.get("axis"), f.get("axis"), True):
            continue
        cand.append((math.dist(sig["center_mm"], f["center"]) / diag, f))
    if not cand:
        return None, "新几何里没有类型、方向都对得上的面"
    cand.sort(key=lambda x: x[0])
    d0, f0 = cand[0]
    ratio = float(f0["area_mm2"]) / sig["area_mm2"]
    if not AREA_RATIO[0] <= ratio <= AREA_RATIO[1]:
        return None, f"最像的面 {f0['id']} 面积差太多（新 / 旧 = {ratio:.2f}）"
    if len(cand) > 1:
        d1 = cand[1][0]
        if d1 < UNIQUE_FACTOR * d0 + UNIQUE_MARGIN and d1 - d0 < UNIQUE_MARGIN * 5:
            return None, f"面 {f0['id']} 和面 {cand[1][1]['id']} 一样像，分不清"
    return int(f0["id"]), f"中心移动 {d0 * diag:.3g} mm、面积比 {ratio:.3g}"


def reconcile(study: dict, faces_of=_faces) -> tuple[dict, dict]:
    """计算前核对面引用。返回 (可能改了面号的算例, 说明 {实体 id: {status, map?, note}})；认不准抛 FaceRefError"""
    s = copy.deepcopy(study)
    report, remaps, bad = {}, {}, []
    used = {}
    for bid, ids in _refs(s):
        used.setdefault(bid, set()).update(int(i) for i in ids)
    for b in s.get("bodies") or []:
        bid = b["id"]
        if bid not in used:
            continue
        sigs = b.get("face_signatures")
        if not sigs or not b.get("step_sha256"):
            report[bid] = {"status": "unchecked", "note": "面引用未核对：算例没有面签名（旧算例），几何改过的话面号可能已经指到别的面"}
            continue
        if sha256(b["step_path"]) == b["step_sha256"]:
            report[bid] = {"status": "same", "note": "STEP 文件没变，面号照用"}
            continue
        fs = faces_of(b["step_path"])
        lo = [min(f["center"][k] for f in fs) for k in range(3)]
        hi = [max(f["center"][k] for f in fs) for k in range(3)]
        diag = math.dist(lo, hi) or 1.0
        m, why = {}, {}
        for i in sorted(used[bid]):
            sig = sigs.get(str(i))
            if sig is None:
                bad.append(f"实体 {bid} 的面 {i} 没有签名")
                continue
            new, msg = match(sig, fs, diag)
            if new is None:
                bad.append(f"实体 {bid} 的面 {i}：{msg}")
            else:
                m[i], why[i] = new, msg
        if len(set(m.values())) < len(m):
            bad.append(f"实体 {bid}：两个旧面认成了同一个新面 {sorted(m.items())}")
        remaps[bid] = m
        report[bid] = {"status": "remapped", "map": {str(k): v for k, v in m.items()},
                       "note": "STEP 文件改过，按面签名重新认面：" + "；".join(f"{k} → {v}（{why[k]}）" for k, v in m.items())}
    if bad:
        raise FaceRefError("几何改过，面引用认不准，不能计算，请人确认支承、载荷放在哪些面上：" + "；".join(bad))
    for bid, ids in _refs(s):
        if bid in remaps:
            ids[:] = [remaps[bid].get(int(i), int(i)) for i in ids]
    for b in s.get("bodies") or []:
        if b["id"] in remaps:                                   # 新几何上重新记签名，下次就按新文件比
            b.pop("face_signatures", None)
            b.pop("step_sha256", None)
    s = sign(s, faces_of) if remaps else s
    return s, report
