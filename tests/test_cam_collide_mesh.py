"""三角网格部件的碰撞（ADR-0106 Q2 第 2 步）：与长方体部件的结论逐一对照；STL 读入；整机仿真里网格部件真查、指纹跟着网格文件变。"""

from __future__ import annotations

import json
import struct

import numpy as np
import pytest

from analysis import cam
from analysis.cam import collide as CL
from analysis.cam import machines

BOX = [-500, -250, -60, 500, 250, 0]


def box_tris(v6):
    x0, y0, z0, x1, y1, z1 = v6
    v = np.array([[x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0],
                  [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]], float)
    f = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4),
         (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]
    return v[np.array(f)]


def write_stl(path, tris, binary=True):
    tris = np.asarray(tris, float)
    if binary:
        with open(path, "wb") as f:
            f.write(b"\0" * 80 + struct.pack("<I", len(tris)))
            f.writelines(struct.pack("<3f", 0, 0, 0) + struct.pack("<9f", *t.ravel()) + b"\0\0" for t in tris)
    else:
        lines = ["solid t"]
        for t in tris:
            lines += ["facet normal 0 0 0", "outer loop", *[f"vertex {x} {y} {z}" for x, y, z in t], "endloop", "endfacet"]
        path.write_text("\n".join([*lines, "endsolid t"]), encoding="utf-8")


@pytest.mark.parametrize("binary", [True, False])
def test_read_stl(tmp_path, binary):
    tris = box_tris([0, 0, 0, 2, 3, 4])
    f = tmp_path / "b.stl"
    write_stl(f, tris, binary)
    assert np.allclose(CL.read_stl(f), tris)


def _rot(rng):
    q, _ = np.linalg.qr(rng.normal(size=(3, 3)))
    return q * np.sign(np.linalg.det(q))


@pytest.mark.parametrize("margin", [0.0, 2.0])
def test_mesh_box_agrees_with_box_component(margin):
    """网格长方体与同样的解析长方体：对随机放的斜长方体、圆柱，碰没碰的结论一样（离边界太近、对不同实现都含糊的情况跳过）"""
    v6 = [0, 0, 0, 40, 30, 20]
    mesh = CL.Mesh(box_tris(v6))
    ref = CL.Box.from_minmax(v6)
    rng = np.random.default_rng(3)
    n_hit = n = 0
    for _ in range(400):
        c = rng.uniform([-30, -30, -30], [70, 60, 50])
        if rng.random() < 0.5:
            other = CL.Box(c, _rot(rng), rng.uniform(1, 12, 3))
        else:
            ax = _rot(rng)[:, 0] * rng.uniform(2, 20)
            other = CL.Cylinder(c - ax, c + ax, float(rng.uniform(1, 8)))
        a = CL.hit(ref, other, margin)
        if a != CL.hit(ref, other, margin + 0.05) or a != CL.hit(ref, other, max(0.0, margin - 0.05)):
            continue                                   # 正好贴着，不比
        assert CL.hit(mesh, other, margin) == a
        assert CL.hit(other, mesh, margin) == a
        n += 1
        n_hit += a
    assert n > 300 and 30 < n_hit < n - 30


def test_small_shape_inside_mesh_counts_as_hit():
    mesh = CL.Mesh(box_tris([0, 0, 0, 100, 100, 100]))
    assert CL.hit(mesh, CL.Cylinder(np.array([50.0, 50, 40]), np.array([50.0, 50, 60]), 3.0))
    assert not CL.hit(mesh, CL.Cylinder(np.array([150.0, 50, 40]), np.array([150.0, 50, 60]), 3.0))


def test_mesh_against_mesh_and_moved():
    a = CL.Mesh(box_tris([0, 0, 0, 10, 10, 10]))
    b = CL.Mesh(box_tris([0, 0, 0, 4, 4, 4]))
    T = np.eye(4)
    T[:3, 3] = [8, 8, 8]
    assert CL.hit(a, b.moved(T))
    T[:3, 3] = [12, 12, 12]
    assert not CL.hit(a, b.moved(T))
    assert not CL.hit(a, b.moved(T), margin=3.4)         # 两个角相距 2·√3 ≈ 3.46
    assert CL.hit(a, b.moved(T), margin=3.5)
    T[:3, 3] = [3, 3, 3]                                  # 整个在里面
    assert CL.hit(a, b.moved(T))


MILL = {"mode": "mill", "machine": "EX-VMC", "stock": {"box": [0, 0, 100, 60], "height": 40},
        "features": [{"type": "pocket", "rect": [20, 15, 80, 45], "corner_r": 6, "depth": 8, "tool_d": 10}]}
OK = {"work_offset_mm": [0, 0, 40], "tools": {"1": {"tool": "EM10", "length_mm": 120}}}


def _machine_with_mesh_table(folder, stl_ok=True):
    m = machines.model("EX-VMC")
    m = {k: v for k, v in m.items() if not k.startswith("_")}
    m["components"] = [{**c, "mesh": "table.stl"} if c["id"] == "table" else c for c in m["components"]]
    for c in m["components"]:
        if c["id"] == "table":
            c.pop("box_mm")
    (folder / "EX-VMC.json").write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
    if stl_ok:
        write_stl(folder / "table.stl", box_tris(BOX))


def _prog(monkeypatch, folder, offset):
    monkeypatch.setenv("FAP_MACHINES", str(folder))
    r = cam.run({**MILL, "machine_sim": {**OK, "work_offset_mm": [0, 0, offset]}})
    assert r["status"] == "ok", r["messages"]
    return r["data"]["programs"][0]


def test_machine_with_mesh_table(tmp_path, monkeypatch):
    """示例加工中心的工作台换成网格：工件零点只比台面高 5、型腔 8 深，照样查出刀切进工作台；高 40 时通过"""
    _machine_with_mesh_table(tmp_path)
    p = _prog(monkeypatch, tmp_path, 5)
    assert any("刀具刃部碰到机床的工作台" in c["text"] for c in p["checks"] if c["level"] == "error")
    p_ok = _prog(monkeypatch, tmp_path, 40)
    assert not [c for c in p_ok["checks"] if c["level"] == "error"]
    fp1 = p_ok["machine_sim"]["fingerprint"] if "machine_sim" in p_ok else p_ok.get("fingerprint")
    # 网格文件改了（台面高 1 mm），指纹跟着变
    write_stl(tmp_path / "table.stl", box_tris([*BOX[:5], 1]))
    p2 = _prog(monkeypatch, tmp_path, 40)
    fp2 = p2["machine_sim"]["fingerprint"] if "machine_sim" in p2 else p2.get("fingerprint")
    assert fp1 and fp2 and fp1 != fp2


def test_missing_mesh_file_is_unknown(tmp_path, monkeypatch):
    _machine_with_mesh_table(tmp_path, stl_ok=False)
    p = _prog(monkeypatch, tmp_path, 40)
    assert any("table.stl" in c["text"] and "读不到" in c["text"] for c in p["checks"] if c["level"] == "unknown")
