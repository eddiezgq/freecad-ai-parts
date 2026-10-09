# -*- coding: utf-8 -*-
"""帮助。

- 第 19 轮 J-8 ~ J-10：资料（以前的帮助文件）副本与原件一致、每份都能转成网页；术语表守住叫法（“不再用”的词不出现在网页上，
  帮助正文与引导也算网页）；导航分组与旧地址跳转。
- 第 30 轮 H-3、H-4（搬自 freecad-ai-parts ADR-0065 的 tests/test_help.py 并扩充）：网页帮助的正文里的自定义块都指得到东西——
  “带我去做”的引导存在、引导要高亮的页面元素（data-help）真在那一页上、引导打开的地址在路由里、动画已登记、视频在清单里且清单里
  每段都用到、首页全流程七站都有对应章节、右上角“帮助”指向存在的章节；章节文件名是 NN-名字.md；服务器的资料与视频接口。
  页面改了把标记弄丢，这里会报出来。"""
import importlib.util
import json
import os
import re

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
DIGITAL = os.path.dirname(HERE)
REPO = os.path.dirname(os.path.dirname(DIGITAL))
WEB = os.path.join(DIGITAL, "web", "src")
HELP = os.path.join(WEB, "help")
EDITIONS = ("teach", "enterprise")
FENCE = re.compile(r"^```(\w+)[ \t]*\n(.*?)^```[ \t]*$", re.M | re.S)
BLOCKS = {"goto", "anim", "video", "live", "ask"}
LIVE = {"plant", "machines", "kpi"}


def _read(*p):
    with open(os.path.join(*p), encoding="utf-8") as f:
        return f.read()


