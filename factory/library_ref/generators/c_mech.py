# -*- coding: utf-8 -*-
"""C 部分：问渠自建机构（第 5 轮第 6 步，P9；R5 运动表）。

engine: wqmech:<型式>，参数取条目 defaults（米、度、齿数）。机构坐标系：平面机构在竖直 XZ 平面内，转角绕 −Y 轴
（从 −Y 方向看逆时针为正）；齿轮轴沿 Y。每个构件一个节点（父节点为机构根），位姿 = 运动表输入为起点值时的位姿。
返回 [("__scene__", {bodies, world, mechanism, motion})]；运动表格式见接口约定 2.4。
    four_bar   曲柄摇杆四杆机构          slider_crank  曲柄滑块机构         cam       盘形凸轮 + 直动滚子从动件
    gear_train 两级定轴齿轮系（也用于 WQR-105）  worm  蜗杆蜗轮           belt      开口带传动
    ratchet    棘轮机构                  geneva   外槽轮（日内瓦）机构     lead_screw 丝杠螺母
"""
import math

import numpy as np

GREY, BLUE, DARK, YEL, RED = [205, 210, 214, 255], [60, 120, 170, 255], [70, 76, 82, 255], [242, 183, 5, 255], [196, 74, 60, 255]


# ---------------------------------------------------------------- 小工具
def _Ry(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def _Rx(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])


def rot(phi):
    """平面内转角 φ（绕 −Y）"""
    return _Ry(-phi)


def _quat(R):
    w = math.sqrt(max(0.0, 1 + R[0, 0] + R[1, 1] + R[2, 2])) / 2
    x = math.copysign(math.sqrt(max(0.0, 1 + R[0, 0] - R[1, 1] - R[2, 2])) / 2, R[2, 1] - R[1, 2])
    y = math.copysign(math.sqrt(max(0.0, 1 - R[0, 0] + R[1, 1] - R[2, 2])) / 2, R[0, 2] - R[2, 0])
    z = math.copysign(math.sqrt(max(0.0, 1 - R[0, 0] - R[1, 1] + R[2, 2])) / 2, R[1, 0] - R[0, 1])
    return [w, x, y, z]


def _mesh(m, color):
    m.visual.face_colors = color
    return m


def cyl_y(r, h, color, center=(0, 0, 0)):
    import trimesh
    m = trimesh.creation.cylinder(radius=r, height=h, sections=40)
    m.apply_transform(trimesh.transformations.rotation_matrix(math.pi / 2, [1, 0, 0]))
    m.apply_translation(center)
    return _mesh(m, color)


def cyl_x(r, h, color, center=(0, 0, 0)):
    import trimesh
    m = trimesh.creation.cylinder(radius=r, height=h, sections=40)
    m.apply_transform(trimesh.transformations.rotation_matrix(math.pi / 2, [0, 1, 0]))
    m.apply_translation(center)
    return _mesh(m, color)


def box(ext, color, center=(0, 0, 0)):
    import trimesh
    m = trimesh.creation.box(extents=ext)
    m.apply_translation(center)
    return _mesh(m, color)


def cat(*ms):
    import trimesh
    return trimesh.util.concatenate([m for m in ms if m is not None])


def bar(L, w, t, color, y=0.0):
    """平面连杆：从局部原点沿 +x 到 (L, 0)，两端铰链孔处画圆柱"""
    return cat(box([L, t, w], color, (L / 2, y, 0)), cyl_y(w * 0.7, t * 1.3, DARK, (0, y, 0)), cyl_y(w * 0.7, t * 1.3, DARK, (L, y, 0)))


def from_shape(shape, color, tol=0.05):
    """build123d 形体（毫米）→ trimesh（米）"""
    import trimesh
    v, f = shape.tessellate(tol, 0.3)
    m = trimesh.Trimesh(np.array([[p.X, p.Y, p.Z] for p in v]) / 1000.0, np.array(f), process=False)
    return _mesh(m, color)


def polygon_prism(pts_xz, t, color, y=0.0):
    """XZ 平面内的多边形（米）沿 Y 拉伸成厚 t 的板"""
    import trimesh
    from shapely.geometry import Polygon
    m = trimesh.creation.extrude_polygon(Polygon(pts_xz), t)          # 在 XY 平面、沿 +Z 拉伸
    m.apply_translation([0, 0, -t / 2])
    m.apply_transform(trimesh.transformations.rotation_matrix(math.pi / 2, [1, 0, 0]))   # (x, y, z) → (x, −z, y)：多边形到 XZ 平面
    m.apply_translation([0, y, 0])
    return _mesh(m, color)


