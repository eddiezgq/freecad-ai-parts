"""Windows 脚本的编码：Windows PowerShell 5.1 读不带 BOM 的 .ps1 时按本机代码页解析，里面的中文会变成乱码、脚本报语法错。
所以每个 .ps1 都要存成带 BOM 的 UTF-8（用户 2026-10-08 在 Windows 上运行 start.ps1 时遇到）。"""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_powershell_scripts_are_utf8_with_bom():
    files = subprocess.run(["git", "ls-files", "*.ps1"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    assert files, "仓库里应有 .ps1 脚本"
    bad = [f for f in files if not (ROOT / f).read_bytes().startswith(b"\xef\xbb\xbf")]
    assert not bad, "这些 .ps1 要存成带 BOM 的 UTF-8：" + "、".join(bad)
    for f in files:
        (ROOT / f).read_bytes()[3:].decode("utf-8")      # 其余部分是合法的 UTF-8
