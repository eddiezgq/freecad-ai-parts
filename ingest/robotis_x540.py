"""DYNAMIXEL X540 壳体（XM540 / XH540 / XD540，铰接型 HINGE）的机械接口与外形（ADR-0115 44.3 之二第 2 步，ADR-0117）。

来源：ROBOTIS e-Manual “Drawings”一节的图纸 PDF 与 STEP（项目负责人 2026-11-22 下载，放 data/raw/robotis/，不入库；SHA-256 登记在
data/sources.yaml 的 robotis 下）。数值由 FreeCAD 从 STEP 量得（measure_step，method = measured），再与图纸上的标注逐项核对一致；
本表是核对后的结果，测试在有 STEP 和 FreeCAD 的环境里重新量一遍与本表比（tests/test_robotis_x540.py）。

组件坐标系（零件库约定：原点在输出法兰面中心，z 指向输出方向）：原点在输出舵盘端面中心，z 沿输出轴向外。
STEP 的坐标原点在输出轴线与壳体前后两面的中间，z 同向；换算 z_组件 = z_STEP − 24.5。
y 轴：壳体在输出轴线下方长（轴线距顶面 13.75、距底面 44.75），+y 指向顶面；x 轴与之正交（壳宽 33.5 对称）。
"""

from __future__ import annotations

SRC_STEP = "src-robotis-x540-step"
SRC_DRAWING = "src-robotis-x540-drawing"
MODELS = ("xm540-w150", "xm540-w270", "xh540-w150", "xh540-w270", "xh540-v150", "xh540-v270", "xd540-t150", "xd540-t270")
Z0 = 24.5                                     # STEP 中输出舵盘端面的 z

# 量得的特征（STEP 坐标，mm），与图纸核对
MEASURED = {
    "body_x": (-16.75, 16.75),               # 图纸 33.5
    "body_y": (-44.75, 13.75),               # 图纸 58.5，轴线距顶面 13.75
    "body_z": (-22.0, 22.0),                 # 图纸 44
    "horn_face_z": 24.5,                     # 前后舵盘端面 ±24.5（壳体面外 2.5）
    "horn_diameter": 26.0,                   # 图纸 Ø26（HN13-I101）
    "horn_hole_pcd": 22.0,                   # 8-M2.5 TAP DP2.5，P.C.D Ø22（前后两个舵盘都有）
    "horn_hole_count": 8,
    "horn_hole_radius": 1.025,               # 攻丝底孔 Ø2.05（M2.5）
    "boss_front_z": 29.8,                    # 输出端中心螺钉与凸台最高处
    "boss_diameter": 10.0,                   # 图纸 Ø10
    "side_holes": {"x": 16.75, "y": (-6.0, -38.0), "z": (-8.0, 8.0)},      # 4-M2.5 TAP DP4.0，两侧各 4 个：间距 32 × 16
    "bottom_holes": {"y": -44.75, "x": (-10.0, 10.0), "z": (-8.0, 8.0)},   # 4-M2.5 TAP DP4.0：间距 20 × 16
}


def _pv(value, note: str, *, doc: str = SRC_STEP, method: str = "measured") -> dict:
    return {"value": value, "source": {"doc": doc, "page": 1, "note": note}, "method": method, "confidence": 1.0, "reviewed": True}


NOTE = "FreeCAD 从 STEP 量得（几何精确值，容差 ±0.01 mm），与图纸标注核对一致（2026-11-22 Claude，经张国庆授权，ADR-0040）"


def _flange(port_id: str, z: float, axis: list[float], what: str) -> dict:
    m = MEASURED
    return {"id": port_id, "type": "mechanical.flange", "dir": "out" if axis[2] > 0 else "bidir", "motion": "rotating",
            "frame": {"origin_mm": [0.0, 0.0, z], "axis": axis},
            "spec": {"pcd_mm": _pv(m["horn_hole_pcd"], f"{what}：8-M2.5 TAP DP2.5，P.C.D Ø22；{NOTE}"),
                     "hole_count": _pv(m["horn_hole_count"], f"{what}：8 孔；{NOTE}"),
                     "hole_kind": _pv("threaded", f"{what}：TAP；{NOTE}"),
                     "thread": _pv("M2.5", f"{what}：M2.5x.45；{NOTE}"),
                     "hole_angle_offset_deg": _pv(0.0, f"{what}：第一个孔在 +x 方向（孔在 0°、45°……）；{NOTE}")},
            "note": f"{what}（舵盘 HN13-I101，Ø26）"}


