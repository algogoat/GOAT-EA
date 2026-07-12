#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path, PureWindowsPath


TESTER_ORDER = [
    "Expert",
    "Symbol",
    "Period",
    "Model",
    "ExecutionMode",
    "Optimization",
    "OptimizationCriterion",
    "FromDate",
    "ToDate",
    "ForwardMode",
    "Report",
    "ReplaceReport",
    "ShutdownTerminal",
    "Deposit",
    "Currency",
    "Leverage",
    "Visual",
]


def read_text(path: Path) -> str:
    for encoding in ("utf-16", "utf-8-sig", "utf-8", "cp1252"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeError:
            continue
    raise ValueError(f"Unable to decode: {path}")


def split_sections(text: str) -> tuple[list[str], dict[str, list[str]]]:
    preamble: list[str] = []
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for raw in text.splitlines():
        line = raw.rstrip("\r")
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            current = stripped[1:-1]
            sections.setdefault(current, [])
        elif current is None:
            preamble.append(line)
        else:
            sections[current].append(line)
    return preamble, sections


def parse_key_values(lines: list[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith(";") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def render_key_values(values: dict[str, str]) -> list[str]:
    emitted: set[str] = set()
    rendered: list[str] = []
    for key in TESTER_ORDER:
        if key in values:
            rendered.append(f"{key}={values[key]}")
            emitted.add(key)
    for key in sorted(key for key in values if key not in emitted):
        rendered.append(f"{key}={values[key]}")
    return rendered


def extract_input_lines(text: str) -> list[str]:
    preamble, sections = split_sections(text)
    if "TesterInputs" in sections:
        return sections["TesterInputs"]
    return preamble


def schema_input_names(path: Path) -> set[str]:
    document = json.loads(path.read_text(encoding="utf-8-sig"))
    names = {
        field["name"]
        for group in document.get("groups", [])
        for field in group.get("fields", [])
    }
    if not names:
        raise ValueError(f"Input schema contains no fields: {path}")
    return names


def validate_inputs(lines: list[str], allowed: set[str]) -> None:
    seen = 0
    encountered: set[str] = set()
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith(";") or "=" not in line:
            continue
        key = line.split("=", 1)[0].strip()
        if key == "EA_Desc":
            raise ValueError("Legacy EA_Desc is forbidden in a GOAT2 input fixture")
        if not key.startswith("V2_"):
            raise ValueError(f"Non-GOAT2 tester input is forbidden: {key}")
        if key not in allowed:
            raise ValueError(f"Unknown GOAT2 tester input: {key}")
        if key in encountered:
            raise ValueError(f"Duplicate GOAT2 tester input: {key}")
        encountered.add(key)
        seen += 1
    if seen == 0:
        raise ValueError("No V2_ tester inputs were found")


def validate_relative_windows_path(value: str, label: str) -> PureWindowsPath:
    path = PureWindowsPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{label} must be a safe MT5-relative Windows path: {value}")
    return path


def parse_date(value: str, label: str) -> datetime:
    try:
        return datetime.strptime(value, "%Y.%m.%d")
    except ValueError as exc:
        raise ValueError(f"{label} must use YYYY.MM.DD: {value}") from exc


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create a GOAT2 single-test MT5 start config without legacy EA_Desc injection."
    )
    parser.add_argument("--set-file", required=True, type=Path)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--period", default="M1")
    parser.add_argument("--from-date", required=True)
    parser.add_argument("--to-date", required=True)
    parser.add_argument("--output-config", required=True, type=Path)
    parser.add_argument("--expert-relative-path", required=True)
    parser.add_argument("--report-root", required=True)
    parser.add_argument("--template-config", type=Path)
    parser.add_argument(
        "--input-schema",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "v2" / "schema" / "inputs_v2.schema.json",
    )
    parser.add_argument("--model")
    parser.add_argument("--execution-mode")
    parser.add_argument("--deposit")
    parser.add_argument("--currency")
    parser.add_argument("--leverage")
    parser.add_argument("--visual", action="store_true")
    parser.add_argument("--shutdown-terminal", action="store_true")
    args = parser.parse_args()

    if not args.set_file.is_file():
        raise SystemExit(f"Set file not found: {args.set_file}")
    if args.template_config is not None and not args.template_config.is_file():
        raise SystemExit(f"Template config not found: {args.template_config}")
    if not args.input_schema.is_file():
        raise SystemExit(f"Input schema not found: {args.input_schema}")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,80}", args.case_id):
        raise SystemExit("case-id must contain only letters, digits, dot, underscore, and hyphen")

    from_date = parse_date(args.from_date, "from-date")
    to_date = parse_date(args.to_date, "to-date")
    if from_date >= to_date:
        raise SystemExit("from-date must be earlier than to-date")

    expert_path = validate_relative_windows_path(args.expert_relative_path, "expert-relative-path")
    if expert_path.suffix.lower() != ".ex5" or not expert_path.name.upper().startswith("GOAT2"):
        raise SystemExit("expert-relative-path must explicitly target a GOAT2 .ex5")
    report_root = validate_relative_windows_path(args.report_root, "report-root")

    set_text = read_text(args.set_file)
    input_lines = extract_input_lines(set_text)
    validate_inputs(input_lines, schema_input_names(args.input_schema))

    tester = {
        "Expert": str(expert_path),
        "Symbol": args.symbol,
        "Period": args.period,
        "Model": "4",
        "ExecutionMode": "0",
        "Optimization": "0",
        "OptimizationCriterion": "6",
        "FromDate": args.from_date,
        "ToDate": args.to_date,
        "ForwardMode": "0",
        "ReplaceReport": "1",
        "ShutdownTerminal": "0",
        "Deposit": "100000",
        "Currency": "USD",
        "Leverage": "100",
        "Visual": "0",
    }
    if args.template_config is not None:
        _, template_sections = split_sections(read_text(args.template_config))
        tester.update(parse_key_values(template_sections.get("Tester", [])))

    tester.update(
        {
            "Expert": str(expert_path),
            "Symbol": args.symbol,
            "Period": args.period,
            "Optimization": "0",
            "FromDate": args.from_date,
            "ToDate": args.to_date,
            "ForwardMode": "0",
            "ReplaceReport": "1",
            "ShutdownTerminal": "1" if args.shutdown_terminal else "0",
            "Visual": "1" if args.visual else "0",
        }
    )
    for key, value in (
        ("Model", args.model),
        ("ExecutionMode", args.execution_mode),
        ("Deposit", args.deposit),
        ("Currency", args.currency),
        ("Leverage", args.leverage),
    ):
        if value is not None:
            tester[key] = value

    report_name = (
        f"{expert_path.stem} {args.symbol},{args.period} "
        f"{args.from_date}-{args.to_date}.xml"
    )
    report_path = report_root / args.case_id / args.symbol / report_name
    tester["Report"] = str(report_path)

    rendered = [
        f";GOAT2 case={args.case_id} input_sha256={sha256(args.set_file)}",
        "[Tester]",
        *render_key_values(tester),
        "[TesterInputs]",
        *[line.rstrip("\r") for line in input_lines],
    ]
    args.output_config.parent.mkdir(parents=True, exist_ok=True)
    args.output_config.write_text(
        "\n".join(rendered) + "\n", encoding="utf-8", newline="\r\n"
    )

    print(f"Config: {args.output_config}")
    print(f"Case: {args.case_id}")
    print(f"Expert: {expert_path}")
    print(f"Report: {report_path}")
    print(f"Input SHA256: {sha256(args.set_file)}")
    print(f"Config SHA256: {sha256(args.output_config)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as exc:
        raise SystemExit(f"ERROR: {exc}") from exc
