# -*- coding: utf-8 -*-
"""CI 出错时把日志的最后几十行作为 GitHub 注释（annotation）发出来，便于通过 GitHub 接口直接读到出错原因。

用法：python3 ci_annotate.py <标题> <日志文件> [行数=120]
"""
import re
import sys

title, path = sys.argv[1], sys.argv[2]
n = int(sys.argv[3]) if len(sys.argv) > 3 else 120
try:
    lines = open(path, encoding="utf-8", errors="replace").read().splitlines()[-n:]
except OSError as e:
    lines = ["（读不到日志：{}）".format(e)]
lines = [re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", x)[:300] for x in lines] or ["（日志是空的：{}）".format(path)]
for i in range(0, len(lines), 160):
    msg = "\n".join(lines[i:i + 160]).replace("%", "%25").replace("\r", "").replace("\n", "%0A")
    print("::error title={} ({}/{})::{}".format(title, i // 160 + 1, (len(lines) + 159) // 160, msg or "（空）"))
