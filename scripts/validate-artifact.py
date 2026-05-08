#!/usr/bin/env python3
"""
validate-artifact — check a run artifact against its JSON Schema.

Used at three points in the pipeline:
  1. Strategist after writing 03-spec-<unit>.json
  2. Executor before announcing it's done writing result.json + trace.jsonl
  3. Reporter before reading result.json (defensive)

Usage:
  scripts/validate-artifact.py --kind result --path artifacts/<run-id>/04-run-<unit>/result.json
  scripts/validate-artifact.py --kind trace  --path artifacts/<run-id>/04-run-<unit>/trace.jsonl
  scripts/validate-artifact.py --kind spec   --path artifacts/<run-id>/03-spec-<unit>.json

Exit codes:
  0  the artifact conforms
  1  schema violation (stderr lists each error)
  2  bad arguments / missing schema or file

Implementation note:
  We use a small home-grown JSON-Schema subset rather than depending on the
  third-party `jsonschema` package. The subset is enough for the schemas in
  schemas/: type, required, additionalProperties, enum, pattern, oneOf,
  allOf, if/then, properties, items, format=date-time, minLength,
  minItems, minimum, const. If a schema later needs $ref or more advanced
  features, swap this for `pip install jsonschema` and use Draft7Validator.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = REPO_ROOT / "schemas"


# ---------------------------------------------------------------------------
# JSON-Schema subset validator
# ---------------------------------------------------------------------------

class Err:
    __slots__ = ("path", "msg")

    def __init__(self, path: str, msg: str) -> None:
        self.path = path
        self.msg = msg

    def __str__(self) -> str:
        return f"{self.path or '<root>'}: {self.msg}"


JSON_TYPE_NAME = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
    type(None): "null",
}


def _type_of(v: Any) -> str:
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, int):
        return "integer"
    if isinstance(v, float):
        return "number"
    if isinstance(v, str):
        return "string"
    if isinstance(v, list):
        return "array"
    if isinstance(v, dict):
        return "object"
    if v is None:
        return "null"
    return "unknown"


def _check_type(value: Any, expected: str) -> bool:
    t = _type_of(value)
    if expected == "number":
        return t in ("integer", "number")
    return t == expected


def validate(value: Any, schema: dict, path: str = "") -> list[Err]:
    errs: list[Err] = []

    # type
    if "type" in schema:
        expected = schema["type"]
        types = expected if isinstance(expected, list) else [expected]
        if not any(_check_type(value, t) for t in types):
            errs.append(Err(path, f"expected type {types!r}, got {_type_of(value)!r}"))
            return errs  # subsequent checks won't make sense

    # enum
    if "enum" in schema and value not in schema["enum"]:
        errs.append(Err(path, f"value {value!r} not in enum {schema['enum']!r}"))

    # const
    if "const" in schema and value != schema["const"]:
        errs.append(Err(path, f"value {value!r} != const {schema['const']!r}"))

    # string constraints
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errs.append(Err(path, f"string length {len(value)} < minLength {schema['minLength']}"))
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errs.append(Err(path, f"string {value!r} does not match pattern {schema['pattern']!r}"))
        if schema.get("format") == "date-time":
            try:
                # Python <3.11 doesn't accept trailing 'Z' — normalise.
                datetime.fromisoformat(value.replace("Z", "+00:00"))
            except Exception:
                errs.append(Err(path, f"string {value!r} is not ISO-8601 date-time"))

    # number constraints
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errs.append(Err(path, f"value {value} < minimum {schema['minimum']}"))

    # array constraints
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errs.append(Err(path, f"array length {len(value)} < minItems {schema['minItems']}"))
        if "items" in schema:
            for i, item in enumerate(value):
                errs.extend(validate(item, schema["items"], f"{path}[{i}]"))

    # object constraints
    if isinstance(value, dict):
        if "required" in schema:
            for k in schema["required"]:
                if k not in value:
                    errs.append(Err(path, f"required property '{k}' is missing"))
        if "properties" in schema:
            props = schema["properties"]
            for k, v in value.items():
                if k in props:
                    errs.extend(validate(v, props[k], _join(path, k)))
        if schema.get("additionalProperties") is False and "properties" in schema:
            allowed = set(schema["properties"].keys())
            for k in value.keys():
                if k not in allowed:
                    errs.append(Err(path, f"unknown property '{k}' (additionalProperties=false)"))

    # combinators
    if "oneOf" in schema:
        matches = sum(1 for s in schema["oneOf"] if not validate(value, s, path))
        if matches != 1:
            errs.append(Err(path, f"oneOf matched {matches} subschemas (expected 1)"))

    if "allOf" in schema:
        for sub in schema["allOf"]:
            errs.extend(validate(value, sub, path))

    if "if" in schema:
        if not validate(value, schema["if"], path):
            if "then" in schema:
                errs.extend(validate(value, schema["then"], path))
        else:
            if "else" in schema:
                errs.extend(validate(value, schema["else"], path))

    return errs


def _join(parent: str, key: str) -> str:
    return f"{parent}.{key}" if parent else key


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def load_schema(kind: str) -> dict:
    name = {
        "result": "run-result.schema.json",
        "trace": "run-trace.schema.json",
        "spec": "run-spec.schema.json",
    }.get(kind)
    if not name:
        die(2, f"unknown --kind {kind!r} (expected: result | trace | spec)")
    path = SCHEMA_DIR / name
    if not path.exists():
        die(2, f"schema not found: {path}")
    return json.loads(path.read_text())


def load_artifact(kind: str, path: Path) -> Any:
    if not path.exists():
        die(2, f"artifact not found: {path}")
    raw = path.read_text()
    if kind == "trace":
        # JSONL — return list of dicts plus track which line each came from
        rows = []
        for i, line in enumerate(raw.splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append((i, json.loads(line)))
            except json.JSONDecodeError as e:
                die(1, f"trace line {i} is not valid JSON: {e}")
        return rows
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        die(1, f"{path} is not valid JSON: {e}")


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------

def die(code: int, msg: str) -> None:
    print(f"validate-artifact: {msg}", file=sys.stderr)
    sys.exit(code)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--kind", required=True, choices=["result", "trace", "spec"])
    p.add_argument("--path", required=True, type=Path)
    p.add_argument("--quiet", action="store_true", help="suppress success message")
    args = p.parse_args()

    schema = load_schema(args.kind)

    if args.kind == "trace":
        rows: Iterable = load_artifact("trace", args.path)
        all_errs: list[str] = []
        for line_no, obj in rows:
            errs = validate(obj, schema)
            for e in errs:
                all_errs.append(f"line {line_no}: {e}")
        if all_errs:
            for e in all_errs:
                print(e, file=sys.stderr)
            die(1, f"{args.path}: {len(all_errs)} validation error(s)")
    else:
        obj = load_artifact(args.kind, args.path)
        errs = validate(obj, schema)
        if errs:
            for e in errs:
                print(str(e), file=sys.stderr)
            die(1, f"{args.path}: {len(errs)} validation error(s)")

    if not args.quiet:
        print(f"ok {args.path}")
    sys.exit(0)


if __name__ == "__main__":
    main()
