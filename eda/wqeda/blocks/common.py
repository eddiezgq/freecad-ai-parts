# -*- coding: utf-8 -*-
"""功能块共用的工具：E 系列选值、元件数值的写法与读法、器件字典、计算结果的格式。纯计算，不联网、不调 AI。"""

from __future__ import annotations

import math
import re

# IEC 60063 的 E 系列（每十倍程里的标称值）
# fmt: off
E6 = [1.0, 1.5, 2.2, 3.3, 4.7, 6.8]
E24 = [1.0, 1.1, 1.2, 1.3, 1.5, 1.6, 1.8, 2.0, 2.2, 2.4, 2.7, 3.0, 3.3, 3.6, 3.9, 4.3, 4.7, 5.1, 5.6, 6.2, 6.8, 7.5,
       8.2, 9.1]
E96 = [1.00, 1.02, 1.05, 1.07, 1.10, 1.13, 1.15, 1.18, 1.21, 1.24, 1.27, 1.30, 1.33, 1.37, 1.40, 1.43, 1.47, 1.50, 1.54,
       1.58, 1.62, 1.65, 1.69, 1.74, 1.78, 1.82, 1.87, 1.91, 1.96, 2.00, 2.05, 2.10, 2.15, 2.21, 2.26, 2.32, 2.37, 2.43,
       2.49, 2.55, 2.61, 2.67, 2.74, 2.80, 2.87, 2.94, 3.01, 3.09, 3.16, 3.24, 3.32, 3.40, 3.48, 3.57, 3.65, 3.74, 3.83,
       3.92, 4.02, 4.12, 4.22, 4.32, 4.42, 4.53, 4.64, 4.75, 4.87, 4.99, 5.11, 5.23, 5.36, 5.49, 5.62, 5.76, 5.90, 6.04,
       6.19, 6.34, 6.49, 6.65, 6.81, 6.98, 7.15, 7.32, 7.50, 7.68, 7.87, 8.06, 8.25, 8.45, 8.66, 8.87, 9.09, 9.31, 9.53,
       9.76]
# fmt: on
SERIES = {"E6": E6, "E24": E24, "E96": E96}
SI = {"p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "m": 1e-3, "": 1.0, "k": 1e3, "M": 1e6, "G": 1e9}


def nearest(x, series="E24"):
    """取 E 系列里最接近 x 的标称值（按比值算远近，即对数距离）"""
    if x <= 0:
        raise ValueError("要正数")
    dec = math.floor(math.log10(x))
    cands = [m * 10**d for d in (dec - 1, dec, dec + 1) for m in SERIES[series]]
    return min(cands, key=lambda c: abs(math.log(c / x)))


def fmt(x, unit=""):
    """数值写成元件标注：51000 → 51k、6800 → 6.8k、147000 → 147k、10 → 10、2.2e-6 → 2.2u、220e-12 → 220p"""
    if x == 0:
        return "0" + unit
    for pre, f in (("G", 1e9), ("M", 1e6), ("k", 1e3), ("", 1.0), ("m", 1e-3), ("u", 1e-6), ("n", 1e-9), ("p", 1e-12)):
        if abs(x) >= f * 0.9999999:
            v = round(x / f, 6)
            s = "{:.3g}".format(v) if v < 1000 else str(int(v))
            return s + pre + unit
    return "{:g}{}".format(x, unit)


def parse(s):
    """元件标注读成数：'51k' → 51000、'470u/63V' → 470e-6（斜线后面是耐压，用 rating() 读）、'2m 1%' → 0.002"""
    m = re.match(r"\s*([0-9.]+)\s*([pnuµmkMG]?)", str(s))
    if not m:
        raise ValueError("读不出数值：{}".format(s))
    return float(m.group(1)) * SI[m.group(2)]


def rating(s, unit="V"):
    """标注里的额定值：'470u/63V' → 63、'60V 1A' → 60（unit='V'）或 1（unit='A'）；没有返回 None"""
    m = re.search(r"([0-9.]+)\s*{}\b".format(unit), str(s))
    return float(m.group(1)) if m else None


def part(ref, lib, value, fp, block, pins, item=None, note=""):
    return {
        "ref": ref,
        "lib": lib,
        "value": value,
        "fp": fp,
        "block": block,
        "pins": dict(pins),
        "item": item,
        "note": note,
    }


def two(ref, lib, value, a, b, block, fp, item, note=""):
    return part(ref, lib, value, fp, block, {"1": a, "2": b}, item, note)


# ------------------------------------------------------------------------------------------------- 计算结果

PASS, FAIL, UNKNOWN, PENDING = "pass", "fail", "unknown", "pending"  # pending = 用到的器件数据待核对


def item(key, name, value, unit="", formula="", source="", note=""):
    """计算书的一行：算出来的量"""
    return {"key": key, "name": name, "value": value, "unit": unit, "formula": formula, "source": source, "note": note}


def judge(key, name, need, have, unit="", rule="", status=None, source="", note=""):
    """计算书的一行判定：need 要求、have 实有；have 为 None 判未知。status 给定时直接用（例如 pending）"""
    if status is None:
        status = UNKNOWN if have is None or need is None else (PASS if have >= need - 1e-12 else FAIL)
    return {
        "key": key,
        "name": name,
        "need": need,
        "have": have,
        "unit": unit,
        "rule": rule,
        "status": status,
        "source": source,
        "note": note,
    }