def _rect(port_id: str, origin: list[float], axis: list[float], px: float, py: float, what: str, along: str) -> dict:
    return {"id": port_id, "type": "mechanical.mount_face", "dir": "bidir", "motion": "stationary",
            "frame": {"origin_mm": origin, "axis": axis},
            "spec": {"pattern": _pv("rect", f"{what}；{NOTE}"),
                     "pitch_x_mm": _pv(px, f"{what}：孔距 {px:g}（{along}）；{NOTE}"),
                     "pitch_y_mm": _pv(py, f"{what}：孔距 {py:g}；{NOTE}"),
                     "hole_count": _pv(4, f"{what}：4 孔；{NOTE}"),
                     "thread": _pv("M2.5", f"{what}：4-M2.5x.45 TAP DP4.0；{NOTE}")},
            "note": f"{what}；pitch_x 沿{along}"}


def ports() -> list[dict]:
    """X540 壳体的机械端口（组件坐标系）"""
    m = MEASURED
    zf, zb = m["horn_face_z"] - Z0, -m["horn_face_z"] - Z0
    sy = sum(m["side_holes"]["y"]) / 2
    return [
        _flange("output_flange", zf, [0.0, 0.0, 1.0], "输出舵盘"),
        _flange("idler_flange", zb, [0.0, 0.0, -1.0], "背面惰轮舵盘（随输出同轴、不出力，铰接支撑用）"),
        _rect("mount_side_r", [m["side_holes"]["x"], sy, -Z0], [1.0, 0.0, 0.0], 16.0, 32.0, "右侧面安装孔", "输出轴方向"),
        _rect("mount_side_l", [-m["side_holes"]["x"], sy, -Z0], [-1.0, 0.0, 0.0], 16.0, 32.0, "左侧面安装孔", "输出轴方向"),
        _rect("mount_bottom", [0.0, m["bottom_holes"]["y"], -Z0], [0.0, -1.0, 0.0], 20.0, 16.0, "底面安装孔", "壳宽方向"),
    ]


def envelope() -> dict:
    """外形：壳体（截面按轴线居中取保守：高取轴线到底面距离的两倍）+ 前后舵盘 + 前端中心凸台"""
    m = MEASURED
    w = m["body_x"][1] - m["body_x"][0]
    h2 = 2 * max(abs(m["body_y"][0]), abs(m["body_y"][1]))
    L = m["body_z"][1] - m["body_z"][0]
    f = "零件库包络按轴线居中：壳体偏在轴线下方（轴线距顶 13.75、距底 44.75），高取 2 × 44.75（保守）"
    horn = m["horn_face_z"] - m["body_z"][1]
    boss = m["boss_front_z"] - m["horn_face_z"]

    def part(shape, label, z, length, **dims):
        out = {"shape": shape, "label": label, "z_start_mm": round(z, 3), "length_mm": _pv(round(length, 3), f"{label}：{NOTE}")}
        for k, v in dims.items():
            out[k] = _pv(round(v, 3), f"{label}：{NOTE}；{f}" if k == "height_mm" else f"{label}：{NOTE}",
                         method="computed" if k == "height_mm" else "measured")
            if k == "height_mm":
                out[k]["source"]["formula"] = "2 × 轴线到底面距离"
        return out

    return {"parts": [part("box", "body", m["body_z"][0] - Z0, L, width_mm=w, height_mm=h2),
                      part("cylinder", "output_horn", m["body_z"][1] - Z0, horn, diameter_mm=m["horn_diameter"]),
                      part("cylinder", "idler_horn", -m["horn_face_z"] - Z0, horn, diameter_mm=m["horn_diameter"]),
                      part("cylinder", "boss", 0.0, boss, diameter_mm=m["boss_diameter"])]}


def measure_step(path) -> dict:
    """在 FreeCAD 里量 STEP（测试用来复核 MEASURED）：外形范围、舵盘端面、8 孔分度圆、侧面与底面孔位"""
    import Part

    s = Part.Shape()
    s.read(str(path))
    bb = s.BoundBox
    out = {"bbox": (bb.XMin, bb.XMax, bb.YMin, bb.YMax, bb.ZMin, bb.ZMax), "holes": []}
    for f in s.Faces:
        su = f.Surface
        if type(su).__name__ == "Cylinder" and abs(su.Radius - 1.025) < 1e-6:
            c, a = su.Center, su.Axis
            out["holes"].append(((round(c.x, 3), round(c.y, 3), round(c.z, 3)), (round(a.x, 3), round(a.y, 3), round(a.z, 3))))
        if type(su).__name__ == "Plane" and f.Area > 200:
            n = f.normalAt(0.5, 0.5)
            if abs(abs(n.z) - 1) < 1e-9 and f.BoundBox.XLength < 26.5:
                out.setdefault("horn_faces", []).append(round(f.BoundBox.ZMin, 3))
    out["holes"] = sorted(set(out["holes"]))         # 一个圆柱孔在 STEP 里常分成两片面：去重
    return out
