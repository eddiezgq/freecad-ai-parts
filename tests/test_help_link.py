"""“帮助与培训”打开哪个网页（issue #687）。"""

from freecad_addon.core import help_link


def test_local_copy_is_used_when_installed(tmp_path):
    (tmp_path / "help" / "wqcad" / "en").mkdir(parents=True)
    (tmp_path / "help" / "wqcad" / "index.html").write_text("zh", encoding="utf-8")
    (tmp_path / "help" / "wqcad" / "en" / "index.html").write_text("en", encoding="utf-8")
    kind, where = help_link.help_target("zh", "intl", tmp_path)
    assert kind == "file" and where.endswith("index.html") and "en" not in where.split("wqcad")[1]
    kind, where = help_link.help_target("en", "cn", tmp_path)
    assert kind == "file" and where.replace("\\", "/").endswith("wqcad/en/index.html")


def test_online_page_by_region_when_no_local_copy(tmp_path):
    assert help_link.help_target("zh", "cn", tmp_path) == ("url", "https://learn.wenquestech.online/static/help/wqcad/index.html")
    assert help_link.help_target("en", "intl", None) == ("url", "https://learn.wenquestrobotics.com/static/help/wqcad/en/index.html")
    assert help_link.help_target("en", "other", None)[1].startswith("https://learn.wenquestrobotics.com/")


def test_local_copy_missing_one_language_falls_back_online(tmp_path):
    (tmp_path / "help" / "wqcad").mkdir(parents=True)
    (tmp_path / "help" / "wqcad" / "index.html").write_text("zh", encoding="utf-8")
    assert help_link.help_target("en", "intl", tmp_path)[0] == "url"

