"""导入规格书的页码写法（ADR-0099 41.1 验收步骤里填 60-90）。"""

import pytest


def test_page_ranges():
    from freecad_addon.core.spec_import import parse_pages

    assert parse_pages("") is None and parse_pages("3,4") == [3, 4]
    assert parse_pages("60-62，3") == [3, 60, 61, 62] and parse_pages("5–6") == [5, 6]
    for bad in ("x", "9-3", "0"):
        with pytest.raises(ValueError):
            parse_pages(bad)