class Scene:
    """收集构件与运动表：pose(id) 返回 (位置, 旋转矩阵)"""

    def __init__(self, dof=1):
        self.bodies, self.members, self.dof = [], [], dof

    def add(self, mid, zh, en, mesh, ground=False):
        self.bodies.append({"name": mid, "parent": None, "pos": [0.0, 0.0, 0.0], "quat": [1.0, 0.0, 0.0, 0.0], "mesh": mesh})
        self.members.append({"id": mid, "name": {"zh": zh, "en": en}, "node": mid, **({"ground": True} if ground else {})})

    def finish(self, poses_at, inputs, unit, inp_member, inp_type="rotation", extra=None, path=None):
        import trimesh
        ids = [m["id"] for m in self.members if not m.get("ground")]
        header = ["input"] + ["{}.{}".format(i, k) for i in ids for k in ("x_m", "y_m", "z_m", "qx", "qy", "qz", "qw")]
        rows = []
        for u in inputs:
            ps = poses_at(u)
            if ps is None:
                continue
            row = [round(u, 6) if isinstance(u, float) else u]
            for i in ids:
                pos, R = ps[i]
                w, x, y, z = _quat(R)
                row += [round(float(v), 6) for v in pos] + [round(x, 6), round(y, 6), round(z, 6), round(w, 6)]
            rows.append(row)
        first = poses_at(inputs[0])
        world = []
        for b in self.bodies:
            if b["name"] in first:
                pos, R = first[b["name"]]
                b["pos"], b["quat"] = [float(v) for v in pos], _quat(R)
                M = np.eye(4)
                M[:3, :3], M[:3, 3] = R, pos
            else:
                M = np.eye(4)
            world.append(b["mesh"].copy().apply_transform(M))
        step = inputs[1] - inputs[0] if len(inputs) > 1 else 0
        mech = {"dof": self.dof, "members": self.members,
                "input": {"member": inp_member, "type": inp_type, "unit": unit, "range": [inputs[0], inputs[-1]], "step": step,
                          **({"path": path} if path else {})},
                "motion": "motion.csv", **(extra or {})}
        return {"bodies": self.bodies, "world": trimesh.util.concatenate(world).apply_scale(1000.0), "mechanism": mech,
                "motion": (header, rows)}


I3 = np.eye(3)


def P(x, z, y=0.0):
    return np.array([x, y, z], float)


# ---------------------------------------------------------------- 四杆机构
def four_bar_solve(p, th2, branch=1):
    """曲柄转角 θ2（弧度）→ (A, B, θ3, θ4)；branch = +1 开式、−1 交叉式；无解返回 None"""
    a, b, c, d = p["crank_m"], p["coupler_m"], p["rocker_m"], p["ground_m"]
    A = np.array([a * math.cos(th2), a * math.sin(th2)])
    O4 = np.array([d, 0.0])
    v = O4 - A
    L = float(np.linalg.norm(v))
    if L > b + c or L < abs(b - c):
        return None
    x = (b * b - c * c + L * L) / (2 * L)
    h = math.sqrt(max(0.0, b * b - x * x))
    u = v / L
    n = np.array([-u[1], u[0]])
    B = A + x * u + branch * h * n
    th3 = math.atan2(B[1] - A[1], B[0] - A[0])
    th4 = math.atan2(B[1] - O4[1], B[0] - O4[0])
    return A, B, th3, th4


def freudenstein_th4(p, th2, branch=1):
    """弗洛伊登斯坦方程 K1 cosθ4 − K2 cosθ2 + K3 = cos(θ2 − θ4) 的闭式解（与 four_bar_solve 两种算法互核）"""
    a, b, c, d = p["crank_m"], p["coupler_m"], p["rocker_m"], p["ground_m"]
    K1, K2, K3 = d / a, d / c, (a * a - b * b + c * c + d * d) / (2 * a * c)
    A_ = math.cos(th2) - K1 - K2 * math.cos(th2) + K3
    B_ = -2 * math.sin(th2)
    C_ = K1 - (K2 + 1) * math.cos(th2) + K3
    disc = B_ * B_ - 4 * A_ * C_
    if disc < 0:
        return None
    return 2 * math.atan2(-B_ - branch * math.sqrt(disc), 2 * A_)


def four_bar(p):
    a, b, c, d = p["crank_m"], p["coupler_m"], p["rocker_m"], p["ground_m"]
    w, t = p["link_width_m"], p["link_thickness_m"]
    sc = Scene()
    sc.add("ground", "机架", "Ground", cat(cyl_y(w, t * 4, GREY, (0, 0, 0)), cyl_y(w, t * 4, GREY, (d, 0, 0)),
                                         box([d + 2 * w, t * 4, w * 0.6], GREY, (d / 2, 0, -1.6 * w)),
                                         box([w * 0.8, t * 4, 1.6 * w], GREY, (0, 0, -0.8 * w)), box([w * 0.8, t * 4, 1.6 * w], GREY, (d, 0, -0.8 * w))), ground=True)
    sc.add("crank", "曲柄", "Crank", bar(a, w, t, BLUE, y=-t * 1.2))
    sc.add("coupler", "连杆", "Coupler", cat(bar(b, w, t, GREY, y=0), cyl_y(w * 0.45, t, RED, (b / 2, -t * 0.8, 0.0))))
    sc.add("rocker", "摇杆", "Rocker", bar(c, w, t, BLUE, y=t * 1.2))

    def poses(deg):
        s = four_bar_solve(p, math.radians(deg))
        if s is None:
            return None
        A, B, th3, th4 = s
        return {"crank": (P(0, 0), rot(math.radians(deg))), "coupler": (P(A[0], A[1]), rot(th3)), "rocker": (P(d, 0), rot(th4))}
    lengths = sorted([a, b, c, d])
    grashof = lengths[0] + lengths[3] <= lengths[1] + lengths[2]
    return sc.finish(poses, list(range(0, 360, 2)), "deg", "crank",
                     extra={"analysis": {"grashof": grashof, "type": "曲柄摇杆" if grashof and min(lengths) == a else "其他",
                                         "coupler_point": {"member": "coupler", "xyz": [round(b / 2, 6), 0, 0], "zh": "连杆中点（红点）的轨迹即连杆曲线"}}})


