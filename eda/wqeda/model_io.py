# -*- coding: utf-8 -*-
"""板子模型存成文件（第 111 轮 P4）：起草台的服务器上没有 KiCad，用这份文件按新规格查模板板子。

    python3 -m wqeda.model_io <板子.kicad_pcb> <输出.json.gz>     # 要 KiCad 的 pcbnew 模块

文件是 gzip 压缩的 JSON（形状用 WKB 十六进制，坐标保留到 0.001 mm）；同一块板子每次写出的字节一样，
CI 核对它和板子文件一致。"""

from __future__ import annotations

import gzip
import json
import sys

import shapely

from .model import Board, BomRow, Component, Copper, Feature, Hole, Pad, Track

FORMAT = "wqeda.board-model/1"
GRID = 0.001


def _g(g):
    return shapely.to_wkb(shapely.set_precision(g, GRID), hex=True) if g is not None else None


def _ug(s):
    return shapely.from_wkb(s) if s else None


def to_dict(b):
    return {
        "format": FORMAT,
        "source": b.source,
        "outline": list(b.outline) if b.outline else None,
        "copper_layers": b.copper_layers,
        "has_nets": b.has_nets,
        "outline_geom": _g(b.outline_geom),
        "tracks": [[t.layer, t.width, t.x1, t.y1, t.x2, t.y2] for t in b.tracks],
        "holes": [[h.x, h.y, h.drill, h.plated, h.ring, h.kind, h.ref] for h in b.holes],
        "copper": [[q.layer, q.x0, q.y0, q.x1, q.y1] for q in b.copper],
        "pads": [[p.side, p.x, p.y] for p in b.pads],
        "components": [[q.ref, q.x, q.y, q.rot, q.side] for q in b.components],
        "bom": [[list(r.refs), r.qty, r.value, r.package, r.item] for r in b.bom],
        "notes": list(b.notes),
        "features": [[f.layer, f.kind, f.net, f.ref, f.pad, f.width, _g(f.geom)] for f in b.features],
        "courtyards": {r: [s, _g(g)] for r, (s, g) in sorted(b.courtyards.items())},
    }


def from_dict(d):
    if d.get("format") != FORMAT:
        raise ValueError("不是板子模型文件（format 应为 {}）".format(FORMAT))
    b = Board(d["source"], tuple(d["outline"]) if d["outline"] else None, d["copper_layers"])
    b.has_nets = d["has_nets"]
    b.outline_geom = _ug(d["outline_geom"])
    b.tracks = [Track(*t) for t in d["tracks"]]
    b.holes = [Hole(*h) for h in d["holes"]]
    b.copper = [Copper(*q) for q in d["copper"]]
    b.pads = [Pad(*p) for p in d["pads"]]
    b.components = [Component(*q) for q in d["components"]]
    b.bom = [BomRow(tuple(r[0]), *r[1:]) for r in d["bom"]]
    b.notes = list(d["notes"])
    b.features = [Feature(f[0], _ug(f[6]), f[1], f[2], f[3], f[4], f[5]) for f in d["features"]]
    b.courtyards = {r: (v[0], _ug(v[1])) for r, v in d["courtyards"].items()}
    return b


def dump(b, path):
    data = json.dumps(to_dict(b), ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    with open(path, "wb") as f:
        f.write(gzip.compress(data, compresslevel=9, mtime=0))


def load(path):
    with open(path, "rb") as f:
        return from_dict(json.loads(gzip.decompress(f.read())))


def main(argv=None):
    a = argv if argv is not None else sys.argv[1:]
    if len(a) != 2:
        print(__doc__)
        return 2
    from .readers import kicad

    dump(kicad.read(a[0]), a[1])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
