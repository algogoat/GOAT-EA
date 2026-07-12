#!/usr/bin/env python3
"""Generate or verify GOAT2's marker-bounded MQL input declaration block.

The JSON schema is authoritative for declaration groups, order, MQL types,
defaults, comments, and enum-token metadata. Enums and validation helpers stay
hand-written outside the generated region in Inputs_V2.mqh.
"""

from __future__ import annotations

import argparse
import codecs
import difflib
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "v2" / "schema" / "inputs_v2.schema.json"
TARGET_PATH = ROOT / "v2" / "Inputs_V2.mqh"
OPERATION_MODE_PATH = ROOT / "v2" / "OperationMode.mqh"
SCALAR_MQL_TYPES = {
    "bool": "bool",
    "int": "int",
    "double": "double",
    "string": "string",
    "timeframe": "ENUM_TIMEFRAMES",
}


class GenerationError(RuntimeError):
    """The schema or target cannot be generated deterministically."""


def load_document() -> dict[str, Any]:
    try:
        document = json.loads(SCHEMA_PATH.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GenerationError(f"cannot read schema: {exc}") from exc
    if document.get("sourceOfTruth") is not True:
        raise GenerationError("schema must declare sourceOfTruth=true")
    if document.get("declarationArtifact") != "v2/Inputs_V2.mqh":
        raise GenerationError("declarationArtifact must be v2/Inputs_V2.mqh")
    generation = document.get("generation")
    if not isinstance(generation, dict):
        raise GenerationError("generation metadata is missing")
    if generation.get("generator") != "scripts/generate_goat2_inputs.py":
        raise GenerationError("generation.generator does not identify this tool")
    for key in ("beginMarker", "endMarker"):
        marker = generation.get(key)
        if (
            not isinstance(marker, str)
            or not marker.startswith("// ")
            or "\r" in marker
            or "\n" in marker
        ):
            raise GenerationError(f"generation.{key} is missing or invalid")
    if generation["beginMarker"] == generation["endMarker"]:
        raise GenerationError("generated-region markers must be distinct")
    if generation.get("schemaHashAlgorithm") != "SHA-256" or generation.get(
        "schemaHashMaterial"
    ) != "exact schema artifact bytes":
        raise GenerationError("schema hash provenance metadata is missing or unsupported")
    return document


def ordered(items: list[dict[str, Any]], context: str) -> list[dict[str, Any]]:
    orders: list[int] = []
    for item in items:
        value = item.get("order")
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise GenerationError(f"{context} has a missing/invalid positive integer order")
        orders.append(value)
    if len(orders) != len(set(orders)):
        raise GenerationError(f"{context} contains duplicate order values")
    return sorted(items, key=lambda item: item["order"])


def validate_default(field: dict[str, Any]) -> None:
    name = field["name"]
    field_type = field["type"]
    raw = field["mqlDefault"]
    expected = field["default"]
    try:
        if field_type == "string":
            actual = json.loads(raw)
            matches = isinstance(actual, str) and actual == expected
        elif field_type == "bool":
            matches = raw in {"true", "false"} and (raw == str(expected).lower())
        elif field_type == "int":
            matches = int(raw) == expected and not isinstance(expected, bool)
        elif field_type == "double":
            matches = float(raw) == float(expected)
        elif field_type in {"enum", "timeframe"}:
            matches = raw == expected
        else:
            matches = False
    except (TypeError, ValueError, json.JSONDecodeError):
        matches = False
    if not matches:
        raise GenerationError(
            f"{name} default mismatch: default={expected!r}, mqlDefault={raw!r}"
        )


def schema_groups(document: dict[str, Any]) -> list[dict[str, Any]]:
    groups = document.get("groups")
    if not isinstance(groups, list) or not groups:
        raise GenerationError("schema groups must be a non-empty list")
    groups = ordered(groups, "groups")
    group_names: set[str] = set()
    group_labels: set[str] = set()
    field_names: set[str] = set()
    for group in groups:
        name = group.get("name")
        label = group.get("label")
        if not isinstance(name, str) or not name:
            raise GenerationError("group name is missing")
        if (
            not isinstance(label, str)
            or not label
            or '"' in label
            or "\r" in label
            or "\n" in label
        ):
            raise GenerationError(f"{name} label is missing or not MQL-safe")
        if name in group_names or label in group_labels:
            raise GenerationError(f"duplicate group name or label: {name}")
        group_names.add(name)
        group_labels.add(label)
        fields = group.get("fields")
        if not isinstance(fields, list) or not fields:
            raise GenerationError(f"{name} fields must be a non-empty list")
        group["fields"] = ordered(fields, f"fields in {name}")
        for field in group["fields"]:
            field_name = field.get("name")
            if not isinstance(field_name, str) or not re.fullmatch(r"V2_[A-Za-z0-9_]+", field_name):
                raise GenerationError(f"{name} contains an invalid field name")
            if field_name in field_names:
                raise GenerationError(f"duplicate field name: {field_name}")
            field_names.add(field_name)
            if field.get("group") != name:
                raise GenerationError(f"{field_name} group metadata does not match {name}")
            if not isinstance(field.get("mqlType"), str) or not re.fullmatch(
                r"[A-Za-z_][A-Za-z0-9_]*", field["mqlType"]
            ):
                raise GenerationError(f"{field_name} mqlType is missing or invalid")
            if (
                not isinstance(field.get("mqlDefault"), str)
                or "\r" in field["mqlDefault"]
                or "\n" in field["mqlDefault"]
                or "default" not in field
            ):
                raise GenerationError(f"{field_name} default metadata is incomplete")
            expected_mql_type = SCALAR_MQL_TYPES.get(field.get("type"))
            if expected_mql_type is not None and field["mqlType"] != expected_mql_type:
                raise GenerationError(
                    f"{field_name} type/mqlType mismatch: "
                    f"{field.get('type')}/{field['mqlType']}"
                )
            if field.get("type") == "enum":
                enum_type = field.get("enumType")
                values = field.get("values")
                if enum_type != field["mqlType"] or not isinstance(values, list) or not values:
                    raise GenerationError(f"{field_name} enum metadata is incomplete")
                if len(values) != len(set(values)) or field["mqlDefault"] not in values:
                    raise GenerationError(f"{field_name} enum values/default are inconsistent")
            if "mqlComment" in field and (
                not isinstance(field["mqlComment"], str)
                or not field["mqlComment"]
                or "\r" in field["mqlComment"]
                or "\n" in field["mqlComment"]
            ):
                raise GenerationError(f"{field_name} mqlComment is invalid")
            validate_default(field)
    return groups


def parse_enum_contracts(text: str) -> dict[str, tuple[list[str], list[int]]]:
    definitions: dict[str, tuple[list[str], list[int]]] = {}
    pattern = re.compile(r"enum\s+(ENUM_V2_[A-Z0-9_]+)\s*\{([^}]*)\}", re.DOTALL)
    for match in pattern.finditer(text):
        tokens: list[str] = []
        numeric_values: list[int] = []
        current_value = -1
        body = re.sub(r"//[^\r\n]*", "", match.group(2))
        for part in body.split(","):
            clean = part.strip()
            if clean:
                pieces = clean.split("=", 1)
                tokens.append(pieces[0].strip())
                if len(pieces) == 2:
                    try:
                        current_value = int(pieces[1].strip(), 0)
                    except ValueError as exc:
                        raise GenerationError(
                            f"{match.group(1)} uses a non-literal numeric enum value"
                        ) from exc
                else:
                    current_value += 1
                numeric_values.append(current_value)
        definitions[match.group(1)] = (tokens, numeric_values)
    return definitions


def validate_enum_contract(groups: list[dict[str, Any]], target_text: str) -> None:
    try:
        operation_text = OPERATION_MODE_PATH.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise GenerationError(f"cannot read operation-mode enum: {exc}") from exc
    definitions = parse_enum_contracts(operation_text + "\n" + target_text)
    for group in groups:
        for field in group["fields"]:
            enum_type = field.get("enumType", "")
            if not enum_type.startswith("ENUM_V2_"):
                continue
            actual = definitions.get(enum_type)
            if actual is None:
                raise GenerationError(f"{field['name']} enum {enum_type} is not declared")
            actual_tokens, actual_values = actual
            if actual_tokens != field["values"]:
                raise GenerationError(
                    f"{field['name']} enum tokens differ: schema={field['values']}, MQL={actual_tokens}"
                )
            expected_values = list(range(len(field["values"])))
            if actual_values != expected_values:
                raise GenerationError(
                    f"{field['name']} enum numeric map differs: "
                    f"expected={expected_values}, MQL={actual_values}"
                )


def render_region(document: dict[str, Any], groups: list[dict[str, Any]]) -> str:
    generation = document["generation"]
    begin = generation["beginMarker"]
    end = generation["endMarker"]
    type_width = generation["typeColumnWidth"]
    comment_column = generation["commentColumn"]
    if not isinstance(type_width, int) or type_width < 1:
        raise GenerationError("typeColumnWidth must be a positive integer")
    if not isinstance(comment_column, int) or comment_column < 1:
        raise GenerationError("commentColumn must be a positive integer")
    lines = [
        begin,
        "// Generated by scripts/generate_goat2_inputs.py. Do not edit this region by hand.",
        f"// Schema: v2/schema/inputs_v2.schema.json ({document['schemaVersion']})",
        f"// Schema SHA-256: {hashlib.sha256(SCHEMA_PATH.read_bytes()).hexdigest().upper()}",
        "",
    ]
    for group_index, group in enumerate(groups):
        if group_index:
            lines.append("")
        lines.append(f'input group "{group["label"]}"')
        for field in group["fields"]:
            line = (
                f"input {field['mqlType']:<{type_width}}"
                f"{field['name']}={field['mqlDefault']};"
            )
            comment = field.get("mqlComment")
            if comment:
                line += " " * max(1, comment_column - len(line)) + f"// {comment}"
            lines.append(line)
    lines.append(end)
    return "\n".join(lines)


def replace_region(text: str, begin: str, end: str, rendered: str) -> str:
    lines = text.splitlines()
    if lines.count(begin) != 1 or lines.count(end) != 1:
        raise GenerationError("target must contain exactly one configured marker pair")
    start = lines.index(begin)
    finish = lines.index(end)
    if finish <= start:
        raise GenerationError("generated-region markers are reversed")
    output = lines[:start] + rendered.splitlines() + lines[finish + 1 :]
    return "\n".join(output) + "\n"


def canonical_mql_bytes(text: str) -> bytes:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return codecs.BOM_UTF8 + normalized.replace("\n", "\r\n").encode("utf-8")


def expected_output(document: dict[str, Any]) -> tuple[bytes, str]:
    try:
        raw = TARGET_PATH.read_bytes()
        target_text = raw.decode("utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        raise GenerationError(f"cannot read target: {exc}") from exc
    groups = schema_groups(document)
    validate_enum_contract(groups, target_text)
    generation = document["generation"]
    rendered = render_region(document, groups)
    replaced = replace_region(
        target_text,
        generation["beginMarker"],
        generation["endMarker"],
        rendered,
    )
    return canonical_mql_bytes(replaced), replaced


def show_diff(actual: bytes, expected_text: str) -> None:
    try:
        actual_text = actual.decode("utf-8-sig")
    except UnicodeDecodeError:
        print("ERROR=target is not valid UTF-8")
        return
    diff = difflib.unified_diff(
        actual_text.splitlines(),
        expected_text.splitlines(),
        fromfile="v2/Inputs_V2.mqh (actual)",
        tofile="v2/Inputs_V2.mqh (generated)",
        lineterm="",
    )
    for line in diff:
        print(line)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check",
        action="store_true",
        help="verify declarations and UTF-8 BOM + CRLF without writing (default)",
    )
    mode.add_argument(
        "--write",
        action="store_true",
        help="replace only the configured generated region and enforce UTF-8 BOM + CRLF",
    )
    args = parser.parse_args()
    try:
        document = load_document()
        expected, expected_text = expected_output(document)
        actual = TARGET_PATH.read_bytes()
        if args.write:
            if actual != expected:
                TARGET_PATH.write_bytes(expected)
                print("GOAT2_INPUT_GENERATION=WRITTEN")
            else:
                print("GOAT2_INPUT_GENERATION=UNCHANGED")
            actual = TARGET_PATH.read_bytes()
        if actual != expected:
            print("GOAT2_INPUT_GENERATION=FAIL")
            print("ERROR=generated declarations or UTF-8 BOM/CRLF encoding are stale")
            show_diff(actual, expected_text)
            print("REMEDY=python scripts/generate_goat2_inputs.py --write")
            return 1
        print("GOAT2_INPUT_GENERATION=PASS")
        print(f"SCHEMA={SCHEMA_PATH.relative_to(ROOT).as_posix()}")
        print(f"TARGET={TARGET_PATH.relative_to(ROOT).as_posix()}")
        return 0
    except GenerationError as exc:
        print("GOAT2_INPUT_GENERATION=FAIL")
        print(f"ERROR={exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