# ---------------------------------------------------------------- 曲柄滑块
def slider_crank_x(p, th):
    r, l, e = p["crank_m"], p["rod_m"], p["offset_m"]
    s = r * math.sin(th) - e
    if abs(s) > l:
        return None
    return r * math.cos(th) + math.sqrt(l * l - s * s)


def slider_crank(p):
    r, l, e, w, t = p["crank_m"], p["rod_m"], p["offset_m"], p["link_width_m"], p["link_thickness_m"]
    sc = Scene()
    xs = [slider_crank_x(p, math.radians(k)) for k in range(0, 360, 2)]
    lo, hi = min(xs), max(xs)
    sc.add("ground", "机架（含导轨）", "Ground (with guide)",
           cat(cyl_y(w, t * 4, GREY), box([w * 0.8, t * 4, 1.6 * w], GREY, (0, 0, -0.8 * w)),
               box([hi - lo + 4 * w, t * 4, w * 0.4], GREY, ((lo + hi) / 2, 0, e - 1.2 * w)),
               box([hi - lo + 4 * w, t * 4, w * 0.4], GREY, ((lo + hi) / 2, 0, e + 1.2 * w))), ground=True)
    sc.add("crank", "曲柄", "Crank", bar(r, w, t, BLUE, y=-t * 1.2))
    sc.add("rod", "连杆", "Connecting rod", bar(l, w, t, GREY))
    sc.add("slider", "滑块", "Slider", box([2.4 * w, t * 3, 2 * w], BLUE))

    def poses(deg):
        th = math.radians(deg)
        x = slider_crank_x(p, th)
        if x is None:
            return None
        A = (r * math.cos(th), r * math.sin(th))
        phi = math.atan2(e - A[1], x - A[0])
        return {"crank": (P(0, 0), rot(th)), "rod": (P(*A), rot(phi)), "slider": (P(x, e), I3)}
    return sc.finish(poses, list(range(0, 360, 2)), "deg", "crank",
                     extra={"analysis": {"stroke_m": round(hi - lo, 6), "formula": {
                         "zh": "x = r·cosθ + √(l² − (r·sinθ − e)²)；对心（e = 0）时行程 = 2r",
                         "en": "x = r cos(th) + sqrt(l^2 - (r sin(th) - e)^2); stroke = 2r when e = 0"}}})


# ---------------------------------------------------------------- 盘形凸轮 + 直动滚子从动件
def cam_lift(p, phi_deg):
    """从动件位移 s(φ)：推程余弦加速度（简谐）规律、远休止、回程余弦、近休止"""
    h, r1, d1, r2 = p["lift_m"], p["rise_deg"], p["far_dwell_deg"], p["return_deg"]
    f = phi_deg % 360
    if f < r1:
        return h / 2 * (1 - math.cos(math.pi * f / r1))
    if f < r1 + d1:
        return h
    if f < r1 + d1 + r2:
        return h / 2 * (1 + math.cos(math.pi * (f - r1 - d1) / r2))
    return 0.0


def cam_profile(p, n=720):
    """凸轮实际轮廓（凸轮坐标系，XZ 平面）：理论轮廓（滚子中心轨迹）沿法向向内偏移滚子半径"""
    r0, rr = p["base_radius_m"], p["roller_radius_m"]
    pitch = []
    for k in range(n):
        f = 360.0 * k / n
        R = r0 + rr + cam_lift(p, f)
        a = math.pi / 2 - math.radians(f)                 # 凸轮逆时针转 φ ⇔ 从动件相对凸轮顺时针绕行
        pitch.append((R * math.cos(a), R * math.sin(a)))
    out = []
    for k in range(n):
        x0, z0 = pitch[k - 1]
        x2, z2 = pitch[(k + 1) % n]
        tx, tz = x2 - x0, z2 - z0
        L = math.hypot(tx, tz)
        nx, nz = tz / L, -tx / L                           # 绕行方向为顺时针时，这是指向外侧的法向
        x, z = pitch[k]
        if nx * x + nz * z < 0:
            nx, nz = -nx, -nz
        out.append((x - rr * nx, z - rr * nz))
    return pitch, out


