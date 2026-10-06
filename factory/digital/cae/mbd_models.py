# -*- coding: utf-8 -*-
"""动力学模型的来源（第 12 轮 D3）与网页动画用的模型。

- 零件库机器人：MuJoCo Menagerie 按零件库同一个固定提交取到镜像里（/opt/menagerie），第一期收常用机械臂。
- 零件库机构：cae/mech_mjcf.py 按参数生成（第 2 步）。
- 上传：MJCF 或 URDF（单个文件，或带网格的 zip）。
"""
import io
import os
import zipfile

import numpy as np

MENAGERIE = os.environ.get("WQ_MENAGERIE", "/opt/menagerie")
MENAGERIE_COMMIT = "4d038b3feae26ec82b46a4d586379114012a8ac7"      # 与 library/vendor/menagerie.yaml 一致（测试核对）

# 零件库编号 → (Menagerie 文件, 中文名, 末端构件)
ROBOTS = {
    "B-ARM-UR5E": ("universal_robots_ur5e/ur5e.xml", "UR5e 机械臂（5 kg 负载）", "wrist_3_link"),
    "B-ARM-UR10E": ("universal_robots_ur10e/ur10e.xml", "UR10e 机械臂（12.5 kg 负载）", "wrist_3_link"),
    "B-ARM-FR3": ("franka_fr3/fr3.xml", "Franka FR3 机械臂（3 kg 负载）", "fr3_link7"),
}
MENAGERIE_DIRS = sorted({v[0].split("/")[0] for v in ROBOTS.values()})


def robot_path(rid):
    if rid not in ROBOTS:
        raise ValueError("零件库里没有可做动力学的机器人“{}”".format(rid))
    p = os.path.join(MENAGERIE, ROBOTS[rid][0])
    if not os.path.exists(p):
        raise ValueError("服务器上缺少模型文件 {}".format(ROBOTS[rid][0]))
    return p


def unpack_upload(data, name, dest):
    """上传的 MJCF / URDF：单个 .xml/.urdf，或 zip（里面一个主文件 + 网格）。返回主文件路径"""
    os.makedirs(dest, exist_ok=True)
    low = name.lower()
    if low.endswith(".zip") or data[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            total = sum(i.file_size for i in z.infolist())
            if total > 200 * 1024 * 1024:
                raise ValueError("zip 解开超过 200 MB")
            for i in z.infolist():
                target = os.path.normpath(os.path.join(dest, i.filename))
                if not target.startswith(os.path.normpath(dest) + os.sep):
                    raise ValueError("zip 里有不安全的路径")
                if i.is_dir():
                    continue
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with z.open(i) as src, open(target, "wb") as out:
                    out.write(src.read())
        mains = []
        for root, _, files in os.walk(dest):
            for f in files:
                if f.lower().endswith((".xml", ".urdf", ".mjcf")):
                    txt = open(os.path.join(root, f), "rb").read(4000).decode("utf-8", "ignore")
                    if "<mujoco" in txt or "<robot" in txt:
                        mains.append(os.path.join(root, f))
        if not mains:
            raise ValueError("zip 里没找到 MJCF（<mujoco>）或 URDF（<robot>）文件")
        mains.sort(key=lambda p: (("scene" in os.path.basename(p).lower()), p.count(os.sep), len(p)))
        return mains[0]
    if not low.endswith((".xml", ".urdf", ".mjcf")):
        raise ValueError("请上传 MJCF（.xml）、URDF（.urdf）或含网格的 zip")
    p = os.path.join(dest, os.path.basename(name))
    open(p, "wb").write(data)
    return p


# ---------------------------------------------------------------- 网页动画模型
def model_glb(model):
    """每个构件一个节点（名字 = 构件名），几何在构件坐标里（米）；网页按每一帧的位置、姿态摆放"""
    import mujoco
    import trimesh
    scene = trimesh.Scene()
    groups = set(int(g) for g in model.geom_group)
    vis = 2 if {2, 3} <= groups else None             # Menagerie 习惯：2 组可视、3 组碰撞；否则全部画
    for b in range(1, model.nbody):
        parts = []
        for g in range(model.ngeom):
            if model.geom_bodyid[g] != b or (vis is not None and model.geom_group[g] != vis):
                continue
            m = _geom_mesh(model, g, trimesh)
            if m is None:
                continue
            R = np.zeros(9)
            mujoco.mju_quat2Mat(R, model.geom_quat[g])
            T = np.eye(4)
            T[:3, :3] = R.reshape(3, 3)
            T[:3, 3] = model.geom_pos[g]
            m.apply_transform(T)
            rgba = model.mat_rgba[model.geom_matid[g]] if model.geom_matid[g] >= 0 else model.geom_rgba[g]
            m.visual.face_colors = (np.clip(rgba, 0, 1) * 255).astype(np.uint8)
            parts.append(m)
        name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_BODY, b) or "body{}".format(b)
        if parts:
            mesh = trimesh.util.concatenate(parts)
            scene.add_geometry(mesh, node_name=name, geom_name=name)
    return scene.export(file_type="glb")


def _geom_mesh(model, g, trimesh):
    t = int(model.geom_type[g])
    s = model.geom_size[g]
    if t == 7:                                                # 网格
        mid = model.geom_dataid[g]
        va, vn = model.mesh_vertadr[mid], model.mesh_vertnum[mid]
        fa, fn = model.mesh_faceadr[mid], model.mesh_facenum[mid]
        return trimesh.Trimesh(model.mesh_vert[va:va + vn].copy(), model.mesh_face[fa:fa + fn].copy(), process=False)
    if t == 6:                                                # 长方体（半尺寸）
        return trimesh.creation.box(extents=2 * s)
    if t == 2:
        return trimesh.creation.icosphere(subdivisions=2, radius=s[0])
    if t == 3:                                                # 胶囊：半径、半长（沿 z）
        return trimesh.creation.capsule(height=2 * s[1], radius=s[0], count=[16, 8])
    if t == 5:
        return trimesh.creation.cylinder(radius=s[0], height=2 * s[1], sections=24)
    if t == 4:
        m = trimesh.creation.icosphere(subdivisions=2, radius=1)
        m.apply_scale(s)
        return m
    return None                                               # 平面、高度场等不画
