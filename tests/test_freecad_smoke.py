"""FreeCAD 环境冒烟测试（ADR-0032）：锁定版本、无界面布尔运算可用。"""

import pytest

pytestmark = pytest.mark.freecad

LOCKED_VERSION = ("1", "0", "2")


def test_locked_version():
    import FreeCAD

    assert tuple(FreeCAD.Version()[:3]) == LOCKED_VERSION


def test_boolean_common_volume():
    import FreeCAD
    import Part

    cyl = Part.makeCylinder(10, 20)
    box = Part.makeBox(5, 5, 5, FreeCAD.Vector(8, 0, 0))
    common = cyl.common(box).Volume
    assert 0 < common < box.Volume
    # 容斥：并集体积 = 两者之和 - 交集
    assert cyl.fuse(box).Volume == pytest.approx(cyl.Volume + box.Volume - common, rel=1e-6)
