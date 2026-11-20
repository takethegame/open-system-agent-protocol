# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The OSAP Authors
"""Verify the conformance registry: every listing must be reproducible.

`conformance/registry.md` records implementations that claim conformance
levels. This tool enforces the admission gate mechanically:

* each row points at a committed report under `conformance/reports/` that
  validates against `report.schema.json`;
* the report's summary matches its own `cases` array, the row's date matches
  the report's `generated_at`, and the row's manual-case ids cover the
  report's skipped cases;
* the status column is one of the three legal states, and an ✅ entry must
  carry a rerun command.

With `--rerun` the tool additionally executes the rerun command of every ✅
row — but only when it starts with `python3 tools/conformance_run.py`, so a
registry entry can never make the checker run arbitrary shell commands. The
rerun always appends `--format json`, and the summary plus the set of failed
and skipped case ids must match the committed report exactly.

The checker is advisory for review, but CI runs the non-rerun part so a
registry edit cannot break schema validity or row/report consistency.
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import shlex
import subprocess
import sys
from jsonschema import Draft202012Validator, FormatChecker
from pathlib import Path
from referencing import Registry as SchemaRegistry, Resource
from referencing.jsonschema import DRAFT202012

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "impl"))

REGISTRY = ROOT / "conformance" / "registry.md"
REPORT_SCHEMA = ROOT / "conformance" / "report.schema.json"
REPORTS_DIR = ROOT / "conformance" / "reports"
COLUMNS = 9
STATUSES = ("✅", "🟡", "❌")
ID_PATTERN = re.compile(r"C\d-\d{2}")
RERUN_PATTERN = re.compile(r"^python3 tools/conformance_run\.py\b")


def load_report_validator():
    schema = json.loads(REPORT_SCHEMA.read_text(encoding="utf-8"))
    registry = SchemaRegistry().with_resource(
        schema["$id"],
        Resource.from_contents(schema, default_specification=DRAFT202012),
    )
    return Draft202012Validator(schema, registry=registry, format_checker=FormatChecker())


def split_cells(line: str) -> list[str]:
    """Split a markdown table row on pipes, keeping inline-code spans whole."""

    line = line.strip().strip("|")
    return [cell.strip() for cell in re.split(r"\|(?=(?:[^`]*`[^`]*`)*[^`]*$)", line)]


def table_rows(text: str) -> list[tuple[int, list[str]]]:
    """Return (line number, cells) for every data row of the registry table."""

    rows = []
    started = False
    header_seen = False
    for number, line in enumerate(text.splitlines(), start=1):
        if line.startswith("## 4."):
            started = True
            continue
        if started and line.startswith("## "):
            break
        if not started or not line.strip().startswith("|"):
            continue
        cells = split_cells(line)
        if len(cells) != COLUMNS:
            continue
        if set("".join(cells)) <= {"-", " ", ":"}:
            continue
        if not header_seen and cells[0] == "实现":
            header_seen = True
            continue
        rows.append((number, cells))
    return rows


def clean(cell: str) -> str:
    """Strip markdown decoration (backticks, links) from a table cell."""

    cell = cell.strip()
    match = re.fullmatch(r"\[[^\]]*\]\(([^)]+)\)", cell)
    if match:
        cell = match.group(1)
    return cell.strip("`")


def first_code(cell: str) -> str:
    """Return the first inline-code span of a cell, undecorated."""

    match = re.match(r"`([^`]+)`", cell.strip())
    if match:
        return match.group(1)
    return clean(cell)


def claimed_ids(cell: str) -> list[str]:
    return ID_PATTERN.findall(cell)


def check_report(registry_dir: Path, row: dict, row_number: int, errors: list[str]) -> dict:
    path = registry_dir / row["report"]
    if not str(row["report"]).startswith("reports/"):
        errors.append(f"row {row_number}: report path must live under conformance/reports/")
        return {}
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        errors.append(f"row {row_number}: report {row['report']!r} does not exist")
        return {}
    except json.JSONDecodeError as error:
        errors.append(f"row {row_number}: report is not valid JSON: {error}")
        return {}
    validator = load_report_validator()
    validator.validate(report)

    counts: dict[str, int] = {}
    for case in report["cases"]:
        counts[case["status"]] = counts.get(case["status"], 0) + 1
    summary = report["summary"]
    for status in ("pass", "fail", "skip"):
        if summary.get(status) != counts.get(status, 0):
            errors.append(
                f"row {row_number}: summary.{status}={summary.get(status)} "
                f"does not match the cases array ({counts.get(status, 0)})"
            )
    if summary.get("total") != len(report["cases"]):
        errors.append(f"row {row_number}: summary.total does not match the cases array")
    skipped = sorted(
        case["id"] for case in report["cases"] if case["status"] == "skip"
    )
    row_manual = sorted(set(claimed_ids(row["levels"])))
    if skipped and not set(skipped) <= set(row_manual):
        missing = sorted(set(skipped) - set(row_manual))
        errors.append(
            f"row {row_number}: skipped cases {missing} are not listed as manual "
            "in the levels column"
        )
    claimed = re.search(r"(\d+)/(\d+) pass", row["levels"])
    if claimed:
        if int(claimed.group(1)) != summary.get("pass"):
            errors.append(
                f"row {row_number}: the row claims {claimed.group(1)} pass but "
                f"the report says {summary.get('pass')}"
            )
        if int(claimed.group(2)) != summary.get("total"):
            errors.append(
                f"row {row_number}: the row claims {claimed.group(2)} total but "
                f"the report says {summary.get('total')}"
            )
    if not path.name.startswith(row["implementation"] + "-"):
        errors.append(
            f"row {row_number}: report file {path.name!r} does not start with "
            f"the implementation name {row['implementation']!r}"
        )
    generated = str(report.get("generated_at", ""))[:10]
    if generated != row["date"]:
        errors.append(
            f"row {row_number}: row date {row['date']} does not match the "
            f"report date {generated}"
        )
    return report


def rerun(row: dict, row_number: int, report: dict, errors: list[str]) -> None:
    command = row["command"]
    if not RERUN_PATTERN.match(command):
        errors.append(
            f"row {row_number}: --rerun only executes commands that start with "
            "'python3 tools/conformance_run.py'; refusing to run this command"
        )
        return
    parts = shlex.split(command)
    if "--format" not in parts:
        parts += ["--format", "json"]
    try:
        completed = subprocess.run(
            parts,
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
            timeout=600,
        )
    except subprocess.TimeoutExpired:
        errors.append(f"row {row_number}: rerun timed out after 600 s")
        return
    except (subprocess.CalledProcessError, FileNotFoundError) as error:
        errors.append(f"row {row_number}: rerun failed: {error}")
        return
    rerun_report = json.loads(completed.stdout)
    for key in ("total", "pass", "fail", "skip"):
        if rerun_report["summary"].get(key) != report["summary"].get(key):
            errors.append(
                f"row {row_number}: rerun summary.{key}="
                f"{rerun_report['summary'].get(key)} does not match the "
                f"committed report ({report['summary'].get(key)})"
            )
    for status in ("fail", "skip"):
        committed = sorted(
            case["id"] for case in report["cases"] if case["status"] == status
        )
        fresh = sorted(
            case["id"] for case in rerun_report["cases"] if case["status"] == status
        )
        if committed != fresh:
            errors.append(
                f"row {row_number}: rerun {status} ids {fresh} do not match the "
                f"committed report {committed}"
            )


def parse_rows(rows: list[tuple[int, list[str]]], errors: list[str]) -> list[dict]:
    parsed = []
    for number, cells in rows:
        status = cells[8]
        if not any(status.startswith(marker) for marker in STATUSES):
            errors.append(
                f"row {number}: status must start with one of {STATUSES}"
            )
        try:
            datetime.date.fromisoformat(cells[7])
        except ValueError:
            errors.append(f"row {number}: date {cells[7]!r} must be YYYY-MM-DD")
        parsed.append(
            {
                "implementation": first_code(cells[0]),
                "contact": clean(cells[2]),
                "levels": cells[3],
                "report": clean(cells[5]),
                "command": first_code(cells[6]),
                "date": cells[7],
                "status": status,
            }
        )
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--registry",
        default=str(REGISTRY),
        help="registry document to check (default: conformance/registry.md)",
    )
    parser.add_argument(
        "--rerun",
        action="store_true",
        help="also execute the rerun command of every ✅ row",
    )
    arguments = parser.parse_args()

    text = Path(arguments.registry).read_text(encoding="utf-8")
    registry_dir = Path(arguments.registry).resolve().parent
    errors: list[str] = []
    rows = parse_rows(table_rows(text), errors)
    if not rows:
        errors.append("the registry table has no data rows")

    for row_number, row in zip([number for number, _ in table_rows(text)], rows):
        report = check_report(registry_dir, row, row_number, errors)
        if row["status"].startswith("✅") and not row["command"]:
            errors.append(f"row {row_number}: a ✅ entry must carry a rerun command")
        if arguments.rerun and row["status"].startswith("✅") and report:
            rerun(row, row_number, report, errors)

    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    mode = "rerun + " if arguments.rerun else ""
    print(
        f"OK: {mode}{len(rows)} registry entr{'y' if len(rows) == 1 else 'ies'} "
        "checked"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
