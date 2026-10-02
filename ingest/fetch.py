"""下载登记的规格书（ADR-0040，issue #124）。

    python -m ingest.fetch [--doc src-...] [--pin] [--raw-dir data/raw]

- 只下载 data/sources.yaml 中登记、且所属来源已核实条款或取得授权的文档；按登记的网址下载，不遍历网站
- 文件存到 data/raw/<文档 id>.pdf（不入 git，CI 中只在临时目录）；已有且 SHA-256 相符的不重新下载
- 登记了 sha256 的文档，下载结果不符即报错并删除文件；没有登记的，--pin 时把算出的值写回 data/sources.yaml
- 每份之间间隔几秒，请求头写明项目与用途
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
import time
import urllib.request
from collections.abc import Callable
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
SOURCES_FILE = ROOT / "data" / "sources.yaml"
USER_AGENT = "freecad-ai-parts/0.1 (+https://github.com/eddiezgq/freecad-ai-parts; engineering parts reference)"
MAX_BYTES = 300 * 1024 * 1024
PAUSE_S = 3.0
_SHA = re.compile(r"^[0-9a-f]{64}$")


class FetchError(RuntimeError):
    pass


def registered_documents(data: dict) -> list[dict]:
    """data/sources.yaml 中的全部来源文档，带上所属来源 id。"""
    out = []
    for src in (data or {}).get("sources") or []:
        for doc in src.get("documents") or []:
            out.append({**doc, "source": src["id"]})
    return out


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _download(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/pdf,*/*"})
    with urllib.request.urlopen(req, timeout=120) as resp, dest.open("wb") as f:  # 只用登记的 https 网址
        total = 0
        while chunk := resp.read(1 << 20):
            total += len(chunk)
            if total > MAX_BYTES:
                raise FetchError(f"文件超过 {MAX_BYTES // (1024 * 1024)} MB：{url}")
            f.write(chunk)


def fetch_document(doc: dict, raw_dir: Path = RAW_DIR,
                   download: Callable[[str, Path], None] | None = None) -> tuple[Path, str, bool]:
    """返回（文件路径, SHA-256, 是否新下载）。"""
    download = download or _download
    url = doc.get("url") or ""
    if not url.startswith("https://"):
        raise FetchError(f"{doc['id']}：只下载 https 网址，登记的是 {url!r}")
    want = doc.get("sha256")
    if want is not None and not _SHA.match(str(want)):
        raise FetchError(f"{doc['id']}：登记的 sha256 格式不对")
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / f"{doc['id']}.pdf"
    if path.is_file():
        have = sha256_file(path)
        if want is None or have == want:
            return path, have, False
    tmp = path.with_suffix(".part")
    try:
        download(url, tmp)
        with tmp.open("rb") as f:
            if not f.read(1024).lstrip().startswith(b"%PDF-"):
                raise FetchError(f"{doc['id']}：下载到的不是 PDF（{url}）")
        have = sha256_file(tmp)
        if want is not None and have != want:
            raise FetchError(f"{doc['id']}：SHA-256 与登记的不符（登记 {want}，下载 {have}）；文件可能已更新，"
                             "须重新登记版本并复核")
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)
    return path, have, True


def pin_sha256(text: str, doc_id: str, sha: str) -> str:
    """在 data/sources.yaml 的文本中给文档写上 sha256（保留注释与格式）；已有其他值时报错。"""
    if not _SHA.match(sha):
        raise ValueError("sha256 格式不对")
    lines = text.splitlines(keepends=True)
    for i, ln in enumerate(lines):
        m = re.match(r"^(\s*)- id: " + re.escape(doc_id) + r"\s*$", ln)
        if not m:
            continue
        indent = m.group(1) + "  "
        j = i + 1
        while j < len(lines) and lines[j].startswith(indent) and not lines[j].lstrip().startswith("- "):
            km = re.match(r"^\s*sha256:\s*(\S*)", lines[j])
            if km and lines[j].startswith(indent + "sha256:"):
                if km.group(1) and km.group(1).strip("'\"") != sha:
                    raise ValueError(f"{doc_id} 已登记了不同的 sha256")
                return text
            j += 1
        lines.insert(j, f"{indent}sha256: \"{sha}\"\n")
        out = "".join(lines)
        assert any(d.get("sha256") == sha for d in registered_documents(yaml.safe_load(out)) if d["id"] == doc_id)
        return out
    raise ValueError(f"data/sources.yaml 中没有文档 {doc_id}")


def main(argv: list[str] | None = None) -> int:
    from kb.sources import SourceRegistry

    parser = argparse.ArgumentParser(description="下载 data/sources.yaml 登记的规格书（ADR-0040）")
    parser.add_argument("--doc", action="append", default=[], help="只下载这些文档（可重复；默认全部已核实的）")
    parser.add_argument("--pin", action="store_true", help="把没有登记的 sha256 写回 data/sources.yaml")
    parser.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    parser.add_argument("--sources", type=Path, default=SOURCES_FILE)
    args = parser.parse_args(argv)

    text = args.sources.read_text(encoding="utf-8")
    registry = SourceRegistry.from_dict(yaml.safe_load(text) or {})
    docs = registered_documents(yaml.safe_load(text))
    known = {d["id"] for d in docs}
    unknown = [d for d in args.doc if d not in known]
    if unknown:
        print(f"未登记的文档：{', '.join(unknown)}", file=sys.stderr)
        return 2
    selected = [d for d in docs if not args.doc or d["id"] in args.doc]
    code = 0
    for doc in selected:
        why = registry.check_document(doc["id"])
        if why:
            print(f"跳过 {doc['id']}：{why}")
            continue
        try:
            path, sha, fresh = fetch_document(doc, args.raw_dir)
        except (FetchError, OSError) as exc:
            print(f"失败 {doc['id']}：{exc}", file=sys.stderr)
            code = 1
            continue
        if fresh:
            time.sleep(PAUSE_S)  # 每份之间留出间隔，不给厂商网站造成负担
        print(f"{'下载' if fresh else '已有'} {doc['id']} → {path}（sha256 {sha}）")
        if doc.get("sha256") is None and args.pin:
            text = pin_sha256(text, doc["id"], sha)
            args.sources.write_text(text, encoding="utf-8")
            print(f"  已写入 sha256：{doc['id']}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
