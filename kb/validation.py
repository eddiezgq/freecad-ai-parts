"""用 schema/ 中的 JSON Schema 校验数据。"""

from __future__ import annotations

import json
from functools import cache, lru_cache
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schema"
ID_BASE = "https://github.com/eddiezgq/freecad-ai-parts/schema/"


@lru_cache(maxsize=1)
def _registry() -> Registry:
    resources = []
    for path in SCHEMA_DIR.rglob("*.schema.json"):
        schema = json.loads(path.read_text(encoding="utf-8"))
        resources.append((schema["$id"], Resource.from_contents(schema)))
    return Registry().with_resources(resources)


@cache
def validator(relative_id: str) -> Draft202012Validator:
    """返回指定 schema 的校验器，例如 validator("component.schema.json")。"""
    registry = _registry()
    return Draft202012Validator(registry.contents(ID_BASE + relative_id), registry=registry)


def errors(relative_id: str, instance: object) -> list[str]:
    """返回校验错误（路径: 信息），无错误时为空列表。"""
    out = []
    for e in validator(relative_id).iter_errors(instance):
        path = "/".join(str(p) for p in e.absolute_path) or "<root>"
        out.append(f"{path}: {e.message}")
    return out


@cache
def validator_for_ref(ref: str) -> Draft202012Validator:
    """按完整 URI（可带 JSON Pointer 片段）取子 schema 的校验器，例如某个品类参数的参数值 schema。"""
    return Draft202012Validator({"$ref": ref}, registry=_registry())
