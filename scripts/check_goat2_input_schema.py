#!/usr/bin/env python3
"""Fail when the GOAT2 MQL input surface and committed schema diverge."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DECLARATIONS = ROOT / "v2" / "Inputs_V2.mqh"
SCHEMA = ROOT / "v2" / "schema" / "inputs_v2.schema.json"
INPUT_RE = re.compile(
    r"^\s*input\s+(?!group\b)(?P<type>\S+)\s+(?P<name>V2_[A-Za-z0-9_]+)\s*=\s*(?P<default>[^;]+);",
    re.MULTILINE,
)


def duplicates(values: list[str]) -> list[str]:
    return sorted({value for value in values if values.count(value) > 1})


def schema_type(mql_type: str) -> str:
    if mql_type == "bool":
        return "bool"
    if mql_type in {"int", "long"}:
        return "int"
    if mql_type in {"double", "float"}:
        return "double"
    if mql_type == "string":
        return "string"
    if mql_type == "ENUM_TIMEFRAMES":
        return "timeframe"
    if mql_type.startswith("ENUM_"):
        return "enum"
    return mql_type


def normalized_token(value: object) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", str(value)).upper()


def default_matches(raw: str, expected: object, field_type: str) -> bool:
    raw = raw.strip()
    if field_type == "string":
        return raw.startswith('"') and raw.endswith('"') and raw[1:-1] == expected
    if field_type == "bool":
        return raw.lower() == str(expected).lower()
    if field_type in {"int", "double"}:
        try:
            return float(raw) == float(expected)
        except ValueError:
            return False
    return normalized_token(raw).endswith(normalized_token(expected))


def main() -> int:
    declarations = [match.groupdict() for match in INPUT_RE.finditer(DECLARATIONS.read_text(encoding="utf-8-sig"))]
    declaration_names = [item["name"] for item in declarations]
    document = json.loads(SCHEMA.read_text(encoding="utf-8-sig"))
    fields = [
        field
        for group in document.get("groups", [])
        for field in group.get("fields", [])
    ]
    schema_fields = [field["name"] for field in fields]
    fields_by_name = {field["name"]: field for field in fields}

    errors: list[str] = []
    if duplicates(declaration_names):
        errors.append(f"duplicate declarations: {', '.join(duplicates(declaration_names))}")
    if duplicates(schema_fields):
        errors.append(f"duplicate schema fields: {', '.join(duplicates(schema_fields))}")

    missing = sorted(set(declaration_names) - set(schema_fields))
    extra = sorted(set(schema_fields) - set(declaration_names))
    if missing:
        errors.append(f"missing from schema: {', '.join(missing)}")
    if extra:
        errors.append(f"not declared in MQL: {', '.join(extra)}")

    for declaration in declarations:
        field = fields_by_name.get(declaration["name"])
        if field is None:
            continue
        actual_type = schema_type(declaration["type"])
        if actual_type != field.get("type"):
            errors.append(
                f"type mismatch {declaration['name']}: MQL={actual_type} schema={field.get('type')}"
            )
        if "default" in field and not default_matches(
            declaration["default"], field["default"], actual_type
        ):
            errors.append(
                f"default mismatch {declaration['name']}: MQL={declaration['default'].strip()} schema={field['default']}"
            )

    if errors:
        print("GOAT2_INPUT_SCHEMA_CHECK=FAIL")
        for error in errors:
            print(f"ERROR={error}")
        return 1

    print("GOAT2_INPUT_SCHEMA_CHECK=PASS")
    print(f"DECLARATIONS={len(declaration_names)}")
    print(f"SCHEMA_FIELDS={len(schema_fields)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
