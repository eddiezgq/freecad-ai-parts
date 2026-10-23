# -*- coding: utf-8 -*-
"""把课程《数字工厂实训》的虚拟实验页同步进工作台网页（第 30 轮 §八 8-1：帮助里的 ```lab``` 块嵌这些页）。

工厂镜像只打包 factory/ 目录，看不到仓库的 textbook/；所以在 factory/digital/web/public/labs/ 放一份副本，网页构建时原样拷进 dist/labs/。
**原件在 textbook/web-editions/dfactory/src/zh/labs/，只改原件**，改完运行：

    python3 factory/digital/tools/sync_help_labs.py

tests/test_help.py 核对副本与原件一字不差（.github/workflows/factory.yml 也监听原件，改了会重新部署）。
"""
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
DIGITAL = HERE.parent
REPO = DIGITAL.parents[1]
SRC = REPO / "textbook" / "web-editions" / "dfactory" / "src" / "zh" / "labs"
DST = DIGITAL / "web" / "public" / "labs"
LABS = ["causal", "whatif", "weibull", "pmopt", "waterfall", "cashflow"]
FILES = {SRC / f"{n}.html": DST / f"{n}.html" for n in LABS}

if __name__ == "__main__":
    DST.mkdir(parents=True, exist_ok=True)
    for src, dst in FILES.items():
        if src.exists():
            shutil.copyfile(src, dst)
            print(dst.relative_to(REPO))
        else:
            print("还没有：", src.relative_to(REPO))
