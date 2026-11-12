"""第 158 轮：零件库“到外部库查”的链接（网页模块 web/src/lib/extlinks.js，经 node 跑同一份代码）。
期望值逐条手写：每类条目拼出的地址与 extlinks.js 里 CFG 的模板一致；没有型号、没有模板时的退路；机器人等不出链接；
物料清单行（bomLinks，细则第三节 B）；问渠贴片页的副本与这份逐字相同。"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1] / "web"
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="需要 node")


def run(cases, si=(), bom=()):
    req = {"cases": [{"entry": e, "size": s} for e, s in cases], "si": [list(x) for x in si], "bom": list(bom)}
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


def q_of(links):
    """链接里的查询词（DigiKey 的 keywords 或 LCSC 的 q），没有链接返回 None"""
    from urllib.parse import parse_qs, urlparse
    for x in links:
        qs = parse_qs(urlparse(x["url"]).query)
        for k in ("keywords", "q"):
            if k in qs:
                return qs[k][0]
    return None


def test_bom_rows_by_hand():
    rows = [  # 驱动板 B 版物料清单里的各类行（细则第三节 B 表）
        ("IC-GDRV", "IR2101S", "SOIC-8_3.9x4.9mm_P1.27mm", "IR2101S", 3),
        ("IC-CAN", "MCP2562-E/SN", "SOIC-8_3.9x4.9mm_P1.27mm", "MCP2562-E/SN", 3),
        ("MOS-80V", "BSC040N08NS5", "TDSON-8-1", "BSC040N08NS5", 3),
        ("IC-ENCIF", "WQ-ENCIF", "QFN-16-1EP_3x3mm_P0.5mm_EP1.7x1.7mm", None, 0),     # 自研芯片不查
        ("CAP-0402", "100n", "C_0402_1005Metric", "0402 100nF", 2),
        ("CAP-1206", "2.2u/100V", "C_1206_3216Metric", "1206 2.2uF 100V", 2),
        ("CAP-BULK", "470u/63V", "CP_Elec_16x17.5", None, 0),                         # 没有尺寸码不猜
        ("RES-0402", "10", "R_0402_1005Metric", "0402 10Ohm", 2),
        ("RES-0402", "6.8k", "R_0402_1005Metric", "0402 6.8kOhm", 2),
        ("RES-SHUNT", "2m 1%", "R_2512_6332Metric", "2512 2mOhm 1%", 2),
        ("IND-PWR", "22u", "L_Bourns_SRN6045TA", "SRN6045TA 22uH", 2),
        ("XTAL", "8MHz", "Crystal_SMD_3225-4Pin_3.2x2.5mm", "3225 8MHz crystal", 2),
        ("CONN-SIG", "CAN", "JST_XH_B4B-XH-A_1x04_P2.50mm_Vertical", "B4B-XH-A", 2),
        ("CONN-SIG", "BRAKE", "JST_PH_B2B-PH-K_1x02_P2.00mm_Vertical", "B2B-PH-K", 2),
        ("CONN-PWR", "48V IN", "TerminalBlock_Phoenix_MKDS-1,5-2_1x02_P5.00mm_Horizontal", None, 0),
        ("DIO-SMD", "60V 1A", "D_SMA", None, 0),
        ("IC-LDO", "", "SOT-223-3_TabPin2", None, 0),                                  # 缺数值
    ]
    out = run([], bom=[{"item": i, "value": v, "package": p} for i, v, p, _, _ in rows])["bom"]
    for (item, value, _, q, n), links in zip(rows, out):
        assert len(links) == n, (item, value, links)
        assert q_of(links) == q, (item, value, links)
    assert {x["site"] for x in out[0]} == {"snapeda", "lcsc", "digikey"}
    assert {x["site"] for x in out[4]} == {"lcsc", "digikey"}


def test_bom_file_of_drive_board_b():
    """真实的驱动板 B 版物料清单：每行要么出链接、要么属于第三节 B 表里“不出”的几类（不认得的行不能悄悄漏掉）"""
    import csv
    f = Path(__file__).resolve().parents[2] / "designs" / "drv-joint-b" / "out" / "bom.csv"
    if not f.exists():
        pytest.skip("没有驱动板 B 版物料清单")
    rows = list(csv.DictReader(f.open(encoding="utf-8")))
    out = run([], bom=[{"item": r["物料编号"], "value": r["数值"], "package": r["封装"]} for r in rows])["bom"]
    none = sorted((r["物料编号"], r["数值"]) for r, links in zip(rows, out) if not links)
    assert none == [("CAP-BULK", "470u/63V"), ("CONN-PWR", "48V IN"), ("CONN-PWR", "MOTOR UVW"), ("DIO-SMD", "100V 1A"),
                    ("DIO-SMD", "60V 1A"), ("DIO-SMD-100", "100V 1A"), ("IC-ENCIF", "WQ-ENCIF"), ("OSC-50M", "50MHz")]
    assert len(rows) - len(none) == 38


def test_eda_page_copy_is_identical():
    lib = WEB / "src" / "lib" / "extlinks.js"
    copy = Path(__file__).resolve().parents[3] / "services" / "eda" / "web" / "factory" / "extlinks.js"
    if not copy.exists():
        pytest.skip("本仓库没有问渠贴片页（services/eda）")
    assert copy.read_bytes() == lib.read_bytes()
