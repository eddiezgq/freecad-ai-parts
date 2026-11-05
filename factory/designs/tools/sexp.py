# -*- coding: utf-8 -*-
"""KiCad S 表达式：读、写、取库里的符号（把 extends 的派生符号展开成完整符号）。纯 Python，不依赖 KiCad。"""
from __future__ import annotations

import os
import re

SYMDIR = os.environ.get("KICAD7_SYMBOL_DIR", "/usr/share/kicad/symbols")
FPDIR = os.environ.get("KICAD7_FOOTPRINT_DIR", "/usr/share/kicad/footprints")


class Sym(str):
    """不带引号的原子（关键字、数字）"""


_TOK = re.compile(r'\s*(?:(\()|(\))|"((?:[^"\\]|\\.)*)"|([^\s()"]+))', re.S)


def parse(text):
    stack, cur = [], []
    pos = 0
    n = len(text)
    while pos < n:
        m = _TOK.match(text, pos)
        if not m:
            if text[pos:].strip() == "":
                break
            raise ValueError("解析失败于 {}".format(pos))
        pos = m.end()
        if m.group(1):
            stack.append(cur)
            cur = []
        elif m.group(2):
            done = cur
            cur = stack.pop()
            cur.append(done)
        elif m.group(3) is not None:
            cur.append(m.group(3).replace('\\"', '"').replace("\\\\", "\\"))
        elif m.group(4) is not None:
            cur.append(Sym(m.group(4)))
    return cur[0] if len(cur) == 1 else cur


def q(s):
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def dump(x, ind=0):
    """写回 S 表达式（每个子表达式换行缩进；原子同一行）"""
    if isinstance(x, list):
        if not x:
            return "()"
        flat = all(not isinstance(e, list) for e in x)
        if flat:
            return "(" + " ".join(dump(e) for e in x) + ")"
        out = "(" + dump(x[0])
        for e in x[1:]:
            if isinstance(e, list):
                out += "\n" + "  " * (ind + 1) + dump(e, ind + 1)
            else:
                out += " " + dump(e)
        return out + ")"
    if isinstance(x, Sym):
        return str(x)
    if isinstance(x, bool):
        return "yes" if x else "no"
    if isinstance(x, (int, float)):
        return fmt(x)
    return q(x)


def fmt(v):
    if isinstance(v, int):
        return str(v)
    s = "{:.4f}".format(v).rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def find(x, key):
    return [e for e in x if isinstance(e, list) and e and e[0] == key]


def first(x, key):
    r = find(x, key)
    return r[0] if r else None


def prop(x, name):
    for e in find(x, "property"):
        if e[1] == name:
            return e[2]
    return None


_LIBS = {}


def library(lib):
    if lib not in _LIBS:
        with open(os.path.join(SYMDIR, lib + ".kicad_sym"), encoding="utf-8") as f:
            doc = parse(f.read())
        _LIBS[lib] = {e[1]: e for e in find(doc, "symbol")}
    return _LIBS[lib]


def symbol(lib_id):
    """库符号（已展开 extends），名字改成 lib:name，子单元名字同步改，可直接放进原理图的 lib_symbols"""
    lib, name = lib_id.split(":", 1)
    syms = library(lib)
    s = syms[name]
    ext = first(s, "extends")
    if ext:
        base = syms[ext[1]]
        props = {e[1]: e for e in find(s, "property")}
        out = [Sym("symbol"), lib_id]
        for e in base[2:]:
            if isinstance(e, list) and e[0] == "property":
                out.append(props.pop(e[1], e))
            elif isinstance(e, list) and e[0] == "symbol":
                out.append([Sym("symbol"), e[1].replace(ext[1], name, 1)] + e[2:])
            else:
                out.append(e)
        out += list(props.values())
        return out
    out = [Sym("symbol"), lib_id]
    for e in s[2:]:
        if isinstance(e, list) and e[0] == "symbol":
            out.append([Sym("symbol"), e[1]] + e[2:])
        else:
            out.append(e)
    return out


def pins(sym):
    """[(编号, 名字, 类型, x, y, 角度, 长度, 单元)]；单元 0 表示各单元共用"""
    out = []
    for sub in find(sym, "symbol"):
        m = re.search(r"_(\d+)_(\d+)$", sub[1])
        unit = int(m.group(1)) if m else 0
        for p in find(sub, "pin"):
            at = first(p, "at")
            out.append((first(p, "number")[1], first(p, "name")[1], str(p[1]), float(at[1]), float(at[2]),
                        float(at[3]) if len(at) > 3 else 0.0, float(first(p, "length")[1]), unit))
    return out
