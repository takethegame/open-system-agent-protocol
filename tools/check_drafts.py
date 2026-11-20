#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The OSAP Authors
"""Static checks for the IETF xml2rfc v3 drafts in ``drafts/``.

The checks are intentionally independent of ``xml2rfc`` so that they run on a
clean checkout.  ``--compile`` additionally invokes ``xml2rfc`` when it is
installed; CI installs it from ``requirements-drafts.txt``.

Checks:
  - XML well-formedness and the v3 ``rfc`` root;
  - required front matter and a valid ``docName``/filename pair;
  - unique anchors and resolvable internal ``xref`` targets;
  - every reference is cited and every citation resolves;
  - every ``sourcecode type="json"`` block parses;
  - no placeholders, local paths, personal identifiers, or non-ASCII text;
  - no dependency on ``docs/standard.md`` or another unpublished local file.

Usage:
    python3 tools/check_drafts.py
    python3 tools/check_drafts.py --compile
    python3 tools/check_drafts.py --compile --outdir build/drafts
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DRAFTS = ROOT / "drafts"
FORBIDDEN = ["zengyunhao", "macbook-pro", "zhangsan", "张三", "/Users/"]
PLACEHOLDERS = ("{{", "}}", "TODO", "TBD", "FIXME", "XXX")
#: Authors that may stand in while drafting but block an actual submission.
SUBMISSION_PLACEHOLDERS = ("OSAP Editors", "editors@osap.example")
DOCNAME_RE = re.compile(r"^draft-[a-z0-9-]+-\d{2}$")
CATEGORIES = {"info", "std", "exp", "bcp", "historic"}
SUBMISSION_TYPES = {"IETF", "IRTF", "IAB", "independent"}


def text_of(element: ET.Element | None) -> str:
    if element is None:
        return ""
    return "".join(element.itertext()).strip()


def check_draft(path: Path, *, submission_mode: bool = False) -> tuple[int, list[str]]:
    failures: list[str] = []
    checks = 0
    rel = path.relative_to(ROOT)

    checks += 1
    try:
        tree = ET.parse(path)
    except ET.ParseError as exc:
        return checks, [f"{rel}: XML does not parse: {exc}"]
    root = tree.getroot()

    checks += 1
    if root.tag != "rfc":
        failures.append(f"{rel}: root element is {root.tag!r}, expected 'rfc'")
        return checks, failures

    checks += 1
    if root.get("version") != "3":
        failures.append(f"{rel}: rfc/@version must be '3'")

    checks += 1
    doc_name = root.get("docName", "")
    if not DOCNAME_RE.match(doc_name):
        failures.append(f"{rel}: invalid docName {doc_name!r}")
    if doc_name and doc_name != path.stem:
        failures.append(f"{rel}: docName {doc_name!r} does not match filename")

    checks += 1
    if root.get("category") not in CATEGORIES:
        failures.append(f"{rel}: invalid category {root.get('category')!r}")
    if root.get("submissionType") not in SUBMISSION_TYPES:
        failures.append(
            f"{rel}: invalid submissionType {root.get('submissionType')!r}"
        )
    if root.get("consensus") not in {"true", "false"}:
        failures.append(f"{rel}: consensus must be 'true' or 'false'")
    if not root.get("ipr"):
        failures.append(f"{rel}: missing ipr attribute")

    front = root.find("front")
    checks += 1
    if front is None:
        failures.append(f"{rel}: missing <front>")
    else:
        for required in ("title", "author", "date", "abstract"):
            if front.find(required) is None:
                failures.append(f"{rel}: front is missing <{required}>")
        title = text_of(front.find("title"))
        if not title:
            failures.append(f"{rel}: front/title is empty")
        date = front.find("date")
        if date is not None and not all(date.get(k) for k in ("year", "month", "day")):
            failures.append(f"{rel}: front/date needs year, month, and day")
        abstract = text_of(front.find("abstract"))
        if len(abstract) < 80:
            failures.append(f"{rel}: abstract is too short to be useful")
        series = front.findall("seriesInfo")
        if not any(
            s.get("name") == "Internet-Draft" and s.get("value") == doc_name
            for s in series
        ):
            failures.append(
                f"{rel}: front must declare an Internet-Draft seriesInfo "
                f"whose value is {doc_name!r}"
            )

    checks += 1
    middle = root.find("middle")
    if middle is None or middle.find("section") is None:
        failures.append(f"{rel}: <middle> must contain at least one <section>")

    checks += 1
    back = root.find("back")
    if back is None or back.find("references") is None:
        failures.append(f"{rel}: <back> must contain <references>")

    checks += 1
    anchors: dict[str, ET.Element] = {}
    for element in root.iter():
        anchor = element.get("anchor")
        if not anchor:
            continue
        if anchor in anchors:
            failures.append(f"{rel}: duplicate anchor {anchor!r}")
        anchors[anchor] = element

    checks += 1
    for section in root.iter("section"):
        if not text_of(section.find("name")):
            failures.append(
                f"{rel}: section {section.get('anchor', '<unnamed>')} has no <name>"
            )

    checks += 1
    for table in root.iter("table"):
        if not text_of(table.find("name")):
            failures.append(
                f"{rel}: table {table.get('anchor', '<unnamed>')} has no <name>"
            )

    checks += 1
    references: dict[str, ET.Element] = {}
    for references_element in root.iter("references"):
        for reference in references_element.findall("reference"):
            anchor = reference.get("anchor")
            if not anchor:
                failures.append(f"{rel}: reference without an anchor")
                continue
            if anchor in references:
                failures.append(f"{rel}: duplicate reference anchor {anchor!r}")
            references[anchor] = reference
            if reference.find("front/title") is None:
                failures.append(f"{rel}: reference {anchor!r} has no title")

    checks += 1
    for reference in references.values():
        if reference.find("front/seriesInfo") is not None:
            failures.append(
                f"{rel}: reference {reference.get('anchor')!r} places "
                "seriesInfo inside <front>"
            )

    checks += 1
    cited: set[str] = set()
    for xref in root.iter("xref"):
        target = xref.get("target")
        if not target:
            failures.append(f"{rel}: xref without a target")
            continue
        cited.add(target)
        if target not in anchors and target not in references:
            failures.append(f"{rel}: unresolved xref target {target!r}")

    checks += 1
    unused = sorted(set(references) - cited)
    if unused:
        failures.append(f"{rel}: unused references: {', '.join(unused)}")

    checks += 1
    for block in root.iter("sourcecode"):
        if block.get("type", "").lower() != "json":
            continue
        try:
            json.loads(block.text or "")
        except json.JSONDecodeError as exc:
            failures.append(f"{rel}: JSON sourcecode does not parse: {exc}")

    checks += 1
    raw = path.read_text(encoding="utf-8")
    for needle in FORBIDDEN:
        if needle.lower() in raw.lower():
            failures.append(f"{rel}: contains forbidden string {needle!r}")
    for needle in PLACEHOLDERS:
        if needle in raw:
            failures.append(f"{rel}: contains unresolved placeholder {needle!r}")
    if submission_mode:
        for needle in SUBMISSION_PLACEHOLDERS:
            if needle in raw:
                failures.append(
                    f"{rel}: placeholder author {needle!r} must be replaced "
                    "with a real named author before submission (--submission)"
                )
        authors = root.findall("./front/author")
        checks += 1
        if not authors:
            failures.append(f"{rel}: --submission requires a named front author")
        for author in authors:
            if author.find("./address/email") is None and author.find(
                "./address/postal"
            ) is None:
                failures.append(
                    f"{rel}: author {author.get('fullname')!r} has no contact "
                    "address (--submission)"
                )
    for needle in ("standard.md", "docs/", "examples/", "schemas/"):
        if needle in raw:
            failures.append(
                f"{rel}: draft must be self-contained, found local reference "
                f"{needle!r}"
            )

    checks += 1
    for line_number, line in enumerate(raw.splitlines(), 1):
        for char in line:
            if ord(char) > 127:
                failures.append(
                    f"{rel}:{line_number}: non-ASCII character {char!r}"
                )
                break

    return checks, failures


def compile_drafts(outdir: Path) -> list[str]:
    failures: list[str] = []
    xml2rfc = shutil.which("xml2rfc")
    if not xml2rfc:
        return ["xml2rfc is not installed; install requirements-drafts.txt"]
    outdir.mkdir(parents=True, exist_ok=True)
    for path in sorted(DRAFTS.glob("*.xml")):
        result = subprocess.run(
            [xml2rfc, str(path), "-p", str(outdir), "--text", "--html"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        if result.returncode:
            detail = (result.stderr or result.stdout).strip()
            failures.append(
                f"{path.relative_to(ROOT)}: xml2rfc failed:\n{detail}"
            )
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--compile",
        action="store_true",
        help="also compile every draft with xml2rfc",
    )
    parser.add_argument(
        "--outdir",
        type=Path,
        default=ROOT / "build" / "drafts",
        help="output directory for --compile (default: build/drafts)",
    )
    parser.add_argument(
        "--submission",
        action="store_true",
        help="enforce pre-submission gates: no placeholder authors, "
        "every author has an email",
    )
    args = parser.parse_args()

    drafts = sorted(DRAFTS.glob("*.xml"))
    if not drafts:
        print("FAIL: no drafts/*.xml files found", file=sys.stderr)
        return 1

    total_checks = 0
    failures: list[str] = []
    for path in drafts:
        checks, problems = check_draft(path, submission_mode=args.submission)
        total_checks += checks
        failures.extend(problems)

    if args.compile:
        failures.extend(compile_drafts(args.outdir))

    if failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        return 1

    suffix = " and compiled" if args.compile else ""
    print(
        f"OK: {total_checks} checks passed across {len(drafts)} drafts{suffix}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
