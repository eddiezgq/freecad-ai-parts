# -*- coding: utf-8 -*-
"""OpenFOAM 的读写小工具（第 16 轮）：写字典、跑程序、读网格和场（ASCII）。

后处理全部用 numpy 自己算，不依赖 OpenFOAM 的 functionObject（Debian / Ubuntu 打包的 v1912 里 functionObject 一加载就报
“IOstream sha1”错误退出），这样不同版本、不同打包都能用。"""
import os
import re
import subprocess

import numpy as np

ENV = dict(os.environ, WM_PROJECT_DIR=os.environ.get("WM_PROJECT_DIR", "/usr/share/openfoam"),
           FOAM_ETC=os.environ.get("FOAM_ETC", "/usr/share/openfoam/etc"), LC_ALL="C", LANG="C",
           OMPI_ALLOW_RUN_AS_ROOT="1", OMPI_ALLOW_RUN_AS_ROOT_CONFIRM="1", OMPI_MCA_btl_vader_single_copy_mechanism="none")

HEAD = 'FoamFile {{ version 2.0; format ascii; class {cls}; {loc}object {obj}; }}\n'


def write(case, rel, body, cls="dictionary"):
    path = os.path.join(case, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    loc = 'location "{}"; '.format(os.path.dirname(rel)) if os.path.dirname(rel) else ""
    with open(path, "w") as f:
        f.write(HEAD.format(cls=cls, loc=loc, obj=os.path.basename(rel)) + body)


def run(case, *cmd, timeout=600, log=None):
    """跑一个 OpenFOAM 程序；失败时抛出带最后几行日志的错误"""
    logf = os.path.join(case, "log." + (log or cmd[0]))
    with open(logf, "w") as lf:
        try:
            p = subprocess.run(list(cmd), cwd=case, env=ENV, stdout=lf, stderr=subprocess.STDOUT, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise RuntimeError("{} 超过 {} 秒".format(cmd[0], timeout)) from None
    txt = open(logf, errors="replace").read()
    if p.returncode != 0 or "FOAM FATAL" in txt:
        tail = txt[txt.find("FOAM FATAL"):][:600] if "FOAM FATAL" in txt else txt[-600:]
        raise RuntimeError("{} 出错：{}".format(cmd[0], tail.strip()))
    return txt


def latest_time(case):
    ts = []
    for d in os.listdir(case):
        try:
            ts.append((float(d), d))
        except ValueError:
            pass
    return max(ts)[1] if ts else "0"


# ---------------------------------------------------------------- 读
def _strip(txt):
    txt = re.sub(r"/\*.*?\*/", "", txt, flags=re.S)
    return re.sub(r"//[^\n]*", "", txt)


def _list_body(txt, start):
    """txt[start] 处是“数目 (”或“(”：返回 (内容, 结束位置)"""
    i = txt.index("(", start)
    depth, j = 0, i
    while True:
        c = txt[j]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return txt[i + 1:j], j + 1
        j += 1


def _numbers(s):
    return np.array(s.replace("(", " ").replace(")", " ").split(), float)


def read_points(case):
    txt = _strip(open(os.path.join(case, "constant/polyMesh/points")).read())
    body, _ = _list_body(txt, txt.index("}") + 1)
    return _numbers(body).reshape(-1, 3)


def read_faces(case):
    txt = _strip(open(os.path.join(case, "constant/polyMesh/faces")).read())
    body, _ = _list_body(txt, txt.index("}") + 1)
    return [list(map(int, m.split())) for m in re.findall(r"\d+\s*\(([^)]*)\)", body)]


def read_labels(case, name):
    txt = _strip(open(os.path.join(case, "constant/polyMesh", name)).read())
    body, _ = _list_body(txt, txt.index("}") + 1)
    return np.array(body.split(), int)


def read_boundary(case):
    txt = _strip(open(os.path.join(case, "constant/polyMesh/boundary")).read())
    body, _ = _list_body(txt, txt.index("}") + 1)
    out = {}
    for name, inner in re.findall(r"(\S+)\s*\{([^}]*)\}", body):
        d = dict(re.findall(r"(\w+)\s+([^;]+);", inner))
        out[name] = {"type": d.get("type"), "nFaces": int(d["nFaces"]), "startFace": int(d["startFace"])}
    return out


class Mesh:
    """多面体网格的几何量：面心、面积矢量、单元中心、单元体积"""

    def __init__(self, case):
        self.points = read_points(case)
        self.faces = read_faces(case)
        self.owner = read_labels(case, "owner")
        self.neighbour = read_labels(case, "neighbour")
        self.boundary = read_boundary(case)
        self.n_cells = int(self.owner.max()) + 1 if len(self.neighbour) == 0 else int(max(self.owner.max(), self.neighbour.max())) + 1
        nf = len(self.faces)
        self.Cf = np.zeros((nf, 3))
        self.Sf = np.zeros((nf, 3))
        for i, f in enumerate(self.faces):
            p = self.points[f]
            c0 = p.mean(0)
            a, b = p, np.roll(p, -1, 0)
            tri = np.cross(a - c0, b - c0) / 2                      # 以平均点为顶点的三角形扇
            ta = np.linalg.norm(tri, axis=1)
            tc = (a + b + c0) / 3
            self.Sf[i] = tri.sum(0)
            self.Cf[i] = (tc * ta[:, None]).sum(0) / ta.sum() if ta.sum() > 0 else c0
        self.magSf = np.linalg.norm(self.Sf, axis=1)
        # 单元体积与中心：散度定理 V = Σ Cf·Sf / 3（owner 为正、neighbour 为负）
        own, nei = self.owner, self.neighbour
        ni = len(nei)
        v = (self.Cf * self.Sf).sum(1) / 3
        self.V = np.bincount(own, v, self.n_cells) - np.bincount(nei, v[:ni], self.n_cells)
        w = self.magSf
        self.C = np.stack([np.bincount(own, self.Cf[:, k] * w, self.n_cells) + np.bincount(nei, self.Cf[:ni, k] * w[:ni], self.n_cells)
                           for k in range(3)], 1)
        ws = np.bincount(own, w, self.n_cells) + np.bincount(nei, w[:ni], self.n_cells)
        self.C /= ws[:, None]

    def patch(self, name):
        b = self.boundary[name]
        return slice(b["startFace"], b["startFace"] + b["nFaces"])


def read_field(case, time, name, mesh=None):
    """返回 (内部场 ndarray, {边界名: 值 ndarray 或 None})；标量 (n,)，矢量 (n,3)"""
    txt = _strip(open(os.path.join(case, str(time), name)).read())
    vec = "volVectorField" in txt[:300]

    def parse(s, n):
        s = s.strip()
        if s.startswith("uniform"):
            v = _numbers(s[len("uniform"):])
            return np.tile(v, (n, 1)) if vec else np.full(n, v[0])
        body, _ = _list_body(s, 0)
        v = _numbers(body)
        return v.reshape(-1, 3) if vec else v
    m = re.search(r"internalField\s+(uniform\s+[^;]+|nonuniform\s+List<\w+>\s*\d*\s*\(.*?\)\s*)\s*;", txt, re.S)
    n_int = mesh.n_cells if mesh else None
    raw = m.group(1).replace("nonuniform", "").strip()
    raw = re.sub(r"^List<\w+>\s*\d*", "", raw).strip() if not raw.startswith("uniform") else raw
    internal = parse(raw, n_int or 1)
    bnd = {}
    bi = txt.index("boundaryField")
    body, _ = _list_body(txt.replace("{", "(").replace("}", ")"), bi)        # 只为找到范围
    seg = txt[bi:]
    for name_, inner in re.findall(r"(\S+)\s*\{(.*?)\n\s*\}", seg[seg.index("{") + 1:], re.S):
        vm = re.search(r"\bvalue\s+(uniform\s+[^;]+|nonuniform\s+List<\w+>\s*\d*\s*\(.*?\)\s*)\s*;", inner, re.S)
        if not vm:
            bnd[name_] = None
            continue
        s = vm.group(1)
        n = mesh.boundary[name_]["nFaces"] if mesh and name_ in mesh.boundary else 1
        if s.startswith("uniform"):
            bnd[name_] = parse(s, n)
        else:
            s = re.sub(r"^nonuniform\s+List<\w+>\s*\d*", "", s).strip()
            bnd[name_] = parse(s, n)
    return internal, bnd
