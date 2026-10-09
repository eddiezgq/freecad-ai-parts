# -*- coding: utf-8 -*-
"""把数字工厂的帮助文件同步进工厂镜像（第 19 轮 J-10：每页右上角“帮助”在网页里打开）。

工厂镜像只打包 factory/ 目录，看不到仓库根目录的 docs/；所以这里放一份副本。**原件在 docs/帮助/ 和 docs/演示/，只改原件**，
改完运行：

    python3 factory/digital/help/sync.py

测试 tests/test_help.py 会核对副本与原件一字不差（.github/workflows/factory.yml 也监听这些原件，改了会重新部署）。
"""
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
HELP = ["两周情景", "数字工厂术语表", "厂情中枢", "客户与服务", "安全环保", "设备维护", "人员与排班", "采购与来料", "能源与环境", "经营与财务",
        "仿真与分析", "流体分析", "数控编程", "数字孪生", "设计优化", "虚拟PLC", "零件与机器人库", "数字工厂企业版使用说明", "数字工厂课程接口", "数字工厂上线与维护"]
DEMO = ["学校版演示脚本", "企业版演示脚本", "演示前检查表"]
FILES = {**{REPO / "docs" / "帮助" / f"{n}.md": HERE / f"{n}.md" for n in HELP},
         **{REPO / "docs" / "演示" / f"{n}.md": HERE / f"{n}.md" for n in DEMO}}

if __name__ == "__main__":
    for src, dst in FILES.items():
        if src.exists():
            shutil.copyfile(src, dst)
            print(dst.relative_to(REPO))
        else:
            print("还没有：", src.relative_to(REPO))