def _sync():
    spec = importlib.util.spec_from_file_location("help_sync", os.path.join(DIGITAL, "help", "sync.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _chapters():
    out = []
    for ed in EDITIONS:
        d = os.path.join(HELP, ed)
        for fn in sorted(os.listdir(d)):
            out.append((ed, re.sub(r"^\d+-", "", fn[:-3]) if fn.endswith(".md") else fn, fn, _read(d, fn)))
    return out


def _args(body):
    return {m.group(1): m.group(2).strip() for m in re.finditer(r"^\s*([a-z_]+)\s*:\s*(.*)$", body, re.M)}


TOURS = json.loads(_read(HELP, "tours.json"))
VIDEOS = json.loads(_read(HELP, "videos.json"))
ANIMS = set(re.findall(r"^\s+'?([\w-]+)'?: defineAsyncComponent", _read(WEB, "components", "help", "anim", "index.js"), re.M))
ROUTES = dict(re.findall(r"path: '([^']+)', component: \(\) => import\('\./pages/(\w+)\.vue'\)", _read(WEB, "main.js")))
REDIRECTS = set(re.findall(r"path: '([^']+)', redirect:", _read(WEB, "main.js")))


def _route_ok(path):
    """站内地址在路由里：完全相同，或匹配带参数的路由（/ont/:type、/help/:ed?/:ch? ……）"""
    path = path.split("?")[0].split("#")[0]
    if path in ROUTES or path in REDIRECTS:
        return True
    for r in ROUTES:
        if ":" in r and not r.startswith("/:"):
            rx = "^" + re.sub(r"/:\w+(\([^)]*\))?\?", r"(/[^/]+)?", r)
            rx = re.sub(r":\w+\(\.\*\)", r".+", rx)
            rx = re.sub(r":\w+", r"[^/]+", rx) + "$"
            if re.match(rx, path):
                return True
    return False


# ---------------------------------------------------------------- 资料（以前的帮助文件，/api/help/docs）
def test_copies_match_originals():
    """digital/help 里是 docs/帮助、docs/演示 的副本：改原件后要运行 help/sync.py"""
    m = _sync()
    if not os.path.isdir(os.path.join(REPO, "docs", "帮助")):
        pytest.skip("不在完整仓库里（只有 factory/）")
    for src, dst in m.FILES.items():
        assert src.exists(), "原件不存在：{}".format(src)
        assert dst.exists(), "副本不存在：{}（运行 python3 factory/digital/help/sync.py）".format(dst.name)
        assert src.read_text(encoding="utf-8") == dst.read_text(encoding="utf-8"), "{} 与原件不一致（运行 help/sync.py）".format(dst.name)


def test_every_doc_renders_and_links():
    pytest.importorskip("markdown")
    from hub import help_api as HA
    groups = HA.listing()
    names = [i["name"] for g in groups for i in g["items"]]
    assert {"使用说明", "两周情景", "数字工厂术语表", "厂情中枢", "经营与财务", "学校版演示脚本", "企业版演示脚本", "演示前检查表",
            "数字工厂上线与维护"} <= set(names)
    for n in names:
        with open(HA.path_of(n), encoding="utf-8") as f:
            html = HA.render(f.read())
        assert "<h1" in html, n
    html = HA.render("见[两周情景](两周情景.md)和[术语](数字工厂术语表.md#一工厂与时间)")
    assert 'href="/help/docs/两周情景"' in html and 'href="/help/docs/数字工厂术语表#' in html
    assert HA.path_of("../app") is None and HA.path_of("没有这份") is None


def test_index_links_point_to_existing_docs():
    from hub import help_api as HA
    with open(HA.INDEX, encoding="utf-8") as f:
        md = f.read()
    for name in re.findall(r"\]\(([^)/#]+)\.md\)", md):
        assert HA.path_of(name), "总目录链接到不存在的帮助：" + name


def test_help_api_routes(tmp_path, monkeypatch):
    """/api/help/docs 要登录；/api/help/media 不用登录，目录不存在时为空；/help-media/ 只给清单里那种文件名"""
    pytest.importorskip("markdown")
    from fastapi import Depends, FastAPI, HTTPException
    from fastapi.testclient import TestClient
    from hub import help_api as HA

    def user_of(x_wq_token: str = ""):
        return {"name": "t"}

    def need_login():
        raise HTTPException(401, "请先登录")

    app = FastAPI()
    HA.mount(app, user_of)
    c = TestClient(app)
    monkeypatch.setattr(HA, "HELP_MEDIA", str(tmp_path / "没有"))
    assert c.get("/api/help/media").json() == {"files": []}
    (tmp_path / "teach-login.webm").write_bytes(b"x")
    (tmp_path / "说明.txt").write_text("x")
    monkeypatch.setattr(HA, "HELP_MEDIA", str(tmp_path))
    assert c.get("/api/help/media").json() == {"files": ["teach-login.webm"]}
    assert c.get("/help-media/teach-login.webm").status_code == 200
    assert c.get("/help-media/说明.txt").status_code == 404 and c.get("/help-media/没有.webm").status_code == 404
    groups = c.get("/api/help/docs").json()["groups"]
    assert any(i["name"] == "两周情景" for g in groups for i in g["items"])
    d = c.get("/api/help/docs/两周情景").json()
    assert d["name"] == "两周情景" and "<h1" in d["html"]
    assert c.get("/api/help/docs/没有这份").status_code == 404
    # 资料要登录：user_of 拒绝时 401
    app2 = FastAPI()
    HA.mount(app2, lambda: need_login())
    c2 = TestClient(app2)
    assert c2.get("/api/help/docs").status_code == 401 and c2.get("/api/help/media").status_code == 200


# ---------------------------------------------------------------- 网页帮助（教学版、企业版）
def test_both_editions_have_chapters_with_titles():
    ch = _chapters()
    for ed in EDITIONS:
        assert any(c[0] == ed for c in ch), ed
    for ed, slug, fn, src in ch:
        # help/index.js 把 help/<版本>/ 里每个 .md 都当一章：工作清单之类不能放这里（放 digital/docs/帮助编写/）
        assert re.match(r"^\d{2}-[a-z0-9-]+\.md$", fn), "{}/{}：章节文件名要是 NN-名字.md".format(ed, fn)
        assert src.startswith("# "), fn
    slugs = [(c[0], c[1]) for c in ch]
    assert len(slugs) == len(set(slugs))
    teach = {c[1] for c in ch if c[0] == "teach"}
    # 第 30 轮 H-3：教学版覆盖七个领域、实验与任务、情景导演、厂情中枢、这门课怎么用数字工厂
    assert {"insight", "service", "supply", "finance", "maint", "people", "ehs", "energy", "labs", "director", "course"} <= teach


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
    # 正文里的站内链接（[实验 15](/lab15)）要在路由里
    for href in re.findall(r"\]\((/[^)\s]*)\)", src):
        assert _route_ok(href), (fn, href)


@pytest.mark.parametrize("tid", sorted(TOURS))
def test_tour_targets_exist_on_their_page(tid):
    t = TOURS[tid]
    assert t["path"] in ROUTES, (tid, t["path"])
    page = _read(WEB, "pages", ROUTES[t["path"]] + ".vue") + _read(WEB, "App.vue")
    assert t["steps"] and t["title"].strip()
    for s in t["steps"]:
        assert 'data-help="{}"'.format(s["help"]) in page, (tid, s["help"], ROUTES[t["path"]])
        assert s["text"].strip()


def test_every_tour_is_used():
    used = {_args(b).get("tour") for _, _, _, src in _chapters() for k, b in FENCE.findall(src) if k == "goto"}
    assert used == set(TOURS), set(TOURS) ^ used


def test_front_page_stages_open_existing_chapters():
    src = _read(HELP, "index.js")
    have = {(c[0], c[1]) for c in _chapters()}
    for ed in EDITIONS:
        m = re.search(ed + r": \[([^\]]*)\]", src)
        slugs = re.findall(r"'([a-z0-9-]+)'", m.group(1))
        assert len(slugs) == 7, ed
        for s in slugs:
            assert (ed, s) in have, (ed, s)


def test_videos_listed_and_used():
    """正文用到的视频都在清单里（上面逐章查了），清单里的每一段都有章节用到"""
    used = {_args(b).get("name") for _, _, _, src in _chapters() for k, b in FENCE.findall(src) if k == "video"}
    assert used == set(VIDEOS), set(VIDEOS) ^ used
    for k, v in VIDEOS.items():
        assert v["edition"] in EDITIONS and v["title"].strip(), k


def test_every_video_has_a_recording_script():
    """视频清单里的每一段，录制脚本（tools/help_videos.py）里都有剧本，反过来也一样"""
    path = os.path.join(DIGITAL, "tools", "help_videos.py")
    if not os.path.exists(path):
        pytest.skip("还没有录制脚本 tools/help_videos.py（第 30 轮第 5 步）")
    spec = importlib.util.spec_from_file_location("help_videos", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert set(mod.SCRIPTS) == set(VIDEOS), set(mod.SCRIPTS) ^ set(VIDEOS)


def test_page_help_button_targets_exist():
    """右上角“帮助”（help/pages.js 的对照表）指向存在的章节或资料"""
    src = _read(HELP, "pages.js")
    have = {(c[0], c[1]) for c in _chapters()}
    teach = src[src.index("export const PAGE_CHAPTER = ["):src.index("export const PAGE_CHAPTER_ENT")]
    ent = src[src.index("export const PAGE_CHAPTER_ENT = ["):src.index("export function helpLink")]
    pairs = re.findall(r"\['(/[^']*)', '([^']+)'\]", teach)
    assert len(pairs) >= 30
    from hub import help_api as HA
    for page, target in pairs:
        assert _route_ok(page), page
        if target.startswith("/help/docs/"):
            assert HA.path_of(target[len("/help/docs/"):]), target
        else:
            assert ("teach", target) in have, (page, target)
    for page, target in re.findall(r"\['(/[^']*)', '([^']+)'\]", ent):
        assert _route_ok(page) and ("enterprise", target) in have, (page, target)


def test_old_help_links_moved():
    """以前的 /help/<文件名> 链接都改成了 /help/teach/<章>、/help/docs/<名字>"""
    bad = []
    for root, _, files in os.walk(WEB):
        for fn in files:
            if fn.endswith((".vue", ".js")):
                t = _read(root, fn)
                for m in re.findall(r"""['"`](/help/[^'"`]*)""", t):
                    if fn == "main.js" or (fn == "Help.vue" and m == "/help/media"):     # 路由定义；视频清单接口
                        continue
                    if not re.match(r"^/help/(teach|enterprise|docs)(/|$)", m) and "${" not in m and m != "/help/":
                        bad.append("{}：{}".format(fn, m))
    assert not bad, bad
    assert "'/api/help'" not in _read(WEB, "pages", "Help.vue")


# ---------------------------------------------------------------- 术语与导航
def _banned():
    with open(os.path.join(DIGITAL, "help", "数字工厂术语表.md"), encoding="utf-8") as f:
        md = f.read()
    out = set()
    for line in md.splitlines():
        if line.startswith("|") and not line.startswith("| ---") and "不再用" not in line:
            last = line.strip().strip("|").split("|")[-1].strip()
            out |= {w.strip() for w in last.split("、") if w.strip()}
    return out


def _visible(text):
    """去掉注释：HTML 注释、/* */、整行和行尾的 // 注释（网页上看不到的不算）"""
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return "\n".join(re.sub(r"(^|\s)//.*$", "", line) for line in text.splitlines())


def test_glossary_banned_words_not_on_pages():
    banned = _banned()
    assert {"预案", "经营与成本", "仿真时间", "制造故障", "告警"} <= banned
    hits = []
    for root, _, files in os.walk(WEB):
        for fn in files:
            if fn.endswith((".vue", ".js", ".md", ".json")):        # 帮助正文（.md）与引导（tours.json）也显示在网页上
                p = os.path.join(root, fn)
                with open(p, encoding="utf-8") as f:
                    t = f.read() if fn.endswith((".md", ".json")) else _visible(f.read())
                for w in banned:
                    if w in t:
                        hits.append("{}：{}".format(os.path.relpath(p, WEB), w))
    assert not hits, "页面上出现了术语表里“不再用”的词：" + "；".join(hits)


def test_nav_groups_and_old_routes():
    app = _read(WEB, "App.vue")
    for g in ("总览", "从订单到回款", "保障", "设计与工艺", "教学", "资源"):
        assert "title: '{}'".format(g) in app
    assert "实验 15 · 任务" not in app and "'/labs'" in app and "'/director'" in app
    routes = _read(WEB, "main.js")
    assert "{ path: '/work/manager', redirect: { path: '/finance', query: { tab: 'production' } } }" in routes
    for n in [7] + list(range(15, 24)):
        assert ("'/teach'" if n == 7 else "'/lab{}'".format(n)) in routes
    assert not os.path.exists(os.path.join(WEB, "pages", "Manager.vue"))
    # 帮助：登录前也能看（public），登录后在工作台框架里（shell）；引导层挂在最外面
    assert "{ path: '/help/:ed?/:ch?', component: () => import('./pages/Help.vue'), meta: { public: true, shell: true } }" in routes
    assert "<TourOverlay />" in app and "route.meta.shell && session.token" in app


def test_cost_entry_only_on_enterprise_plants():
    """第 30 轮：企业工厂没有“经营与财务”，厂长用左栏“生产成本”；演示工厂导航不变（不显示这一项）"""
    app = _read(WEB, "App.vue")
    assert "{ to: '/cost', label: '生产成本', role: 'manager', only: () => !demoPlant.value }" in app
    assert "const demoPlant = computed(() => cfg.value.plant?.demo !== false);" in app
    assert ROUTES.get("/cost") == "Cost" and "<ProductionCost" in _read(WEB, "pages", "Cost.vue")
    hub = _read(DIGITAL, "hub", "app.py")
    nav = hub[hub.index("TEACH_ONLY_NAV = ("):hub.index("\n\n", hub.index("TEACH_ONLY_NAV = ("))]   # 企业工厂隐藏的入口
    assert '"/finance"' in nav and "/cost" not in nav
