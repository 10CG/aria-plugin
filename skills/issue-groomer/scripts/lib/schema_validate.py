"""groom-report schema 结构校验器 (draft 2020-12 受限子集, stdlib-only)。

依赖方向 (B.3 修复轮修正): 校验实现住**生产层** (本模块), 两类消费方同源
import — ``groom.py`` 出厂自校验 (``_mini_validate``) 与 ``tests/
test_schema.py`` 断言面。此前实现住在 tests/test_schema.py、生产侧经
importlib 直载测试文件并在缺 pytest 的环境注入 stub — 生产代码依赖测试
环境属依赖方向倒置 (pytest 毒井), 本模块即其修正落点。

支持的关键字子集与语义与原实现逐字一致 (TASK-003 SC-8 验收面原样迁移,
零行为变化 — 已有断言全部继续成立): ``$ref`` (internal) / ``type``
(string or list) / ``required`` / ``properties`` / ``additionalProperties``
(bool or schema) / ``items`` / ``enum`` / ``const`` / ``pattern``
(re.search, per spec) / ``minLength`` / ``minimum`` / ``minItems`` /
``maxItems``。``format`` 在 2020-12 是 annotation-only, 有意不校验。
"""

from __future__ import annotations

import re
from typing import Any

__all__ = ["mini_validate"]


def _resolve_pointer(root: dict[str, Any], ref: str) -> Any:
    """Resolve an internal JSON pointer like '#/$defs/IssueEntry'."""
    if not ref.startswith("#/"):
        raise AssertionError(f"mini_validate: only internal $ref supported, got {ref!r}")
    node: Any = root
    for raw in ref[2:].split("/"):
        part = raw.replace("~1", "/").replace("~0", "~")
        node = node[part]
    return node


def _type_matches(value: Any, expected: str) -> bool:
    """draft 2020-12 type semantics; bool is NOT an integer (Python quirk)."""
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    raise AssertionError(f"mini_validate: unknown type keyword {expected!r}")


def mini_validate(
    instance: Any,
    schema: dict[str, Any],
    root: dict[str, Any] | None = None,
    path: str = "$",
    errors: list[str] | None = None,
) -> list[str]:
    """Validate `instance` against a draft 2020-12 subset schema.

    Supported keywords: $ref (internal), type (string or list), required,
    properties, additionalProperties (bool or schema), items, enum, const,
    pattern (re.search semantics, per spec), minLength, minimum, minItems,
    maxItems. `format` is annotation-only in 2020-12 and intentionally not
    checked. Returns a list of human-readable error strings (empty = valid).
    """
    if errors is None:
        errors = []
        root = schema if root is None else root
    assert root is not None

    if "$ref" in schema:
        return mini_validate(
            instance, _resolve_pointer(root, schema["$ref"]), root, path, errors
        )

    if "type" in schema:
        expected = schema["type"]
        candidates = expected if isinstance(expected, list) else [expected]
        if not any(_type_matches(instance, t) for t in candidates):
            errors.append(
                f"{path}: expected type {expected!r}, got {type(instance).__name__}"
            )
            return errors  # type mismatch invalidates keyword application below

    if "const" in schema and instance != schema["const"]:
        errors.append(f"{path}: {instance!r} != const {schema['const']!r}")
    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}: {instance!r} not in enum {schema['enum']!r}")

    if isinstance(instance, str):
        if "pattern" in schema and re.search(schema["pattern"], instance) is None:
            errors.append(f"{path}: {instance!r} fails pattern {schema['pattern']!r}")
        if "minLength" in schema and len(instance) < schema["minLength"]:
            errors.append(f"{path}: length {len(instance)} < minLength {schema['minLength']}")

    if isinstance(instance, int) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            errors.append(f"{path}: {instance} < minimum {schema['minimum']}")

    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            errors.append(f"{path}: {len(instance)} items < minItems {schema['minItems']}")
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            errors.append(f"{path}: {len(instance)} items > maxItems {schema['maxItems']}")
        if "items" in schema:
            for i, item in enumerate(instance):
                mini_validate(item, schema["items"], root, f"{path}[{i}]", errors)

    if isinstance(instance, dict):
        for key in schema.get("required", []):
            if key not in instance:
                errors.append(f"{path}: missing required property {key!r}")
        properties = schema.get("properties", {})
        additional = schema.get("additionalProperties", True)
        for key, value in instance.items():
            child = f"{path}.{key}"
            if key in properties:
                mini_validate(value, properties[key], root, child, errors)
            elif additional is False:
                errors.append(
                    f"{child}: additional property {key!r} not allowed (closed keyset)"
                )
            elif isinstance(additional, dict):
                mini_validate(value, additional, root, child, errors)

    return errors
