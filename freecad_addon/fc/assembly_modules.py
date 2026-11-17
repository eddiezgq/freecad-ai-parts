"""导入 FreeCAD Assembly 工作台的 Python 模块（ADR-0097 D5c，补充十二）。

JointObject 在模块顶层 `from pivy import coin`（只给三维显示用）。没有界面时先导入真的 pivy，之后再起界面，Coin 的状态就乱了，
三维视图一画就崩（FreeCAD 1.0.2 实测：同一进程里先跑无界面测试、再跑界面测试时 SIGSEGV）。
所以没有界面时用一个空的 coin 替身导入 JointObject（我们只用它的数据对象 Joint、GroundedJoint，不用显示部分）；
界面起来以后再导入就是真的。
"""

from __future__ import annotations

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
