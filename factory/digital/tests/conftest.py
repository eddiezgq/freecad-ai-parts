import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DIGITAL = os.path.dirname(HERE)
sys.path[:0] = [DIGITAL, os.path.dirname(DIGITAL)]   # wqbus / sim / hub，以及上一级的 factory 数据
