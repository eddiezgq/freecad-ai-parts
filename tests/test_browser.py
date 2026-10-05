"""库浏览器的筛选与详情（ADR-0048 第 3 条）：纯函数，用真实库与虚构测试组件测试。"""

from __future__ import annotations

from pathlib import Path

from freecad_addon.core.browser import detail, instance_name, rows, show
from kb.library import JsonLibrary

ROOT = Path(__file__).resolve().parent.parent
REAL = JsonLibrary(ROOT / "data" / "library").all()
FIX = JsonLibrary(ROOT / "tests" / "golden" / "fixtures").all()


def test_filter_by_category_text_and_range():
    reducers = rows(REAL, "reducer")
    assert reducers and all(r.category == "reducer" for r in reducers)
    assert [r.model for r in rows(REAL, "reducer", "csf-25")] == ["CSF-25-100-2UH"]
    assert {r.model for r in rows(REAL, "reducer", "csf 100")} >= {"CSF-25-100-2UH", "CSF-14-100-2UH"}
    big = rows(REAL, "reducer", ranges={"params/rated_torque_nm": (60, None)})
    assert big and all(float(dict(r.key)["额定扭矩"].split()[0]) >= 60 for r in big)
    bore14 = rows(REAL, "reducer", ranges={"ports/input_bore/diameter_mm": (14, 14)})
    assert {r.model for r in bore14} == {"CSF-25-100-2UH", "CSF-32-100-2UH"}
    # 缺该参数的组件在有范围条件时不显示
    assert rows(REAL, "drive", ranges={"params/ratio": (1, None)}) == []


def test_key_fields_and_detail_carry_sources_and_review():
    motor = next(c for c in REAL if c["id"].endswith("sgm7j-02a-6"))
    row = rows([motor])[0]
    assert dict(row.key)["额定扭矩"] == "0.637 N·m" and dict(row.key)["轴径"].startswith("14 mm")
    d = detail(motor)
    assert d["category"] == "电机" and d["docs"] == ["src-yaskawa-sgm7-rotary-manual"]
    shaft = next(p for p in d["ports"] if p["id"] == "shaft")
    feat = next(s for s in shaft["spec"] if s["name"] == "feature")
    assert feat["value"] == "keyed" and feat["review"] == "人工录入" and "第 53 页" in feat["source"]
    red = detail(next(c for c in REAL if c["id"].endswith("csf-25-100-2uh")))
    assert next(p for p in red["params"] if p["name"] == "efficiency_curve")["value"] == "曲线 24 点"
    assert next(p for p in red["ports"] if p["id"] == "motor_flange")["configurable"] is True


def test_show_value_shapes():
    assert show({"value": 3}, "rpm") == "3 rpm"
    assert show({"min": 200, "max": 240}, "V") == "200–240 V"
    assert show({"nominal": 14, "tol_upper": 0, "tol_lower": -0.011}, "mm") == "14 mm（0 / -0.011）"
    assert show({"value": ["ethercat", "canopen"]}) == "ethercat、canopen"
    assert show(None) == "—"


def test_instance_names_number_per_category():
    assert instance_name("servo_motor", []) == "motor"
    assert instance_name("servo_motor", ["motor", "reducer"]) == "motor2"
    assert instance_name("servo_motor", ["motor", "motor2"]) == "motor3"
    assert instance_name("adapter", ["motor"]) == "adapter"


def test_fixtures_list_without_errors():
    assert {r.category for r in rows(FIX)} >= {"servo_motor", "reducer", "drive"}
    for comp in FIX:
        assert detail(comp)["id"] == comp["id"]
