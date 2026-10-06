"""企业私有库（ADR-0055）：企业自选的文件夹，叠加在公共库上；写入与公共库同规则。

结构：
- components/<品类>/<组件 id>.json：完整组件（component.schema.json）
- sources.yaml：企业登记的资料（id 以 src-ent- 开头）
- docs/：规格书原件，只在企业那边
- history.jsonl：每次写入一行

规则：写入前按 schema 校验，不合格不写；新值须有依据（企业资料 id + 页码 + 原文，或人工录入并注明录入人），
不编造、缺数据就不写；只写本目录。
"""

from __future__ import annotations

import copy
import datetime
import hashlib
import json
import re
import shutil
from collections.abc import Callable
from pathlib import Path

import yaml

from kb.validation import errors as schema_errors

DOC_PREFIX = "src-ent-"
_SLUG = re.compile(r"[^a-z0-9]+")


class EnterpriseError(ValueError):
    """不能写入企业库；消息说明原因。"""


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")


def _slug(text: str) -> str:
    s = _SLUG.sub("-", text.lower()).strip("-")
    return s or "doc"


class EnterpriseLibrary:
    def __init__(self, directory: str | Path, create: bool = False):
        self.directory = Path(directory)
        if create:
            for sub in ("components", "docs"):
                (self.directory / sub).mkdir(parents=True, exist_ok=True)
        if not (self.directory / "components").is_dir():
            raise FileNotFoundError(f"不是企业库目录（缺 components/）：{self.directory}")
        self._load()

    # ------------------------------------------------------------ 读

    def _load(self) -> None:
        self._comps: dict[str, dict] = {}
        self._paths: dict[str, Path] = {}
        for path in sorted((self.directory / "components").rglob("*.json")):
            comp = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(comp, dict) or "id" not in comp:
                continue
            if comp["id"] in self._comps:
                raise ValueError(f"企业库中组件 id 重复：{comp['id']}（{path}）")
            self._comps[comp["id"]] = comp
            self._paths[comp["id"]] = path

    def get(self, cid: str) -> dict | None:
        return self._comps.get(cid)

    def all(self, category: str | None = None) -> list[dict]:
        return [c for _, c in sorted(self._comps.items()) if category is None or c["category"] == category]

    def documents(self) -> list[dict]:
        path = self.directory / "sources.yaml"
        if not path.is_file():
            return []
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return list(data.get("documents") or [])

    def document(self, doc_id: str) -> dict | None:
        return next((d for d in self.documents() if d.get("id") == doc_id), None)

    def history(self) -> list[dict]:
        path = self.directory / "history.jsonl"
        if not path.is_file():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    # ------------------------------------------------------------ 写

    def _log(self, entry: dict) -> None:
        with (self.directory / "history.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({"time": _now(), **entry}, ensure_ascii=False, sort_keys=True) + "\n")

    def register_document(self, file: str | Path, title: str, actor: str) -> dict:
        """登记一份企业资料：复制到 docs/，记 SHA-256；同一文件（哈希相同）不重复登记。"""
        src = Path(file)
        if not src.is_file():
            raise EnterpriseError(f"文件不存在：{src}")
        if not title.strip() or not actor.strip():
            raise EnterpriseError("登记资料须写明标题与登记人")
        digest = hashlib.sha256(src.read_bytes()).hexdigest()
        docs = self.documents()
        same = next((d for d in docs if d.get("sha256") == digest), None)
        if same is not None:
            return same
        base = DOC_PREFIX + _slug(Path(title).stem if "." in title else title)[:40].strip("-")
        doc_id, n = base, 2
        while any(d.get("id") == doc_id for d in docs):
            doc_id, n = f"{base}-{n}", n + 1
        target = self.directory / "docs" / f"{doc_id}{src.suffix.lower()}"
        shutil.copyfile(src, target)
        entry = {"id": doc_id, "title": title.strip(), "file": target.name, "sha256": digest, "added_by": actor.strip(),
                 "date": datetime.datetime.now().astimezone().date().isoformat()}
        docs.append(entry)
        (self.directory / "sources.yaml").write_text(
            yaml.safe_dump({"documents": docs}, allow_unicode=True, sort_keys=False), encoding="utf-8")
        self._log({"action": "register_document", "actor": actor.strip(), "doc": doc_id, "title": title.strip()})
        return entry

    def save_component(self, comp: dict, actor: str, note: str) -> Path:
        """写入（新增或覆盖）一个完整组件。schema 不合格、来源资料未登记时不写。"""
        if not actor.strip() or not note.strip():
            raise EnterpriseError("写入须写明操作人与说明")
        errs = schema_errors("component.schema.json", comp)
        if errs:
            raise EnterpriseError("组件不符合 schema：" + "；".join(errs[:5]))
        for doc in sorted(_docs_of(comp)):
            if doc.startswith(DOC_PREFIX) and self.document(doc) is None:
                raise EnterpriseError(f"来源资料 {doc} 未在企业库登记")
        cid = comp["id"]
        old = self._comps.get(cid)
        path = self._paths.get(cid) or self.directory / "components" / comp["category"] / f"{cid}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(comp, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        self._comps[cid], self._paths[cid] = copy.deepcopy(comp), path
        self._log({"action": "save_component", "actor": actor.strip(), "component": cid, "note": note.strip(),
                   "new": old is None})
        return path

    def set_value(self, cid: str, target: str, pv: dict, actor: str, base: Callable[[str], dict | None]) -> dict:
        """在组件的一个字段写入参数值（ADR-0055 第 4 条）。target 为 params/<名> 或 ports/<端口>/<名>。
        组件不在企业库时，先从公共库复制一份；参数值须有依据：企业资料（已登记）+ 页码 + 原文，或人工录入并注明录入人。"""
        _require_basis(pv, self)
        comp = copy.deepcopy(self._comps.get(cid) or base(cid))
        if comp is None:
            raise EnterpriseError(f"组件不存在：{cid}")
        parts = target.split("/")
        if len(parts) == 2 and parts[0] == "params":
            holder = comp.setdefault("params", {})
        elif len(parts) == 3 and parts[0] == "ports":
            port = next((p for p in comp.get("ports", []) if p["id"] == parts[1]), None)
            if port is None:
                raise EnterpriseError(f"{cid} 没有端口 {parts[1]}")
            holder = port.setdefault("spec", {})
        else:
            raise EnterpriseError(f"字段须写成 params/<名> 或 ports/<端口>/<名>：{target}")
        old = holder.get(parts[-1])
        holder[parts[-1]] = pv
        self.save_component(comp, actor, f"补数据 {target}")
        self._log({"action": "set_value", "actor": actor.strip(), "component": cid, "target": target, "old": old,
                   "new": pv})
        return comp


def _docs_of(node) -> set[str]:
    out: set[str] = set()
    if isinstance(node, dict):
        src = node.get("source")
        if isinstance(src, dict) and isinstance(src.get("doc"), str):
            out.add(src["doc"])
        for v in node.values():
            out |= _docs_of(v)
    elif isinstance(node, list):
        for v in node:
            out |= _docs_of(v)
    return out


def _require_basis(pv: dict, lib: EnterpriseLibrary) -> None:
    src = pv.get("source") if isinstance(pv, dict) else None
    if not isinstance(src, dict):
        raise EnterpriseError("参数值须有来源")
    method = pv.get("method")
    if method == "computed":
        if not src.get("formula"):
            raise EnterpriseError("计算值须写明公式")
        return
    doc = src.get("doc")
    if not doc:
        raise EnterpriseError("参数值须注明来源资料")
    if doc.startswith(DOC_PREFIX):
        if lib.document(doc) is None:
            raise EnterpriseError(f"来源资料 {doc} 未在企业库登记")
        if src.get("page") is None or not (src.get("note") or "").strip():
            raise EnterpriseError("引用企业资料须写页码与原文")
    if method == "manual" and "录入人" not in (src.get("note") or "") and "确认人" not in (src.get("note") or ""):
        raise EnterpriseError("人工录入须在来源说明中写明录入人或确认人")
