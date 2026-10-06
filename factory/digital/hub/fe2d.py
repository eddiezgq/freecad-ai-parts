"""平面应力有限元（常应变三角形单元），用来核算夹具元件的刚度（第 13 轮，配教材第 52 章 52.9 节与实验 52.9）。

只做教学够用的事情：矩形网格、按形状挖去单元、底边固定、节点力，求位移和单元应力。
实验 52.9 的浏览器程序用同样的单元和网格（JavaScript 重写），两者结果由书里的程序互相核对。
单位：mm、N、MPa。
"""
from __future__ import annotations

import math

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.linalg import spsolve


class Mesh:
    def __init__(self, W: float, H: float, h: float, keep=None):
        """W × H 的矩形，网格边长 h；keep(x, y) 判断单元形心是否保留（返回 False 的单元挖去）。"""
        self.nx, self.ny = int(round(W / h)), int(round(H / h))
        self.h = h
        xs = np.linspace(-W / 2, W / 2, self.nx + 1)
        ys = np.linspace(0, H, self.ny + 1)
        self.xy = np.array([(x, y) for y in ys for x in xs])
        nid = lambda i, j: j * (self.nx + 1) + i  # noqa: E731
        tris = []
        for j in range(self.ny):
            for i in range(self.nx):
                a, b, c, d = nid(i, j), nid(i + 1, j), nid(i + 1, j + 1), nid(i, j + 1)
                for t in ((a, b, c), (a, c, d)):
                    cx, cy = self.xy[list(t)].mean(axis=0)
                    if keep is None or keep(cx, cy):
                        tris.append(t)
        self.tri = np.array(tris)
        used = np.unique(self.tri)
        self.used = np.zeros(len(self.xy), bool)
        self.used[used] = True


class MappedMesh(Mesh):
    """顶边是曲线（折线）的网格：第 i 列节点的 x 均匀分布，y 从 0 均匀分到 ytop(x)。边界与形状贴合，不出现台阶。"""

    def __init__(self, W: float, ytop, nx: int, ny: int):
        self.nx, self.ny, self.h = nx, ny, W / nx
        xs = np.linspace(-W / 2, W / 2, nx + 1)
        self.xy = np.array([(x, ytop(x) * j / ny) for j in range(ny + 1) for x in xs])
        nid = lambda i, j: j * (nx + 1) + i  # noqa: E731
        tris = []
        for j in range(ny):
            for i in range(nx):
                a, b, c, d = nid(i, j), nid(i + 1, j), nid(i + 1, j + 1), nid(i, j + 1)
                # 对角线方向交替，网格不偏向一侧
                tris += [(a, b, c), (a, c, d)] if (i + j) % 2 == 0 else [(a, b, d), (b, c, d)]
        self.tri = np.array(tris)
        self.used = np.ones(len(self.xy), bool)


def solve(mesh: Mesh, E: float, nu: float, t: float, fixed, loads) -> dict:
    """fixed：被固定的节点号列表（两个方向都固定）；loads：{节点号: (Fx, Fy)}。t：单元厚度（垂直于纸面）。"""
    D = E / (1 - nu * nu) * np.array([[1, nu, 0], [nu, 1, 0], [0, 0, (1 - nu) / 2]])
    rows, cols, vals, Bs, As = [], [], [], [], []
    for tri in mesh.tri:
        (x1, y1), (x2, y2), (x3, y3) = mesh.xy[tri]
        A = 0.5 * ((x2 - x1) * (y3 - y1) - (x3 - x1) * (y2 - y1))
        b = np.array([y2 - y3, y3 - y1, y1 - y2])
        c = np.array([x3 - x2, x1 - x3, x2 - x1])
        B = np.zeros((3, 6))
        B[0, 0::2] = b
        B[1, 1::2] = c
        B[2, 0::2] = c
        B[2, 1::2] = b
        B /= 2 * A
        k = t * A * B.T @ D @ B
        dof = np.array([[2 * n, 2 * n + 1] for n in tri]).ravel()
        for i in range(6):
            for j in range(6):
                rows.append(dof[i]); cols.append(dof[j]); vals.append(k[i, j])
        Bs.append(B); As.append(A)
    N = 2 * len(mesh.xy)
    K = coo_matrix((vals, (rows, cols)), shape=(N, N)).tocsr()
    F = np.zeros(N)
    for n, (fx, fy) in loads.items():
        F[2 * n] += fx
        F[2 * n + 1] += fy
    fixed_dof = set()
    for n in fixed:
        fixed_dof |= {2 * n, 2 * n + 1}
    for n in np.where(~mesh.used)[0]:
        fixed_dof |= {2 * n, 2 * n + 1}
    free = np.array([d for d in range(N) if d not in fixed_dof])
    u = np.zeros(N)
    u[free] = spsolve(K[free][:, free].tocsc(), F[free])
    vm = []
    for tri, B in zip(mesh.tri, Bs):
        dof = np.array([[2 * n, 2 * n + 1] for n in tri]).ravel()
        sx, sy, txy = D @ B @ u[dof]
        vm.append(math.sqrt(sx * sx - sx * sy + sy * sy + 3 * txy * txy))
    return {"u": u.reshape(-1, 2), "vm": np.array(vm), "vm_max": float(max(vm))}


