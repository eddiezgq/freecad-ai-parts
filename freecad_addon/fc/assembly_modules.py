"""导入 FreeCAD Assembly 工作台的 Python 模块（ADR-0097 D5c，补充十二）。

JointObject 在模块顶层 `from pivy import coin`（只给三维显示用）。没有界面时先导入真的 pivy，之后再起界面，Coin 的状态就乱了，
三维视图一画就崩（FreeCAD 1.0.2 实测：同一进程里先跑无界面测试、再跑界面测试时 SIGSEGV）。
所以没有界面时用一个空的 coin 替身导入 JointObject（我们只用它的数据对象 Joint、GroundedJoint，不用显示部分）；
界面起来以后再导入就是真的。
"""

from __future__ import annotations

import inspect
import sys
import types

import FreeCAD as App


def load():
    """返回 (JointObject, UtilsAssembly)"""
    if "JointObject" not in sys.modules and not App.GuiUp:
        saved = {k: sys.modules.get(k) for k in ("pivy", "pivy.coin", "SoSwitchMarker")}
        pivy = types.ModuleType("pivy")
        pivy.coin = types.ModuleType("pivy.coin")
        marker = types.ModuleType("SoSwitchMarker")
        marker.SoSwitchMarker = type("SoSwitchMarker", (), {})
        sys.modules.update({"pivy": pivy, "pivy.coin": pivy.coin, "SoSwitchMarker": marker})
        try:
            import JointObject
        finally:
            for k, v in saved.items():
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v
    import JointObject
    import UtilsAssembly

    return JointObject, UtilsAssembly


def moving_part(UtilsAssembly, assembly, ref):
    """运动副一端连的零件（装配体下面直接的那一个）。

    FreeCAD 1.0 是 getMovingPart(assembly, ref)，照用。1.1 改成 getMovingPart(ref)，只返回 ref[0]——
    1.1 界面建的关节引用以零件为根，ref[0] 就是零件；但以装配体为根的引用（1.0 存的文件、脚本建的关节）
    ref[0] 是装配体本身，要顺着子路径“零件.子对象.Face1”往下找第一个在装配体里的对象。问渠 CAD 用的是 1.1"""
    f = UtilsAssembly.getMovingPart
    try:
        n = len(inspect.signature(f).parameters)
    except (TypeError, ValueError):
        n = 2
    if n != 1:
        return f(assembly, ref)
    if not ref or len(ref) != 2 or ref[0] is None:
        return None
    root, subs = ref[0], ref[1]
    top = {o.Name for o in getattr(assembly, "Group", [])}
    if root.Name in top:
        return root
    sub = (subs[0] if isinstance(subs, (list, tuple)) and subs else subs) or ""
    obj = root
    for name in sub.split(".")[:-1]:
        nxt = obj.getSubObject(name + ".", retType=1) if hasattr(obj, "getSubObject") else None
        if nxt is None:
            nxt = obj.Document.getObject(name)
        if nxt is None:
            break
        if nxt.Name in top:
            return nxt
        obj = nxt
    return f(ref)
