# -*- coding: utf-8 -*-
"""帮助。

- 第 19 轮 J-8 ~ J-10：资料（以前的帮助文件）副本与原件一致、每份都能转成网页；术语表守住叫法（“不再用”的词不出现在网页上，
  帮助正文与引导也算网页）；导航分组与旧地址跳转。
- 第 30 轮 H-3、H-4（搬自 freecad-ai-parts ADR-0065 的 tests/test_help.py 并扩充）：网页帮助的正文里的自定义块都指得到东西——
  “带我去做”的引导存在、引导要高亮的页面元素（data-help）真在那一页上、引导打开的地址在路由里、动画已登记、视频在清单里且清单里
  每段都用到、首页全流程七站都有对应章节、右上角“帮助”指向存在的章节；章节文件名是 NN-名字.md；服务器的资料与视频接口。
  页面改了把标记弄丢，这里会报出来。
- 第 30 轮 §八 8-1：新块 lab（嵌虚拟实验，副本与课程原件一致、预置按钮真有）/ try（当场动手，动作在白名单里）/ quiz（你来选，
  选项格式、至少一个对的、链回的小节存在）；带我去做的“做完检测”（done 条件指向真地址、真接口、真元素）；逐章覆盖统计
  （8-3 起强制；只数“:::查表”以上的正文）；领域实时数据（live kind: domain）取的字段是接口真给的。"""
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
BLOCKS = {"goto", "anim", "video", "live", "ask", "lab", "try", "quiz"}
LIVE = {"plant", "machines", "kpi", "domain"}


def _read(*p):
    with open(os.path.join(*p), encoding="utf-8") as f:
        return f.read()


def _domain_live():
    """web/src/lib/domainlive.js：领域 → (接口, [字段])"""
    src = _read(WEB, "lib", "domainlive.js")
    out = {}
    for m in re.finditer(r"^  (\w+): \{ api: '([^']+)'.*?items: \[(.*?)\] \},?$", src, re.M | re.S):
        out[m.group(1)] = (m.group(2), re.findall(r"\['(\w+)', '", m.group(3)))
    return out


DOMAIN_LIVE = _domain_live()


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


def _block_args(body):
    """与前端 lib/helpdoc.js 的 args() 同样的读法：键后面空着，下面几行“  - 项”是它的列表（quiz 的 options）"""
    out, lst = {}, None
    for line in body.split("\n"):
        li = re.match(r"^\s+-\s+(.*)$", line) if lst else None
        if li:
            out[lst].append(li.group(1).strip())
            continue
        m = re.match(r"^\s*([a-z_]+)\s*:\s*(.*)$", line)
        if m:
            out[m.group(1)] = m.group(2).strip()
            lst = None if m.group(2).strip() else m.group(1)
            if lst:
                out[lst] = []
    return out


def _quiz_option(s):
    parts = [x.strip() for x in s.split("|")]
    return {"text": parts[0], "verdict": parts[1] if len(parts) > 1 else "", "why": " | ".join(parts[2:])}


EXTRA = json.loads(_read(HELP, "extra.json"))          # 本仓库独有的引导与视频（问渠这边空，freecad-ai-parts 是企业功能的）
TOURS = dict(json.loads(_read(HELP, "tours.json")), **EXTRA.get("tours", {}))
LAB_PUBLIC = os.path.join(DIGITAL, "web", "public", "labs")
LABS = dict(re.findall(r"^  (\w+): \{ title: '[^']+'.*?presets: \[([^\]]*)\] \}", _read(HELP, "labs.js"), re.M | re.S))
LABS = {k: re.findall(r"'([\w-]+)'", v) for k, v in LABS.items()}
VIDEOS = dict(json.loads(_read(HELP, "videos.json")), **EXTRA.get("videos", {}))
ANIMS = set(re.findall(r"^\s+'?([\w-]+)'?: defineAsyncComponent", _read(WEB, "components", "help", "anim", "index.js"), re.M))
ROUTES = dict(re.findall(r"path: '([^']+)', component: \(\) => import\('\./pages/(\w+)\.vue'\)", _read(WEB, "main.js")))
REDIRECTS = set(re.findall(r"path: '([^']+)', redirect:", _read(WEB, "main.js")))
# 企业页面（main.js 的 ENTERPRISE_PAGES）：页面文件在（freecad-ai-parts）才有这条路由
for _f, _p in re.findall(r"'\./pages/(\w+)\.vue': '([^']+)'", _read(WEB, "main.js").split("ENTERPRISE_PAGES = ", 1)[1].split("\n", 1)[0]):
    if os.path.exists(os.path.join(WEB, "pages", _f + ".vue")):
        ROUTES[_p] = _f


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
            if a["kind"] == "domain":     # 领域数据：domain 要在 web/src/lib/domainlive.js 里，取的字段要是接口真给的
                assert a.get("domain") in DOMAIN_LIVE, (fn, a)
        elif kind == "ask":
            assert a.get("q"), fn
        elif kind == "lab":
            assert a.get("id") in LABS, (fn, a)
            assert os.path.exists(os.path.join(LAB_PUBLIC, a["id"] + ".html")), (fn, a)
            if a.get("preset"):
                assert a["preset"] in LABS[a["id"]], (fn, a)
            if a.get("height"):
                assert a["height"].isdigit() and 320 <= int(a["height"]) <= 1200, (fn, a)
        elif kind == "try":
            from hub import help_try as HT
            assert a.get("action") in HT.ACTIONS, (fn, a)
        elif kind == "quiz":
            _check_quiz(ed, fn, src, _block_args(body))
    # 正文里的站内链接（[实验 15](/lab15)）要在路由里
    for href in re.findall(r"\]\((/[^)\s]*)\)", src):
        assert _route_ok(href), (fn, href)