def vblock_section(B=80.0, Hb=50.0, y_apex=20.0, alpha=90.0, d=40.3, h=1.0):
    """V 形块的截面网格：宽 B、高 Hb，V 形槽顶点离底面 y_apex，夹角 α。返回网格和两个接触点的坐标。"""
    a = math.radians(alpha) / 2

    def ytop(x):
        return min(Hb, y_apex + abs(x) / math.tan(a))

    m = MappedMesh(B, ytop, int(round(B / h)), int(round(Hb / h)))
    r = d / 2
    yc = y_apex + r / math.sin(a)                       # 工件轴心高度
    contacts = [(-r * math.cos(a), yc - r * math.sin(a)), (r * math.cos(a), yc - r * math.sin(a))]
    return m, contacts, yc


def vblock_stiffness(W: float, E: float, nu=0.3, t=18.0, B=80.0, Hb=50.0, y_apex=20.0, alpha=90.0, d=40.3, h=1.0) -> dict:
    """一段 V 形块工作面（长 t）承受工件传来的竖直力 W 时，工件轴心下沉多少。
    W 按 V 形块两工作面的法向力 N = W/(2 sin(α/2)) 施加在接触点附近的节点上（分到最近的 3 个节点），底面固定。
    轴心下沉 = 接触点沿工作面法向的位移 / sin(α/2)（两边对称）。"""
    m, contacts, yc = vblock_section(B, Hb, y_apex, alpha, d, h)
    a = math.radians(alpha) / 2
    N = W / (2 * math.sin(a))
    loads, normals = {}, []
    for sx, (cx, cy) in zip((-1, 1), contacts):
        nrm = (-sx * math.cos(a), math.sin(a))           # 工作面的外法向（指向工件）
        normals.append(nrm)
        dist = np.hypot(m.xy[:, 0] - cx, m.xy[:, 1] - cy)
        dist[~m.used] = 1e9
        near = np.argsort(dist)[:3]
        for n in near:
            fx, fy = loads.get(int(n), (0.0, 0.0))
            loads[int(n)] = (fx - N / 3 * nrm[0], fy - N / 3 * nrm[1])
    fixed = [i for i, (x, y) in enumerate(m.xy) if abs(y) < 1e-9]
    r = solve(m, E, nu, t, fixed, loads)
    un = []
    for (cx, cy), nrm in zip(contacts, normals):
        dist = np.hypot(m.xy[:, 0] - cx, m.xy[:, 1] - cy)
        dist[~m.used] = 1e9
        near = np.argsort(dist)[:3]
        uu = r["u"][near].mean(axis=0)
        un.append(-(uu[0] * nrm[0] + uu[1] * nrm[1]))   # 沿法向退让为正
    drop = sum(un) / 2 / math.sin(a)
    return {"drop": drop, "vm_max": r["vm_max"], "n_nodes": int(m.used.sum()), "n_el": len(m.tri), "mesh": m, "res": r}
