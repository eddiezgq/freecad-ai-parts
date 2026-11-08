"""问渠电子 KiCad 插件的入口（第 113 轮 P6）：KiCad 9 起的工具栏按钮会运行这个文件。"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)  # 打包时 wqeda 和 wq_kicad 都放在插件目录里

from wq_kicad.app import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
