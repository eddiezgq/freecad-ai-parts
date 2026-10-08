# -*- coding: utf-8 -*-
"""网页版帮助（ADR-0065）的一致性：正文里的自定义块都指得到东西——“带我去做”的引导存在、引导要高亮的页面元素
（data-help）真在那一页上、动画已登记、视频在清单里、首页全流程七站都有对应章节。页面改了把标记弄丢，这里会报出来。"""
import json
import os
import re

import pytest

WEB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "src")
HELP = os.path.join(WEB, "help")
FENCE = re.compile(r"^```(\w+)[ \t]*\n(.*?)^```[ \t]*$", re.M | re.S)
BLOCKS = {"goto", "anim", "video", "live", "ask"}
LIVE = {"plant", "machines", "kpi"}


def _read(*p):
    with open(os.path.join(*p), encoding="utf-8") as f:
        return f.read()


def _chapters():
    out = []
    for ed in ("teach", "enterprise"):
        d = os.path.join(HELP, ed)
        for fn in sorted(os.listdir(d)):
            if fn.endswith(".md"):
                out.append((ed, re.sub(r"^\d+-", "", fn[:-3]), fn, _read(d, fn)))
    return out


def _args(body):
    return {m.group(1): m.group(2).strip() for m in re.finditer(r"^\s*([a-z_]+)\s*:\s*(.*)$", body, re.M)}


TOURS = json.loads(_read(HELP, "tours.json"))
VIDEOS = json.loads(_read(HELP, "videos.json"))
ANIMS = set(re.findall(r"^\s+'?([\w-]+)'?: defineAsyncComponent", _read(WEB, "components", "help", "anim", "index.js"), re.M))
ROUTES = dict(re.findall(r"path: '([^']+)', component: \(\) => import\('\./pages/(\w+)\.vue'\)", _read(WEB, "main.js")))


def test_both_editions_have_chapters_with_titles():
    ch = _chapters()
    for ed in ("teach", "enterprise"):
        assert any(c[0] == ed for c in ch), ed
    for ed, slug, fn, src in ch:
        assert re.match(r"^\d{2}-[a-z0-9-]+\.md$", fn), fn
        assert src.startswith("# "), fn
    slugs = [(c[0], c[1]) for c in ch]
    assert len(slugs) == len(set(slugs))


@pytest.mark.parametrize("ed,slug,fn,src", _chapters(), ids=lambda v: v if isinstance(v, str) and v.endswith(".md") else None)
def test_blocks_point_at_real_things(ed, slug, fn, src):
    for kind, body in FENCE.findall(src):
        if kind not in BLOCKS:
            continue
        a = _args(body)
        if kind == "goto":
            assert a.get("tour") in TOURS, (fn, a)
        elif kind == "anim":
            assert a.get("name") in ANIMS, (fn, a)
        elif kind == "video":
            assert a.get("name") in VIDEOS, (fn, a)
            assert VIDEOS[a["name"]]["edition"] == ed, (fn, a)
        elif kind == "live":
            assert a.get("kind") in LIVE, (fn, a)
        elif kind == "ask":
            assert a.get("q"), fn


@pytest.mark.parametrize("tid", sorted(TOURS))
def test_tour_targets_exist_on_their_page(tid):
    t = TOURS[tid]
    assert t["path"] in ROUTES, (tid, t["path"])
    page = _read(WEB, "pages", ROUTES[t["path"]] + ".vue") + _read(WEB, "App.vue")
    for s in t["steps"]:
        assert 'data-help="{}"'.format(s["help"]) in page, (tid, s["help"], ROUTES[t["path"]])
        assert s["text"].strip()


def test_front_page_stages_open_existing_chapters():
    src = _read(HELP, "index.js")
    have = {(c[0], c[1]) for c in _chapters()}
    for ed in ("teach", "enterprise"):
        m = re.search(ed + r": \[([^\]]*)\]", src)
        slugs = re.findall(r"'([a-z0-9-]+)'", m.group(1))
        assert len(slugs) == 7, ed
        for s in slugs:
            assert (ed, s) in have, (ed, s)


def test_every_video_has_a_recording_script():
    """视频清单里的每一段，录制脚本里都有剧本（反过来也一样）；企业版视频都在企业版的章节里用到。"""
    import importlib.util
    path = os.path.join(os.path.dirname(WEB), "..", "tools", "help_videos.py")
    spec = importlib.util.spec_from_file_location("help_videos", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert set(mod.SCRIPTS) == set(VIDEOS), set(mod.SCRIPTS) ^ set(VIDEOS)
    used = {_args(b).get("name") for _, _, _, src in _chapters() for k, b in FENCE.findall(src) if k == "video"}
    assert used == set(VIDEOS), set(VIDEOS) ^ used
