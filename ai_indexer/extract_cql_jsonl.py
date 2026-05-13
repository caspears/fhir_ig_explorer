from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Dict, Iterable, List

from common_jsonl import clean_text, stable_id, write_jsonl, make_artifact_url, ig_context_from_root, add_common_file_metadata, build_cql_library_lookup


def derive_cql_metadata(filename: str, library_name: str, text: str) -> dict:
    combined = f"{filename} {library_name} {text}".lower()

    program = None
    reporting_frequency = None
    measure_group = None

    if "ach" in combined:
        program = "ACH"

    if "daily" in combined:
        reporting_frequency = "daily"
    elif "monthly" in combined:
        reporting_frequency = "monthly"

    if program and reporting_frequency:
        measure_group = f"{program} {reporting_frequency.title()}"
    elif program:
        measure_group = program

    return {
        "program": program,
        "reportingFrequency": reporting_frequency,
        "measureGroup": measure_group,
        "libraryNameNormalized": library_name.lower() if library_name else None,
    }


def extract_library_name(text: str, fallback: str) -> str:
    match = re.search(r"(?im)^\s*library\s+([A-Za-z0-9_.-]+)", text)
    return match.group(1) if match else fallback


def extract_version(text: str) -> str | None:
    match = re.search(r"(?im)^\s*library\s+[A-Za-z0-9_.-]+\s+version\s+'([^']+)'", text)
    return match.group(1) if match else None


def extract_header_declarations(text: str) -> List[dict]:
    patterns = [
        ("using", r"(?im)^\s*using\s+.+$"),
        ("include", r"(?im)^\s*include\s+.+$"),
        ("codesystem", r"(?im)^\s*codesystem\s+.+$"),
        ("valueset", r"(?im)^\s*valueset\s+.+$"),
        ("code", r"(?im)^\s*code\s+.+$"),
        ("parameter", r"(?im)^\s*parameter\s+.+$"),
        ("context", r"(?im)^\s*context\s+.+$"),
    ]

    rows = []
    for kind, pattern in patterns:
        for match in re.finditer(pattern, text):
            rows.append({
                "kind": kind,
                "statement": clean_text(match.group(0)),
            })

    return rows


def split_cql_defines(text: str) -> List[dict]:
    """
    Splits CQL into define blocks.

    Handles common forms:
      define "Initial Population":
      define InitialPopulation:
      define function SomeFunction(...):
    """
    pattern = re.compile(
        r"""(?imx)
        ^\s*define
        (?:\s+function)?
        \s+
        (?:
            "([^"]+)"
            |
            ([A-Za-z_][A-Za-z0-9_]*)
        )
        \s*(?:\([^)]*\))?
        \s*:
        """
    )

    matches = list(pattern.finditer(text))
    blocks = []

    for i, match in enumerate(matches):
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)

        define_name = match.group(1) or match.group(2)
        block_text = clean_text(text[start:end])

        blocks.append({
            "defineName": define_name,
            "text": block_text,
        })

    return blocks


def extract_cql_rows(path: Path, ig_context: Dict[str, str | None], library_lookup: dict) -> Iterable[Dict]:
    raw = path.read_text(encoding="utf-8", errors="ignore")
    text = clean_text(raw)

    if not text:
        return []

    library_name = extract_library_name(text, path.stem)
    version = extract_version(text)
    derived = derive_cql_metadata(path.name, library_name, text)

    library_metadata = (
        library_lookup.get(path.name)
        or library_lookup.get(path.name.lower())
        or {}
    )

    rows = []

    overview_text = clean_text(
        "\n".join([
            f"CQL Library: {library_name}",
            f"Version: {version}",
            f"File: {path.name}",
            f"Program: {derived.get('program')}",
            f"Measure group: {derived.get('measureGroup')}",
            f"Reporting frequency: {derived.get('reportingFrequency')}",
        ])
    )

    rows.append(add_common_file_metadata({
        "id": stable_id("cql", library_name, "overview", str(path)),
        "sourceType": "CQL",
        "chunkType": "cql-overview",
        "file": str(path),
        "libraryName": library_name,
        "libraryVersion": version,
        **derived,
        **library_metadata,
        "text": overview_text,
    }, ig_context))

    for idx, declaration in enumerate(extract_header_declarations(text)):
        rows.append(add_common_file_metadata({
            "id": stable_id("cql", library_name, declaration["kind"], idx, declaration["statement"], str(path)),
            "sourceType": "CQL",
            "chunkType": f"cql-{declaration['kind']}",
            "file": str(path),
            "libraryName": library_name,
            "libraryVersion": version,
            "declarationType": declaration["kind"],
            **derived,
            **library_metadata,
            "text": clean_text(
                f"CQL Library: {library_name}\n"
                f"Declaration type: {declaration['kind']}\n"
                f"{declaration['statement']}"
            ),
        }, ig_context))

    for idx, block in enumerate(split_cql_defines(text)):
        define_name = block["defineName"]
        block_text = block["text"]

        define_type = "cql-define"
        if define_name and "initial population" in define_name.lower():
            define_type = "cql-initial-population"
        elif define_name and "encounter" in define_name.lower():
            define_type = "cql-encounter-logic"
        elif define_name and "extract" in define_name.lower():
            define_type = "cql-extraction-logic"

        rows.append(add_common_file_metadata({
            "id": stable_id("cql", library_name, "define", idx, define_name, str(path)),
            "sourceType": "CQL",
            "chunkType": define_type,
            "file": str(path),
            "libraryName": library_name,
            "libraryVersion": version,
            "defineName": define_name,
            **derived,
            **library_metadata,
            "text": clean_text(
                f"CQL Library: {library_name}\n"
                f"Define: {define_name}\n"
                f"Program: {derived.get('program')}\n"
                f"Measure group: {derived.get('measureGroup')}\n"
                f"Reporting frequency: {derived.get('reportingFrequency')}\n\n"
                f"{block_text}"
            ),
        }, ig_context))

    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Folder containing .cql files")
    parser.add_argument("--output", required=True, help="Output cql.jsonl")
    parser.add_argument("--ig-name", default=None, help="Optional IG name override")
    parser.add_argument("--base-url", default=None, help="Optional published IG base URL override")
    args = parser.parse_args()

    root = Path(args.input)
    ig_context = ig_context_from_root(root)
    library_lookup = build_cql_library_lookup(root, ig_context)

    if args.ig_name:
        ig_context["ig_title"] = args.ig_name
        ig_context["ig_name"] = args.ig_name

    if args.base_url:
        ig_context["base_url"] = args.base_url

    rows = []
    for path in Path(args.input).rglob("*.cql"):
        rows.extend(extract_cql_rows(path, ig_context, library_lookup))

    count = write_jsonl(Path(args.output), rows)
    print(f"Wrote {count} rows to {args.output}")


if __name__ == "__main__":
    main()