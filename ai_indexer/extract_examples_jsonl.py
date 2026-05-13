"""
Extract example FHIR resources into JSONL.

This script intentionally excludes conformance resources that are usually indexed elsewhere:
StructureDefinition, ValueSet, CodeSystem, CapabilityStatement, SearchParameter,
OperationDefinition, ConceptMap, NamingSystem, ImplementationGuide.

It creates compact summaries plus optionally resource JSON snippets.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable

from common_jsonl import clean_text, get_resource_type, iter_json_files, read_json, stable_id, write_jsonl, make_artifact_url, ig_context_from_root, add_common_ig_metadata


EXCLUDE_TYPES = {
    "StructureDefinition",
    "ValueSet",
    "CodeSystem",
    "CapabilityStatement",
    "SearchParameter",
    "OperationDefinition",
    "ConceptMap",
    "NamingSystem",
    "ImplementationGuide",
}


def extract_reference_summary(resource: Dict[str, Any]) -> list[str]:
    refs: list[str] = []

    def walk(obj: Any, path: str = ""):
        if isinstance(obj, dict):
            if "reference" in obj and isinstance(obj.get("reference"), str):
                refs.append(f"{path}.reference={obj.get('reference')}")
            for k, v in obj.items():
                walk(v, f"{path}.{k}" if path else k)
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                walk(item, f"{path}[{i}]")

    walk(resource)
    return refs[:100]


def extract_example_rows(path: Path, resource: Dict[str, Any], ig_context: Dict[str, str | None], include_json: bool) -> Iterable[Dict[str, Any]]:
    rt = get_resource_type(resource)
    if not rt or rt in EXCLUDE_TYPES:
        return []

    resource_id = resource.get("id")
    meta_profiles = []
    if isinstance(resource.get("meta"), dict):
        meta_profiles = resource["meta"].get("profile", []) if isinstance(resource["meta"].get("profile"), list) else []

    identifiers = []
    ident = resource.get("identifier")
    if isinstance(ident, list):
        for i in ident:
            if isinstance(i, dict):
                identifiers.append(f"{i.get('system')}|{i.get('value')}")
    elif isinstance(ident, dict):
        identifiers.append(f"{ident.get('system')}|{ident.get('value')}")

    refs = extract_reference_summary(resource)

    json_snippet = json.dumps(resource, ensure_ascii=False, indent=2)
    if not include_json and len(json_snippet) > 4000:
        json_snippet = json_snippet[:4000] + "\n... [truncated]"

    text = clean_text(
        "\n".join(
            [
                f"FHIR example resource: {rt}/{resource_id}",
                f"File: {path.name}",
                f"Meta profiles: {', '.join(meta_profiles)}",
                f"Identifiers: {', '.join(identifiers)}",
                f"References: {' || '.join(refs)}",
                "Resource JSON:",
                json_snippet,
            ]
        )
    )

    return [
        add_common_ig_metadata({
            "id": stable_id("example", rt, resource_id or path.name, str(path)),
            "sourceType": "Example",
            "chunkType": "example-resource",
            "file": str(path),
            "resourceType": rt,
            "resourceId": resource_id,
            "metaProfiles": meta_profiles,
            "identifiers": identifiers,
            "text": text,
        }, resource, ig_context)
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Folder containing FHIR JSON artifacts")
    parser.add_argument("--output", required=True, help="Output examples.jsonl")
    parser.add_argument("--ig-name", default=None, help="Optional IG name override")
    parser.add_argument("--base-url", default=None, help="Optional published IG base URL override")
    parser.add_argument("--include-full-json", action="store_true", help="Include full JSON text in each chunk")
    args = parser.parse_args()

    root = Path(args.input)
    ig_context = ig_context_from_root(root)

    if args.ig_name:
        ig_context["ig_title"] = args.ig_name
        ig_context["ig_name"] = args.ig_name

    if args.base_url:
        ig_context["base_url"] = args.base_url

    rows = []
    for path in iter_json_files(Path(args.input)):
        resource = read_json(path)
        if not isinstance(resource, dict):
            continue
        if resource:
            rows.extend(extract_example_rows(path, resource, ig_context, args.include_full_json))

    count = write_jsonl(Path(args.output), rows)
    print(f"Wrote {count} rows to {args.output}")


if __name__ == "__main__":
    main()
