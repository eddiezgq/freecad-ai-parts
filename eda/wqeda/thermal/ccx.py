# -*- coding: utf-8 -*-
"""调本机 CalculiX（第 111 轮 P4）：写输入文件、跑 ccx、读温度。CalculiX 是 GPL 外部程序，只作工具调用；不联网。"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile

CCX = os.environ.get("WQ_CCX", "ccx")
TIME_LIMIT_S = 300


def read_nt(path):
    """frd 里最后一个温度块：{节点: ℃}"""
    cur, last = None, None
    with open(path, errors="replace") as f:
        for line in f:
            if line.startswith(" -4"):
                cur = {} if line.split()[1] == "NDTEMP" else None
                if cur is not None:
                    last = cur
                continue
            if cur is None:
                continue
            if line.startswith(" -3"):
                cur = None
            elif line.startswith(" -1"):
                cur[int(line[3:13])] = float(line[13:25])
    return last or {}


def run(text, workdir=None):
    """跑 CalculiX，返回 {节点: ℃}；没装 CalculiX 抛 RuntimeError"""
    if shutil.which(CCX) is None:
        raise RuntimeError("没有找到 CalculiX（ccx）")
    tmp = workdir or tempfile.mkdtemp(prefix="wqeda-th-")
    with open(os.path.join(tmp, "job.inp"), "w") as f:
        f.write(text)
    # 线程数照数字工厂（cae/solve.py）：不设时 CalculiX 的 OpenMP 在 CI 机器上会卡住
    env = dict(os.environ, OMP_NUM_THREADS=os.environ.get("WQ_CAE_THREADS", "2"))
    r = subprocess.run([CCX, "-i", "job"], cwd=tmp, capture_output=True, text=True, timeout=TIME_LIMIT_S,
                       stdin=subprocess.DEVNULL, env=env)
    frd = os.path.join(tmp, "job.frd")
    if r.returncode != 0 or not os.path.exists(frd):
        raise RuntimeError("CalculiX 没算出来：" + (r.stdout[-1500:] + r.stderr[-500:]))
    nt = read_nt(frd)
    if workdir is None:
        shutil.rmtree(tmp, ignore_errors=True)
    return nt
