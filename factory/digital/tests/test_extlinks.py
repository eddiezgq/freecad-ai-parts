"""第 158 轮：零件库“到外部库查”的链接（网页模块 web/src/lib/extlinks.js，经 node 跑同一份代码）。
期望值逐条手写：每类条目拼出的地址与 extlinks.json 的模板一致；没有型号、没有模板时的退路；机器人等不出链接。"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1] / "web"
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="需要 node")


def run(cases, si=()):
    req = {"cases": [{"entry": e, "size": s} for e, s in cases], "si": [list(x) for x in si]}
    r = subprocess.run(["node", "tools/extlinks_check.mjs"], input=json.dumps(req), capture_output=True, text=True, cwd=WEB, timeout=60, check=False)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def urls(links):
    return {x["site"]: x["url"] for x in links}


def test_si_format_by_hand():
    out = run([], [(1e-11, "F"), (1e-7, "F"), (2.2e-6, "F"), (4.7e-4, "F"), (10, "Ohm"), (0.002, "Ohm"), (4700, "Ohm"),
                   (2.2e-5, "H"), (8e6, "Hz"), (0, "F"), ("x", "F")])
    assert out["si"] == ["10pF", "100nF", "2.2uF", "470uF", "10Ohm", "2mOhm", "4.7kOhm", "22uH", "8MHz", None, None]


def test_electronic_part_number_goes_to_three_sites():
    e = {"id": "A-ELE-SOIC8", "category": "ELE", "name": {"en": "SOIC-8 ICs"}}
    links = run([(e, {"size": "IR2101S", "params": {"part": "IR2101S"}})])["links"][0]
    assert urls(links) == {"snapeda": "https://www.snapeda.com/search/?q=IR2101S",
                           "lcsc": "https://www.lcsc.com/search?q=IR2101S",
                           "digikey": "https://www.digikey.com/en/products/result?keywords=IR2101S"}


def test_passive_without_part_number_uses_template():
    c = {"id": "A-ELE-C0402", "category": "ELE"}
    r = {"id": "A-ELE-SHUNT", "category": "ELE"}
    xh = {"id": "A-ELE-XH", "category": "ELE"}
    out = run([(c, {"size": "100N", "params": {"c_f": 1e-7, "v_rated": 50}}),
               (r, {"size": "2M", "params": {"r_ohm": 0.002, "tol_pct": 1}}),
               (xh, {"size": "4P", "params": {"n_pin": 4, "pitch_mm": 2.5}})])["links"]
    assert urls(out[0]) == {"lcsc": "https://www.lcsc.com/search?q=0402%20100nF",
                            "digikey": "https://www.digikey.com/en/products/result?keywords=0402%20100nF"}
    assert urls(out[1])["digikey"] == "https://www.digikey.com/en/products/result?keywords=2512%202mOhm"
    assert urls(out[2])["lcsc"] == "https://www.lcsc.com/search?q=JST%20B4B-XH-A"
    assert "snapeda" not in urls(out[0])               # SnapMagic 对“封装 + 数值”查不出结果，不放


def test_no_template_or_missing_value_gives_nothing():
    out = run([({"id": "A-ELE-NEW", "category": "ELE"}, {"size": "X", "params": {}}),          # 没型号、没模板
               ({"id": "A-ELE-C0402", "category": "ELE"}, {"size": "?", "params": {}})])["links"]  # 有模板缺数值：不猜
    assert out == [[], []]


def test_mechanical_standard_part():
    e = {"id": "A-SCR-SHC", "category": "SCR", "name": {"en": "Socket head cap screw"}}
    b = {"id": "A-BRG-AC", "category": "BRG", "name": {"en": "Angular contact ball bearing (40°)"}}
    out = run([(e, {"size": "M5x16", "params": {}}), (b, {"size": "7200BECBP", "params": {}})])["links"]
    assert urls(out[0]) == {"misumi": "https://us.misumi-ec.com/vona2/result/?Keyword=Socket%20head%20cap%20screw%20M5x16",
                            "mcmaster": "https://www.mcmaster.com/products/Socket-head-cap-screw-M5x16/"}
    assert urls(out[1])["misumi"].endswith("Keyword=Angular%20contact%20ball%20bearing%207200BECBP")   # 括号里的说明去掉
    k = {"id": "A-KEY-FLAT", "category": "KEY", "name": {"en": "Parallel key, form A"}}
    assert urls(run([(k, {"size": "2x2x6", "params": {}})])["links"][0])["mcmaster"] == \
        "https://www.mcmaster.com/products/Parallel-key-2x2x6/"                                     # 逗号后的说明去掉


def test_vendor_site_and_robots():
    v = {"id": "D-FTS-ATI-FT", "category": "FTS", "source": {"origin": "vendor"},
         "vendor": {"id": "ATI", "name": {"en": "ATI Industrial Automation"}, "site": "https://www.ati-ia.com"}}
    rb = {"id": "B-ARM-ALOHA", "category": "ARM", "kind": "robot", "source": {"origin": "menagerie"}}
    out = run([(v, {"size": "Nano17", "params": {}}), (rb, {"size": "default", "params": {}}), (None, None)])["links"]
    assert out[0] == [{"site": "vendor", "name": "ATI Industrial Automation", "url": "https://www.ati-ia.com"}]
    assert out[1] == [] and out[2] == []
