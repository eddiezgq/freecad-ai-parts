"""按系统的连接关系布局（ADR-0032）：把系统中的实例放进场景，并按机械连接逐个配合。

- 电气与信号连接没有坐标系，不参与布局
- 先做面配合，再做圆柱配合（同类按端口对排序）：两实例之间同时有两种配合时，轴向位置由面配合决定，
  圆柱配合只核对同轴；只经圆柱配合相连的实例（如轴套）按 ADR-0032 的插入深度约定放置
- 每个刚性组按系统中最先列出的成员定位在世界原点；没有机械连接的实例（如驱动器）留在原点，
  在结果中列为“未配合”，由调用方另行摆放
"""

from __future__ import annotations

from collections.abc import Callable

from freecad_addon.core.geometry import MECHANICAL, LayoutError
from freecad_addon.core.pose import Pose
from freecad_addon.core.scene import Scene, split_ref


def _port_type(comp: dict, pid: str) -> str | None:
    return next((p.get("type") for p in comp.get("ports", []) if p.get("id") == pid), None)


def layout_system(system: dict, resolve: Callable[[str], dict | None]) -> tuple[Scene, dict]:
    scene = Scene()
    order = []
    for item in system.get("components", []):
        comp = resolve(item["component"])
        if comp is None:
            raise LayoutError(f"组件库中没有 {item['component']}（实例 {item['instance']}）")
        scene.place(item["instance"], comp, Pose())
        order.append(item["instance"])

    mech, skipped = [], []
    for c in system.get("connections", []):
        types = []
        for ref in (c["a"], c["b"]):
            inst, pid = split_ref(ref)
            types.append(_port_type(scene.component(inst), pid))
        (mech if all(t in MECHANICAL for t in types) else skipped).append(c)
    def canonical(c: dict) -> tuple:
        inst, pid = split_ref(c["a"])
        face = _port_type(scene.component(inst), pid) in ("mechanical.flange", "mechanical.mount_face")
        return (0 if face else 1, tuple(sorted((c["a"], c["b"]))))

    # 按规范顺序处理：先面配合，再圆柱配合；同类按端口对排序，结果与书写顺序、方向无关
    ordered = sorted(mech, key=canonical)
    steps = [scene.connect(c["a"], c["b"]) for c in ordered]

    # 每个刚性组按最先列出的成员回到原点，结果与连接的书写方向无关
    done: set[str] = set()
    groups = []
    for name in order:
        if name in done:
            continue
        g = scene.group(name)
        done |= g
        scene.place(name, pose=Pose())
        groups.append([n for n in order if n in g])
    report = {
        "steps": steps,
        "groups": groups,
        "unmated": [g[0] for g in groups if len(g) == 1],
        "non_mechanical_connections": [f"{c['a']} ↔ {c['b']}" for c in skipped],
    }
    return scene, report