def _heads(src):
    return {m.strip() for m in re.findall(r"^#{2,3} (.+)$", src, re.M)}


def _check_quiz(ed, fn, src, a):
    assert a.get("q"), fn
    opts = [_quiz_option(o) for o in a.get("options") or []]
    assert 2 <= len(opts) <= 5, (fn, a.get("q"))
    for o in opts:
        assert o["text"] and o["verdict"] in ("right", "wrong") and o["why"], (fn, o)
    assert any(o["verdict"] == "right" for o in opts), (fn, a.get("q"))
    if a.get("more"):
        f, _, sec = a["more"].partition("#")
        if f:
            chs = {c[2][:-3]: c[3] for c in _chapters() if c[0] == ed}
            assert f.removesuffix(".md") in chs, (fn, a["more"])
            target = chs[f.removesuffix(".md")]
        else:
            target = src
        assert not sec or sec in _heads(target), (fn, a["more"], "链回的小节标题不存在")


def test_block_parsing_matches_frontend():
    """Python 的读法（_block_args）与前端一样：列表、空值；quiz 的选项“文字 | right | 道理”"""
    a = _block_args("q: 磨床逾期 120 小时：\noptions:\n  - 现在保养 | wrong | 停 3 小时\n  - 下班后保养 | right | 合计约 $235\nmore: 11-maint#三个方案\n")
    assert a["q"] == "磨床逾期 120 小时：" and a["more"] == "11-maint#三个方案" and len(a["options"]) == 2
    assert _quiz_option(a["options"][1]) == {"text": "下班后保养", "verdict": "right", "why": "合计约 $235"}
    js = _read(WEB, "lib", "helpdoc.js")
    assert "export const BLOCKS = ['goto', 'anim', 'video', 'live', 'ask', 'lab', 'try', 'quiz'];" in js
    assert {"goto", "anim", "video", "live", "ask", "lab", "try", "quiz"} == BLOCKS


