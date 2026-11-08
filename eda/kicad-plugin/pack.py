"""问渠电子 KiCad 插件打包（第 113 轮 P6）：插件文件 + wqeda 检查引擎 + 器件数据 + 示例工厂 → 一个 zip。

    python3 eda/kicad-plugin/pack.py <输出.zip>

zip 里是一个文件夹 wenquest-eda/，解压到 KiCad 9 的插件文件夹即可（帮助里写了各系统的位置）。
同一份源文件每次打出的字节一样（文件按名字排序、时间固定）。"""

from __future__ import annotations

import io
import os
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
EDA = os.path.dirname(HERE)
FOLDER = "wenquest-eda"
FIXED = (2026, 1, 1, 0, 0, 0)


def files():
    """(zip 里的路径, 本机路径)"""
    out = []
    for name in ("plugin.json", "check.py", "requirements.txt", "README.md"):
        out.append((name, os.path.join(HERE, name)))
    for sub, root in (
        ("resources", os.path.join(HERE, "resources")),
        ("wq_kicad", os.path.join(HERE, "wq_kicad")),
        ("wqeda", os.path.join(EDA, "wqeda")),
        ("parts", os.path.join(EDA, "parts")),
        ("factories", os.path.join(EDA, "examples", "factories")),
    ):
        for d, dirs, fs in os.walk(root):
            dirs[:] = sorted(x for x in dirs if x != "__pycache__")
            for f in sorted(fs):
                if f.endswith((".pyc", ".pyo")):
                    continue
                p = os.path.join(d, f)
                out.append((os.path.join(sub, os.path.relpath(p, root)).replace(os.sep, "/"), p))
    return sorted(out)


def build():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for arc, path in files():
            info = zipfile.ZipInfo("{}/{}".format(FOLDER, arc), FIXED)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            with open(path, "rb") as f:
                z.writestr(info, f.read())
    return buf.getvalue()


if __name__ == "__main__":
    data = build()
    with open(sys.argv[1] if len(sys.argv) > 1 else "wenquest-eda-kicad-plugin.zip", "wb") as f:
        f.write(data)
    print("{} 字节".format(len(data)))
