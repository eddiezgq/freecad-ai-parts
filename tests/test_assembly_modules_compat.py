"""FreeCAD 1.0 / 1.1 两种 getMovingPart 写法都认（问渠 CAD 用 FreeCAD 1.1.4，装配体多体动力学一点就报
“getMovingPart() takes 1 positional argument but 2 were given”）。不需要 FreeCAD：用替身对象。"""

import sys
import types

import pytest


@pytest.fixture
def am(monkeypatch):
    if "FreeCAD" not in sys.modules:
        monkeypatch.setitem(sys.modules, "FreeCAD", types.SimpleNamespace(GuiUp=False))
    monkeypatch.delitem(sys.modules, "freecad_addon.fc.assembly_modules", raising=False)
    import freecad_addon.fc.assembly_modules as m

    return m


class Obj:
    def __init__(self, name, doc=None, children=()):
        self.Name, self.Document, self.Group = name, doc, list(children)
        self._kids = {c.Name: c for c in children}

    def getSubObject(self, sub, retType=0):
        return self._kids.get(sub.rstrip("."))


def test_freecad_10_signature_is_used_as_is(am):
    calls = []
    utils = types.SimpleNamespace(getMovingPart=lambda assembly, ref: calls.append((assembly, ref)) or "part")
    assert am.moving_part(utils, "asm", ("x", ["y"])) == "part"
    assert calls == [("asm", ("x", ["y"]))]


def test_freecad_11_reference_rooted_at_the_part(am):
    part = Obj("Crank")
    asm = Obj("Assembly", children=[part])
    utils = types.SimpleNamespace(getMovingPart=lambda ref: ref[0])
    assert am.moving_part(utils, asm, [part, ["Face3"]]) is part


def test_freecad_11_reference_rooted_at_the_assembly(am):
    """1.0 存的文件、脚本建的关节：引用以装配体为根，要顺着子路径找装配体下面的那个零件"""
    body = Obj("Body")
    link = Obj("Link", children=[body])
    asm = Obj("Assembly", children=[link])
    utils = types.SimpleNamespace(getMovingPart=lambda ref: ref[0])
    assert am.moving_part(utils, asm, [asm, ["Link.Body.Face1", "Link.Body.Vertex2"]]) is link


def test_freecad_11_bad_reference(am):
    utils = types.SimpleNamespace(getMovingPart=lambda ref: None)
    assert am.moving_part(utils, Obj("Assembly"), None) is None