def test_lab_copies_match_course():
    """web/public/labs/ 是课程《数字工厂实训》实验页的副本：改原件后运行 tools/sync_help_labs.py"""
    spec = importlib.util.spec_from_file_location("sync_help_labs", os.path.join(DIGITAL, "tools", "sync_help_labs.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    assert set(LABS) == set(m.LABS), set(LABS) ^ set(m.LABS)            # labs.js 登记的与同步的一样
    for src, dst in m.FILES.items():
        assert dst.exists(), "副本不存在：{}（运行 python3 factory/digital/tools/sync_help_labs.py）".format(dst.name)
        page = dst.read_text(encoding="utf-8")
        assert not re.search(r"""(src|href)=["'](?!#)""", page), dst.name + "：实验页要自成一页（不引外部文件）"
        for p in LABS[dst.stem]:
            assert 'data-p="{}"'.format(p) in page, (dst.name, p)          # labs.js 写的预置按钮真在页上
        if src.exists():
            assert src.read_text(encoding="utf-8") == page, "{} 与课程原件不一致（运行 tools/sync_help_labs.py）".format(dst.name)
    if not os.path.isdir(m.SRC):
        pytest.skip("不在完整仓库里（没有 textbook/），只查了副本")
    wf = _read(REPO, ".github", "workflows", "factory.yml")
    assert '"textbook/web-editions/dfactory/src/zh/labs/**"' in wf          # 原件改了要重新部署


HUB_GETS = None


def _hub_gets():
    global HUB_GETS
    if HUB_GETS is None:
        HUB_GETS = set()
        for root, _, files in os.walk(os.path.join(DIGITAL, "hub")):
            for fn in files:
                if fn.endswith(".py"):
                    HUB_GETS |= set(re.findall(r'@app\.get\("(/api/[^"]+)"', _read(root, fn)))
    return HUB_GETS


def _api_ok(path):
    """“做完检测”轮询的接口在枢纽里（GET，地址不带 /api 前缀，可以带路径参数的具体值）"""
    full = "/api" + path.split("?")[0]
    for r in _hub_gets():
        if re.fullmatch(re.sub(r"\{\w+\}", r"[^/]+", r), full):
            return True
    return False


DONE_KEYS = {"route", "query", "selector", "api", "path", "grew", "changed", "gt", "gte", "eq"}


def _check_done(tid, page, d):
    assert set(d) <= DONE_KEYS, (tid, d)
    kinds = [k for k in ("route", "selector", "api") if k in d]
    assert len(kinds) == 1, (tid, d, "done 只写一种：route / selector / api")
    if "route" in d:
        assert _route_ok(d["route"]), (tid, d)
    elif "selector" in d:
        for h in re.findall(r"""data-help=["']?([\w-]+)""", d["selector"]):
            assert 'data-help="{}"'.format(h) in page, (tid, d)
    else:
        assert d["api"].startswith("/") and not d["api"].startswith("/api/") and _api_ok(d["api"]), (tid, d)
        assert d.get("path"), (tid, d)
        assert sum(k in d for k in ("grew", "changed", "gt", "gte", "eq")) == 1, (tid, d)


@pytest.mark.parametrize("tid", sorted(TOURS))
def test_tour_targets_exist_on_their_page(tid):
    t = TOURS[tid]
    assert t["path"] in ROUTES, (tid, t["path"])
    page = _read(WEB, "pages", ROUTES[t["path"]] + ".vue") + _read(WEB, "App.vue")
    assert t["steps"] and t["title"].strip()
    for s in t["steps"]:
        assert 'data-help="{}"'.format(s["help"]) in page, (tid, s["help"], ROUTES[t["path"]])
        assert s["text"].strip()
        assert set(s) <= {"help", "text", "done"}, (tid, s)
        if "done" in s:
            _check_done(tid, page, s["done"])


def test_every_tour_is_used():
    used = {_args(b).get("tour") for _, _, _, src in _chapters() for k, b in FENCE.findall(src) if k == "goto"}
    assert used == set(TOURS), set(TOURS) ^ used


def test_front_page_stages_open_existing_chapters():
    src = _read(HELP, "index.js")
    have = {(c[0], c[1]) for c in _chapters()}
    for ed in EDITIONS:
        m = re.search(ed + r": \[([^\]]*)\]", src)
        slugs = re.findall(r"'([a-z0-9|-]+)'", m.group(1))
        assert len(slugs) == 7, ed
        for s in slugs:                       # “a|b”：有 a 用 a，没有用 b——至少一个是真有的章
            assert any((ed, x) in have for x in s.split("|")), (ed, s)


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
                    if fn == "main.js" or (fn == "Help.vue" and m == "/help/media") or (fn == "TryBlock.vue" and m.startswith("/help/try")):     # 路由定义；视频清单、当场动手接口
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


# ---------------------------------------------------------------- 逐章覆盖（第 30 轮 §八“每章的样子”H-10、验收）
COVER_EXEMPT = {("teach", "course"), ("teach", "faq")}           # 这门课怎么用数字工厂、常见问题：不是一个领域的操作章
INTERACTIVE = ("lab", "try", "goto_done", "quiz")                  # 问 AI 不算一种互动
HANDS_ON = ("try", "goto_done")                                     # 在真工厂里动手


def coverage(src):
    """一章里各种块有几个：anim / video / goto / goto_done（带“做完检测”的带我去做）/ lab / try / quiz / live / ask"""
    n = {k: 0 for k in ("anim", "video", "goto", "goto_done", "lab", "try", "quiz", "live", "ask")}
    src = re.split(r"^:::查表[ \t]*$", src, maxsplit=1, flags=re.M)[0]       # 折叠的“查表”里的块不算：要放在正文里
    for kind, body in FENCE.findall(src):
        if kind not in n:
            continue
        n[kind] += 1
        if kind == "goto" and any(st.get("done") for st in (TOURS.get(_args(body).get("tour")) or {}).get("steps", [])):
            n["goto_done"] += 1
    return n


def coverage_gaps(n):
    """按细则 §八 验收：动画 ≥ 1（anim，或 lab 嵌课程的动画页）；视频或“做完打勾”的带我去做 ≥ 1；互动 ≥ 2 种且至少一种是当场动手或做完打勾；实时数据 ≥ 1"""
    gaps = []
    if n["anim"] < 1 and n["lab"] < 1:
        gaps.append("没有动画")
    if n["video"] < 1 and n["goto_done"] < 1:
        gaps.append("没有视频，也没有做完打勾的带我去做")
    kinds = {k for k in INTERACTIVE if n[k]}
    if len(kinds) < 2:
        gaps.append("互动只有 {} 种（{}）".format(len(kinds), "、".join(sorted(kinds)) or "无"))
    if not kinds & set(HANDS_ON):
        gaps.append("没有在真工厂里动手的互动（try 或做完打勾的 goto）")
    if n["live"] < 1:
        gaps.append("没有实时数据")
    return gaps


def test_coverage_rule_itself():
    full = ("```anim\nname: flow\n```\n```video\nname: teach-maint\n```\n```try\naction: stop-grinder\n```\n"
            "```quiz\nq: x\noptions:\n  - a | right | b\n  - c | wrong | d\n```\n```live\nkind: machines\n```\n```ask\nq: 问\n```\n")
    n = coverage(full)
    assert n["anim"] == n["video"] == n["try"] == n["quiz"] == n["live"] == n["ask"] == 1
    assert coverage_gaps(n) == []
    assert any("互动只有 1 种" in g for g in coverage_gaps(coverage(full.replace("```try\naction: stop-grinder\n```\n", ""))))
    no_hands = coverage(full.replace("```try\naction: stop-grinder\n```\n", "```lab\nid: weibull\n```\n"))
    assert coverage_gaps(no_hands) == ["没有在真工厂里动手的互动（try 或做完打勾的 goto）"]
    done_tour = next(t for t, v in TOURS.items() if any(st.get("done") for st in v["steps"]))
    plain_tour = next(t for t, v in TOURS.items() if not any(st.get("done") for st in v["steps"]))
    assert coverage("```goto\ntour: {}\n```".format(done_tour))["goto_done"] == 1
    assert coverage("```goto\ntour: {}\n```".format(plain_tour))["goto_done"] == 0
    assert coverage_gaps(coverage("```ask\nq: 问\n```"))[-1] == "没有实时数据"


def test_domain_live_fields_are_real():
    """帮助里“本厂此刻”的领域数据：每个领域的接口真有、取的字段是这个接口的 kpis 真返回的（查 hub 源码里的键名）"""
    assert set(DOMAIN_LIVE) == {"service", "supply", "maint", "people", "ehs", "energy", "finance"}
    for dom, (api, fields) in DOMAIN_LIVE.items():
        api_src = _read(DIGITAL, "hub", dom + "_api.py")
        assert '"/api{}"'.format(api) in api_src, (dom, api)
        mod = _read(DIGITAL, "hub", dom + ".py") + api_src + (_read(DIGITAL, "hub", "crm.py") if dom == "service" else "")
        for f in fields:
            assert re.search(r'["\']{}["\']\s*:|\b{}=' .format(f, f), mod), (dom, f)


def test_every_chapter_covered():
    """教学版每章：动画、视频或做完打勾、两种互动（其一在真工厂动手）、实时数据。第 30 轮 §八 8-3 逐章改写完，起强制（少一样不通过）"""
    report = {}
    for ed, slug, fn, src in _chapters():
        if ed != "teach" or (ed, slug) in COVER_EXEMPT:
            continue
        gaps = coverage_gaps(coverage(src))
        if gaps:
            report[fn] = gaps
    assert not report, "；".join("{}：{}".format(k, "、".join(v)) for k, v in sorted(report.items()))


def test_demo_chapter_with_all_new_blocks():
    """样张（tests/fixtures/help_blocks_demo.md，不在帮助目录里）：新块都写对了、各项检查都走一遍，逐章覆盖规则判它合格"""
    src = _read(HERE, "fixtures", "help_blocks_demo.md")
    test_blocks_point_at_real_things("teach", "blocks-demo", "help_blocks_demo.md", src)
    n = coverage(src)
    assert n["lab"] == n["try"] == n["quiz"] == n["goto_done"] == 1 and coverage_gaps(n) == []
    assert not os.path.exists(os.path.join(HELP, "teach", "help_blocks_demo.md"))
    # 写错的要报出来
    for bad in ("```lab\nid: nope\n```", "```lab\nid: weibull\npreset: nope\n```", "```try\naction: rm-rf\n```",
                "```quiz\nq: x\noptions:\n  - a | right | b\n```", "```quiz\nq: x\noptions:\n  - a | wrong | b\n  - c | wrong | d\n```",
                "```quiz\nq: x\noptions:\n  - a | right | b\n  - c | wrong | d\nmore: 11-maint#没有这一节\n```"):
        with pytest.raises(AssertionError):
            test_blocks_point_at_real_things("teach", "x", "x.md", "# x\n\n" + bad + "\n")