def cam(p):
    r0, rr, h, t = p["base_radius_m"], p["roller_radius_m"], p["lift_m"], p["thickness_m"]
    pitch, prof = cam_profile(p)
    sc = Scene()
    top = r0 + rr + h
    sc.add("ground", "机架（含从动件导路）", "Ground (with guide)",
           cat(cyl_y(0.006, t * 3, GREY), box([0.012, t * 3, 0.012], GREY, (0, 0, -0.012)),
               box([0.004, t * 2, 0.05], GREY, (-0.01, 0, top + 0.03)), box([0.004, t * 2, 0.05], GREY, (0.01, 0, top + 0.03))), ground=True)
    sc.add("cam", "凸轮", "Cam", cat(polygon_prism(prof, t, BLUE), cyl_y(0.006, t * 1.4, DARK)))
    stem = 0.08
    sc.add("follower", "直动从动件（带滚子）", "Translating roller follower",
           cat(cyl_y(rr, t * 0.9, YEL), box([0.012, t * 0.6, stem], GREY, (0, 0, rr + stem / 2))))

    def poses(deg):
        return {"cam": (P(0, 0), rot(math.radians(deg))), "follower": (P(0, r0 + rr + cam_lift(p, deg)), I3)}
    return sc.finish(poses, list(range(0, 360, 2)), "deg", "cam",
                     extra={"analysis": {"law": "余弦加速度（简谐）推程与回程", "lift_m": h,
                                         "phases_deg": {"rise": p["rise_deg"], "far_dwell": p["far_dwell_deg"], "return": p["return_deg"],
                                                        "near_dwell": 360 - p["rise_deg"] - p["far_dwell_deg"] - p["return_deg"]}}})


# ---------------------------------------------------------------- 齿轮（bd_warehouse 渐开线直齿轮）
_GEAR_CACHE = {}


def spur(m_mm, z, b_mm, color):
    """渐开线直齿轮（bd_warehouse），轴线沿 Y、中心在原点；一个齿的齿槽对着 +X 方向（便于对齐啮合）。返回 (网格, 齿顶半径 米)"""
    key = (m_mm, z, b_mm)
    if key not in _GEAR_CACHE:
        from bd_warehouse.gear import SpurGear
        from build123d import Axis, Pos
        g = None
        for fil in (0.25 * m_mm, 0.1 * m_mm, None):      # 齿根圆角：个别齿数下圆角算法失败，就减小或不做
            try:
                g = SpurGear(module=m_mm, tooth_count=z, pressure_angle=20, thickness=b_mm, root_fillet=fil)
                break
            except ValueError:
                continue
        ra = m_mm * (z + 2) / 2
        # bd_warehouse 齿的方位：在齿顶圆附近 +X 处是齿还是槽？是齿就转半个齿距，让 +X 对着齿槽
        probe = Pos(ra - 0.3 * m_mm, 0, 0) * __import__("build123d").Box(0.05, 0.05, 0.05)
        if (g & probe).volume > 1e-6:
            g = g.rotate(Axis.Z, 180.0 / z)
        _GEAR_CACHE[key] = g.rotate(Axis.X, 90)            # 轴线从 Z 转到 Y
    return from_shape(_GEAR_CACHE[key], color), m_mm * (z + 2) / 2000


def mesh_phase(p):
    """啮合初相位：spur() 的齿轮 +X 方向是齿槽。右边齿轮在 −X 方向要对上左边齿轮 +X 方向的“齿槽/齿”：
    记左轮 +X 处的齿距分数 f（0 = 槽、0.5 = 齿），右轮转 π + 齿距·((f + 0.5) mod 1)。第一级 f = 0；
    这个规律用两组齿数按干涉体积最小验证过（tests/test_mechanisms.py 再查一次）"""
    z2, z3, z4 = (int(p[k]) for k in ("z2", "z3", "z4"))
    off2 = math.pi + 2 * math.pi / z2 * 0.5
    f3 = ((-off2) / (2 * math.pi / z3)) % 1.0
    off4 = math.pi + 2 * math.pi / z4 * ((f3 + 0.5) % 1.0)
    return off2, off4


def gear_train_layout(p):
    """两级定轴轮系：轴 I、II、III 沿 X 排列；返回各轴 x 坐标（米）与传动比"""
    m1, m2 = p["module1_mm"], p["module2_mm"]
    z1, z2, z3, z4 = (int(p[k]) for k in ("z1", "z2", "z3", "z4"))
    a1, a2 = m1 * (z1 + z2) / 2000, m2 * (z3 + z4) / 2000
    return {"x": [0.0, a1, a1 + a2], "a1_m": a1, "a2_m": a2, "i12": z2 / z1, "i34": z4 / z3, "i": z2 * z4 / (z1 * z3)}


