"""FreeCAD 中组件库的选择（ADR-0048 第 2 条）。"""

from __future__ import annotations

import json

from freecad_addon.core.library_choice import REPO_ROOT, choose, load


def test_order_env_then_database_then_repo_then_fixtures(tmp_path):
    assert choose({"FAP_LIBRARY": "/x"}, tmp_path).kind == "env_json"
    assert choose({"DATABASE_URL": "postgres://"}, tmp_path).kind == "database"
    # 仓库里没有 data/library：虚构测试组件，并注明
    fx = choose({}, tmp_path)
    assert fx.kind == "fixtures" and "虚构测试组件" in fx.note
    # 有组件：用真实库，说明里写数量
    (tmp_path / "data" / "library" / "reducer").mkdir(parents=True)
    (tmp_path / "data" / "library" / "reducer" / "a.json").write_text(json.dumps({"id": "a"}), encoding="utf-8")
    real = choose({}, tmp_path)
    assert real.kind == "repo" and "真实厂商组件 1 个" in real.note


def test_this_repository_uses_its_real_library_by_default():
    choice = choose({})
    assert choice.kind == "repo" and choice.path == REPO_ROOT / "data" / "library"
    lib = load(choice)
    assert lib.all("reducer") and not any(c["id"].startswith("test.") for c in lib.all())
