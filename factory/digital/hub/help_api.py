# -*- coding: utf-8 -*-
"""帮助的服务器端。

- 资料（第 19 轮 J-10；第 30 轮 H-3 改名 /api/help/docs）：较长的说明文件（digital/help/ 里的副本，原件在仓库 docs/帮助/、
  docs/演示/），网页帮助首页的“资料”栏列出，/help/docs/<名字> 打开。总目录是《帮助_数字工厂使用说明》。
  Markdown 在服务器转成 HTML（文件都是仓库里的，可信）。要登录。
- 帮助视频（第 30 轮 H-4，搬自 freecad-ai-parts ADR-0065）：WQ_HELP_MEDIA 目录（缺省 digital/help-media）里的 .webm / .mp4 / .vtt；
  目录不存在时列表为空，帮助页在视频位置显示“带我去做”。不用登录（帮助页登录前也能看）。

网页帮助的正文（教学版、企业版章节）在前端 web/src/help/，随网页打包，不经这里。"""
import os
import re

from fastapi import Depends, HTTPException
from fastapi.responses import FileResponse

HERE = os.path.dirname(os.path.abspath(__file__))
DIGITAL = os.path.dirname(HERE)
HELP_DIR = os.path.join(DIGITAL, "help")
INDEX = os.path.join(DIGITAL, "帮助_数字工厂使用说明.md")
HELP_MEDIA = os.environ.get("WQ_HELP_MEDIA", os.path.join(DIGITAL, "help-media"))
MEDIA_NAME = re.compile(r"^[a-z0-9-]+\.(webm|mp4|vtt)$")
GROUPS = [("开始", ["使用说明", "两周情景", "数字工厂术语表"]),
          ("厂情中枢与七个领域", ["厂情中枢", "客户与服务", "采购与来料", "经营与财务", "设备维护", "人员与排班", "安全环保", "能源与环境"]),
          ("设计与工程软件", ["仿真与分析", "流体分析", "数控编程", "数字孪生", "设计优化", "虚拟PLC", "零件与机器人库"]),
          ("演示", ["学校版演示脚本", "企业版演示脚本", "演示前检查表"]),
          ("企业版、课程与运维", ["数字工厂企业版使用说明", "数字工厂课程接口", "数字工厂上线与维护"])]


def path_of(name):
    if name == "使用说明":
        return INDEX
    if not re.fullmatch(r"[\w一-鿿·\-（）()]+", name or ""):
        return None
    p = os.path.join(HELP_DIR, name + ".md")
    return p if os.path.exists(p) else None


def title_of(md, name):
    m = re.search(r"^#\s+(.+)$", md, re.M)
    return m.group(1).strip() if m else name


def render(md):
    import markdown
    html = markdown.markdown(md, extensions=["tables", "fenced_code", "sane_lists", "toc"], output_format="html5")
    # 资料之间的相对链接（xxx.md）→ 网页里的资料页
    return re.sub(r'href="(?:\./)?([^"/#]+)\.md(#[^"]*)?"', lambda m: 'href="/help/docs/{}{}"'.format(m.group(1), m.group(2) or ""), html)


def listing():
    out = []
    for g, names in GROUPS:
        items = []
        for n in names:
            p = path_of(n)
            if p:
                with open(p, encoding="utf-8") as f:
                    items.append({"name": n, "title": title_of(f.read(), n)})
        out.append({"group": g, "items": items})
    return out


def media_files(d=None):
    d = HELP_MEDIA if d is None else d
    return sorted(f for f in os.listdir(d) if MEDIA_NAME.match(f)) if os.path.isdir(d) else []


def mount(app, user_of):
    @app.get("/api/help/media")
    def help_media():
        """装在这台服务器上的帮助视频（不用登录：帮助页登录前也能看）。"""
        return {"files": media_files()}

    @app.get("/help-media/{name}")
    def help_media_file(name: str):
        f = os.path.join(HELP_MEDIA, name)
        if not MEDIA_NAME.match(name) or not os.path.isfile(f):
            raise HTTPException(404, "没有这段视频")
        return FileResponse(f, headers={"Cache-Control": "public, max-age=86400"})

    @app.get("/api/help/docs")
    def help_index(u=Depends(user_of)):
        return {"groups": listing()}

    @app.get("/api/help/docs/{name}")
    def help_doc(name: str, u=Depends(user_of)):
        p = path_of(name)
        if not p:
            raise HTTPException(404, "没有这份帮助：{}".format(name))
        with open(p, encoding="utf-8") as f:
            md = f.read()
        return {"name": name, "title": title_of(md, name), "html": render(md)}