def gear_train(p, names=None):
    m1, m2, b1, b2 = p["module1_mm"], p["module2_mm"], p["face1_mm"], p["face2_mm"]
    z1, z2, z3, z4 = (int(p[k]) for k in ("z1", "z2", "z3", "z4"))
    L = gear_train_layout(p)
    x1, x2, x3 = L["x"]
    names = names or {}
    g1, _ = spur(m1, z1, b1, BLUE)
    g2, ra2 = spur(m1, z2, b1, GREY)
    g3, _ = spur(m2, z3, b2, BLUE)
    g4, ra4 = spur(m2, z4, b2, GREY)
    y1, y2 = 0.0, (b1 + b2) / 2000 + 0.01                  # 第一级、第二级所在平面
    shaft = lambda r, y0, y1_: cyl_y(r, abs(y1_ - y0), DARK, (0, (y0 + y1_) / 2, 0))  # noqa: E731
    sc = Scene()
    span_y = (-b1 / 2000 - 0.03, y2 + b2 / 2000 + 0.03)
    sc.add("ground", names.get("ground", "机架（轴承座）"), "Ground (bearing supports)",
           cat(box([x3 + 2 * ra4, span_y[1] - span_y[0], 0.008], GREY, (x3 / 2, sum(span_y) / 2, -max(ra2, ra4) - 0.01)),
               *[box([0.03, 0.01, max(ra2, ra4) + 0.01], GREY, (x, yy, -(max(ra2, ra4) + 0.01) / 2)) for x in (x1, x2, x3) for yy in span_y]), ground=True)
    sc.add("shaft1", names.get("shaft1", "输入轴（齿轮 z1）"), "Input shaft (gear z1)", cat(g1, shaft(0.006, span_y[0], y1 + 0.02)))
    sc.add("shaft2", names.get("shaft2", "中间轴（齿轮 z2、z3）"), "Intermediate shaft (gears z2, z3)",
           cat(g2, g3.copy().apply_translation([0, y2, 0]), shaft(0.008, span_y[0] + 0.01, span_y[1] - 0.01)))
    sc.add("shaft3", names.get("shaft3", "输出轴（齿轮 z4）"), "Output shaft (gear z4)",
           cat(g4.copy().apply_translation([0, y2, 0]), shaft(0.01, y2 - 0.02, span_y[1] + 0.02)))
    off2, off4 = mesh_phase(p)

    def poses(deg):
        a = math.radians(deg)
        a2 = -a * z1 / z2
        a4 = -a2 * z3 / z4
        return {"shaft1": (P(x1, 0), rot(a)), "shaft2": (P(x2, 0), rot(a2 + off2)), "shaft3": (P(x3, 0), rot(a4 + off4))}
    rng = list(range(0, int(round(360 * L["i12"])) + 1, 4))           # 输入转 i12 圈 = 中间轴转一圈
    return sc.finish(poses, rng, "deg", "shaft1",
                     extra={"analysis": {"ratio": round(L["i"], 6), "stages": [round(L["i12"], 6), round(L["i34"], 6)],
                                         "center_distance_m": [round(L["a1_m"], 6), round(L["a2_m"], 6)],
                                         "formula": {"zh": "i = (z2·z4)/(z1·z3)；中心距 a = m(z1 + z2)/2；每级外啮合转向相反",
                                                     "en": "i = (z2 z4)/(z1 z3); a = m (z1 + z2)/2"}}})


# ---------------------------------------------------------------- 蜗杆蜗轮
def worm(p):
    m, z1, z2, q, b = p["module_mm"], int(p["worm_starts"]), int(p["wheel_teeth"]), p["diameter_factor"], p["wheel_face_mm"]
    d1, d2 = m * q / 1000, m * z2 / 1000
    a = (d1 + d2) / 2
    lead = math.pi * m * z1 / 1000
    gamma = math.atan(z1 / q)
    wheel, ra2 = spur(m, z2, b, GREY)
    Lw = max(6 * math.pi * m / 1000, 1.2 * b / 1000 * 3)
    # 蜗杆：根圆柱 + 螺旋线排列的小圆柱示意齿（不是真实齿形）
    import trimesh
    parts = [cyl_x(d1 / 2 - 1.1 * m / 1000, Lw, BLUE), cyl_x(0.004, Lw + 0.08, DARK)]
    nseg = int(Lw / lead * 48)
    for k in range(nseg):
        s = -Lw / 2 + Lw * k / nseg
        ang = 2 * math.pi * s / lead
        for st in range(z1):
            a_ = ang + 2 * math.pi * st / z1
            parts.append(_mesh(trimesh.creation.icosphere(subdivisions=1, radius=1.0 * m / 1000).apply_translation(
                [s, (d1 / 2 - 0.2 * m / 1000) * math.cos(a_), (d1 / 2 - 0.2 * m / 1000) * math.sin(a_)]), BLUE))
    sc = Scene()
    sc.add("ground", "机架", "Ground", cat(cyl_y(0.004, 0.06, GREY, (0, 0, 0)), box([0.01, 0.01, a + 0.03], GREY, (Lw / 2 + 0.03, 0, a / 2)),
                                          box([0.01, 0.01, a + 0.03], GREY, (-Lw / 2 - 0.03, 0, a / 2))), ground=True)
    sc.add("worm", "蜗杆（{} 头）".format(z1), "Worm ({} start)".format(z1), cat(*parts))
    sc.add("wheel", "蜗轮（{} 齿）".format(z2), "Worm wheel ({} teeth)".format(z2), cat(wheel, cyl_y(0.006, 0.05, DARK)))

    def poses(deg):
        a1 = math.radians(deg)
        a2 = a1 * z1 / z2
        return {"worm": (P(0, a), _Rx(a1)), "wheel": (P(0, 0), rot(a2))}
    return sc.finish(poses, list(range(0, 360 * 3 + 1, 10)), "deg", "worm",
                     extra={"analysis": {"ratio": z2 / z1, "center_distance_m": round(a, 6), "lead_angle_deg": round(math.degrees(gamma), 4),
                                         "formula": {"zh": "i = z2 / z1；a = m(q + z2)/2；导程角 tanγ = z1 / q（γ 小于当量摩擦角时自锁）",
                                                     "en": "i = z2/z1; a = m (q + z2)/2; tan(gamma) = z1/q"}},
                            "note": {"zh": "蜗杆螺旋齿与蜗轮齿为示意（蜗轮按同模数直齿轮画）", "en": "Thread and wheel teeth are schematic"}})


# ---------------------------------------------------------------- 开口带传动
def belt_geometry(p):
    D1, D2, a = p["d1_m"], p["d2_m"], p["center_m"]
    beta = math.asin((D2 - D1) / (2 * a))
    L = 2 * a * math.cos(beta) + math.pi * (D1 + D2) / 2 + beta * (D2 - D1)
    wrap1 = math.pi - 2 * beta
    return {"beta": beta, "length_m": L, "wrap_small_deg": math.degrees(wrap1), "ratio": D2 / D1}


def belt_path(p, n=360):
    """带的中线（XZ）：小轮在原点、大轮在 (a, 0)；两段切线 + 两段圆弧"""
    D1, D2, a = p["d1_m"], p["d2_m"], p["center_m"]
    r1, r2 = D1 / 2, D2 / 2
    beta = math.asin((r2 - r1) / a)
    pts = []
    for k in range(n // 2 + 1):                            # 小轮包角：从上切点绕到下切点（左侧）
        t = math.pi / 2 + beta + (math.pi - 2 * beta) * k / (n // 2)
        pts.append((r1 * math.cos(t), r1 * math.sin(t)))
    for k in range(n // 2 + 1):                            # 大轮包角：从下切点绕到上切点（右侧）
        t = -(math.pi / 2 + beta) + (math.pi + 2 * beta) * k / (n // 2)
        pts.append((a + r2 * math.cos(t), r2 * math.sin(t)))
    return pts


def belt(p):
    D1, D2, a, w = p["d1_m"], p["d2_m"], p["center_m"], p["width_m"]
    g = belt_geometry(p)
    import trimesh
    path = belt_path(p)
    th = 0.004
    from shapely.geometry import Polygon
    ring = Polygon(path).buffer(th / 2).difference(Polygon(path).buffer(-th / 2))
    bm = trimesh.creation.extrude_polygon(ring, w)
    bm.apply_translation([0, 0, -w / 2])
    bm.apply_transform(trimesh.transformations.rotation_matrix(math.pi / 2, [1, 0, 0]))
    bm.visual.face_colors = DARK
    pulley = lambda D, col: cat(cyl_y(D / 2 - 0.002, w * 1.1, col), cyl_y(D / 2 + 0.004, 0.003, col, (0, w * 0.6, 0)),  # noqa: E731
                                cyl_y(D / 2 + 0.004, 0.003, col, (0, -w * 0.6, 0)), box([D * 0.7, w * 1.3, 0.006], DARK))
    sc = Scene()
    sc.add("ground", "机架", "Ground", cat(cyl_y(0.005, w * 3, GREY), cyl_y(0.006, w * 3, GREY, (a, 0, 0)),
                                          box([a + D2, 0.01, 0.008], GREY, (a / 2, w * 1.4, -D2 / 2 - 0.02))), ground=True)
    sc.add("pulley1", "主动带轮（小）", "Driving pulley", pulley(D1, BLUE))
    sc.add("pulley2", "从动带轮（大）", "Driven pulley", pulley(D2, GREY))
    sc.add("belt", "传动带", "Belt", bm)

    def poses(deg):
        a1 = math.radians(deg)
        return {"pulley1": (P(0, 0), rot(a1)), "pulley2": (P(a, 0), rot(a1 * D1 / D2)), "belt": (P(0, 0), I3)}
    return sc.finish(poses, list(range(0, 721, 5)), "deg", "pulley1",
                     extra={"analysis": {"ratio": round(g["ratio"], 6), "belt_length_m": round(g["length_m"], 6),
                                         "wrap_small_deg": round(g["wrap_small_deg"], 3),
                                         "formula": {"zh": "i ≈ D2/D1（不计弹性滑动）；L = 2a·cosβ + π(D1+D2)/2 + β(D2−D1)，sinβ = (D2−D1)/(2a)；小轮包角 α1 = 180° − 2β",
                                                     "en": "i = D2/D1; L = 2a cos(b) + pi (D1 + D2)/2 + b (D2 - D1), sin(b) = (D2 - D1)/(2a)"}},
                            "note": {"zh": "带画成静止的环（形状不变），带轮按传动比转动", "en": "Belt drawn as a static loop"}})


# ---------------------------------------------------------------- 棘轮
def ratchet_state(p, deg):
    """输入曲柄转角（可多圈）→ (摇杆摆角 ψ, 棘轮转角)：摇杆按 (1 − cosθ)/2 往复摆动 swing；
    推程中先走过空程 swing − 齿距，再推棘轮转过一个齿距；回程止回棘爪顶住，棘轮不动"""
    z, sw = int(p["teeth"]), math.radians(p["swing_deg"])
    pitch = 2 * math.pi / z
    th = math.radians(deg)
    n, f = divmod(th, 2 * math.pi)
    psi = sw * (1 - math.cos(f)) / 2
    idle = sw - pitch
    if f <= math.pi:
        adv = max(0.0, psi - idle)
    else:
        adv = pitch
    return psi, n * pitch + adv


def ratchet(p):
    z, R, t = int(p["teeth"]), p["wheel_radius_m"], p["thickness_m"]
    h = 0.18 * R
    pts = []
    for k in range(z):                                    # 锯齿形齿廓：径向齿面 + 斜齿背
        a0 = 2 * math.pi * k / z
        pts += [(R * math.cos(a0), R * math.sin(a0)), ((R - h) * math.cos(a0 + 0.02), (R - h) * math.sin(a0 + 0.02))]
    wheel = cat(polygon_prism(pts, t, BLUE), cyl_y(0.006, t * 2, DARK))
    Lr = R * 1.6
    rocker = cat(box([Lr, t * 0.8, 0.012], GREY, (Lr / 2, -t, 0)), cyl_y(0.009, t * 0.9, DARK, (0, -t, 0)),
                 box([0.006, t * 0.8, 0.035], YEL, (R + 0.006, -t * 0.2, h * 0.3)))
    sc = Scene()
    sc.add("ground", "机架（含止回棘爪）", "Ground (with holding pawl)",
           cat(cyl_y(0.006, t * 4, GREY), box([0.012, t * 4, R + 0.02], GREY, (0, 0, -(R + 0.02) / 2)),
               box([0.006, t, 0.03], RED, (-R - 0.004, 0, 0.01))), ground=True)
    sc.add("wheel", "棘轮", "Ratchet wheel", wheel)
    sc.add("rocker", "摇杆（带驱动棘爪）", "Rocker with driving pawl", rocker)

    def poses(deg):
        psi, w = ratchet_state(p, deg)
        return {"wheel": (P(0, 0), rot(w)), "rocker": (P(0, 0), rot(psi))}
    return sc.finish(poses, list(range(0, 360 * 4, 5)), "deg", "rocker", inp_type="rotation",
                     path={"zh": "驱动曲柄转 4 圈：摇杆往复摆动 {}°，棘轮每圈前进一个齿（{:.1f}°）".format(p["swing_deg"], 360 / z),
                           "en": "Driving crank turns 4 times; the wheel advances one tooth per turn"},
                     extra={"analysis": {"advance_per_cycle_deg": round(360 / z, 6), "idle_deg": round(p["swing_deg"] - 360 / z, 6)}})


# ---------------------------------------------------------------- 外槽轮机构
def geneva_wheel_angle(p, deg):
    """主动拨盘转角（度，可多圈）→ 槽轮转角（弧度，累计；槽轮在拨盘 −X 侧、中心距 C）。
    拨销在槽内时（α = θ − 180°，|α| ≤ 90° − 180°/n）：β = atan2(R·sinα, C − R·cosα)，槽轮转角 = −β − 圈数·360°/n"""
    n, R = int(p["slots"]), p["crank_m"]
    C = R / math.sin(math.pi / n)
    lim = math.pi / 2 - math.pi / n
    turns = math.floor(deg / 360)
    alpha = math.radians(deg - 360 * turns) - math.pi
    if alpha < -lim:
        beta = -math.pi / n
    elif alpha > lim:
        beta = math.pi / n
    else:
        beta = math.atan2(R * math.sin(alpha), C - R * math.cos(alpha))
    return -turns * 2 * math.pi / n - beta


def geneva(p):
    n, R, t = int(p["slots"]), p["crank_m"], p["thickness_m"]
    C = R / math.sin(math.pi / n)
    Rw = math.sqrt(C * C - R * R) * 1.08                  # 槽轮外半径（略大于中心到槽口）
    pin_r = 0.12 * R
    from shapely.geometry import Point, box as sbox
    from shapely import affinity
    disc = Point(0, 0).buffer(Rw, 128)
    slot_len = R + Rw - C + pin_r * 1.5
    for k in range(n):
        a = 2 * math.pi * k / n
        sl = sbox(Rw - slot_len, -pin_r * 1.1, Rw + 0.01, pin_r * 1.1)
        disc = disc.difference(affinity.rotate(sl, a, origin=(0, 0), use_radians=True))
        notch = Point((C) * math.cos(a + math.pi / n), (C) * math.sin(a + math.pi / n)).buffer(R * 0.62, 64)
        disc = disc.difference(notch)
    import trimesh
    wm = trimesh.creation.extrude_polygon(disc, t)
    wm.apply_translation([0, 0, -t / 2])
    wm.apply_transform(trimesh.transformations.rotation_matrix(math.pi / 2, [1, 0, 0]))
    wm.visual.face_colors = BLUE
    crank = cat(box([R, t, 0.01], GREY, (R / 2, -t * 1.1, 0)), cyl_y(pin_r, t * 2, YEL, (R, -t * 0.4, 0)),
                cyl_y(R * 0.55, t, GREY, (0, -t * 0.2, 0)), cyl_y(0.006, t * 3, DARK))
    sc = Scene()
    sc.add("ground", "机架", "Ground", cat(cyl_y(0.006, t * 4, GREY), cyl_y(0.006, t * 4, GREY, (-C, 0, 0)),
                                          box([C + 2 * R, t * 4, 0.008], GREY, (-C / 2, 0, -Rw - 0.012))), ground=True)
    sc.add("crank", "拨盘（带拨销与锁止弧）", "Driver with pin", crank)
    sc.add("wheel", "槽轮（{} 槽）".format(n), "Geneva wheel ({} slots)".format(n), wm)

    def poses(deg):
        return {"crank": (P(0, 0), rot(math.radians(deg))), "wheel": (P(-C, 0), rot(geneva_wheel_angle(p, deg)))}
    return sc.finish(poses, list(range(0, 720, 3)), "deg", "crank",
                     extra={"analysis": {"slots": n, "center_distance_m": round(C, 6), "advance_per_turn_deg": 360 / n,
                                         "motion_fraction": round((n - 2) / (2 * n), 6),
                                         "formula": {"zh": "中心距 C = R / sin(π/n)；拨盘转一圈槽轮转 360°/n；运动时间占比 τ = (n − 2)/(2n)",
                                                     "en": "C = R / sin(pi/n); advance 360/n per turn; tau = (n - 2)/(2n)"}}})


# ---------------------------------------------------------------- 丝杠螺母
def lead_screw(p):
    d, Ph, Ls, t = p["diameter_mm"] / 1000, p["lead_mm"] / 1000, p["screw_length_m"], p["nut_length_m"]
    import trimesh
    parts = [cyl_x(d / 2 * 0.82, Ls, GREY)]
    nseg = int(Ls / Ph * 24)
    for k in range(nseg):                                 # 螺纹示意：沿螺旋线排列的小方块
        s = -Ls / 2 + Ls * k / nseg
        ang = 2 * math.pi * s / Ph
        parts.append(_mesh(trimesh.creation.box(extents=[Ph * 0.45, d * 0.12, d * 0.12]).apply_translation(
            [s, d * 0.44 * math.cos(ang), d * 0.44 * math.sin(ang)]), GREY))
    screw = cat(*parts, cyl_x(d * 0.3, 0.04, DARK, (Ls / 2 + 0.02, 0, 0)))
    nut = cat(cyl_x(d * 0.95, t, BLUE), box([t * 0.6, d * 1.2, d * 2.6], BLUE, (0, 0, d * 0.9)))
    travel = (Ls - t) * 0.8
    sc = Scene()
    sc.add("ground", "机架（轴承座与导轨）", "Ground (supports and guide)",
           cat(box([0.02, d * 3, d * 2.4], GREY, (-Ls / 2 - 0.01, 0, -d * 0.4)), box([0.02, d * 3, d * 2.4], GREY, (Ls / 2 + 0.01, 0, -d * 0.4)),
               box([Ls, d * 0.6, d * 0.3], DARK, (0, 0, d * 2.4))), ground=True)
    sc.add("screw", "丝杠", "Lead screw", screw)
    sc.add("nut", "螺母（滑台）", "Nut (carriage)", nut)
    revs = travel / Ph

    def poses(deg):
        return {"screw": (P(0, 0), _Rx(math.radians(deg))), "nut": (P(-travel / 2 + Ph * deg / 360, 0), I3)}
    top = int(revs * 360)
    return sc.finish(poses, list(range(0, top + 1, 30)), "deg", "screw",
                     extra={"analysis": {"lead_m": Ph, "travel_m": round(Ph * (top // 30 * 30) / 360, 6),
                                         "lead_angle_deg": round(math.degrees(math.atan(Ph / (math.pi * (d - Ph / 2)))), 4),
                                         "formula": {"zh": "螺母位移 s = Ph·φ/360°（单线）；导程角 tanλ = Ph/(π·d2)，λ 小于当量摩擦角时自锁",
                                                     "en": "s = Ph * phi / 360; tan(lambda) = Ph / (pi d2)"}}})


BUILDERS = {"four_bar": four_bar, "slider_crank": slider_crank, "cam": cam, "gear_train": gear_train, "worm": worm,
            "belt": belt, "ratchet": ratchet, "geneva": geneva, "lead_screw": lead_screw}


def params_of(entry, row=None):
    p = dict(entry.get("defaults") or {})
    for k, v in (row or {}).items():
        if k in p and v not in (None, ""):
            p[k] = float(v)
    return p


def build(entry, row):
    kind = entry["model"]["engine"].split(":")[1]
    p = params_of(entry, row)
    if kind == "gear_train" and entry.get("mechanism_names"):
        return [("__scene__", gear_train(p, entry["mechanism_names"]))]
    return [("__scene__", BUILDERS[kind](p))]
