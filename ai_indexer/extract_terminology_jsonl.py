"""
Extract FHIR ValueSet and CodeSystem content into JSONL.

Produces chunks for:
- ValueSet overview
- ValueSet compose.include systems, concepts, filters, nested value sets
- CodeSystem overview
- CodeSystem concepts

Useful for questions such as:
- What codes are required?
- What code systems are used?
- Does this ValueSet include another ValueSet?
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Dict, Iterable, List

from common_jsonl import clean_text, canonical_or_url, get_resource_type, iter_json_files, read_json, stable_id, write_jsonl,make_artifact_url, ig_context_from_root, add_common_ig_metadata


def concept_line(concept: Dict[str, Any]) -> str:
    return clean_text(
        f"code={concept.get('code')}; display={concept.get('display')}; definition={concept.get('definition')}"
    )


def extract_valueset_rows(path: Path, resource: Dict[str, Any], ig_context: Dict[str, str | None]) -> Iterable[Dict[str, Any]]:
    url = canonical_or_url(resource)
    name = resource.get("name")
    title = resource.get("title") or name or url or path.stem
    version = resource.get("version")
    status = resource.get("status")
    description = resource.get("description")
    purpose = resource.get("purpose")

    overview = clean_text(
        "\n".join(
            [
                f"FHIR ValueSet: {title}",
                f"Canonical URL: {url}",
                f"Version: {version}",
                f"Status: {status}",
                f"Description: {description}",
                f"Purpose: {purpose}",
            ]
        )
    )

    yield add_common_ig_metadata({
        "id": stable_id("valueset", url or path.name, "overview"),
        "sourceType": "ValueSet",
        "chunkType": "valueset-overview",
        "file": str(path),
        "url": url,
        "version": version,
        "name": name,
        "title": title,
        "status": status,
        "text": overview,
    }, resource, ig_context)

    compose = resource.get("compose") if isinstance(resource.get("compose"), dict) else {}
    includes = compose.get("include", []) if isinstance(compose.get("include"), list) else []

    for idx, inc in enumerate(includes):
        system = inc.get("system")
        version_inc = inc.get("version")
        nested_value_sets = inc.get("valueSet", []) if isinstance(inc.get("valueSet"), list) else []
        concepts = inc.get("concept", []) if isinstance(inc.get("concept"), list) else []
        filters = inc.get("filter", []) if isinstance(inc.get("filter"), list) else []

        concept_lines = [concept_line(c) for c in concepts if isinstance(c, dict)]
        filter_lines = [
            f"property={f.get('property')}; op={f.get('op')}; value={f.get('value')}"
            for f in filters
            if isinstance(f, dict)
        ]

        text = clean_text(
            "\n".join(
                [
                    f"FHIR ValueSet include for {title}",
                    f"ValueSet canonical: {url}",
                    f"Include index: {idx}",
                    f"System: {system}",
                    f"System version: {version_inc}",
                    f"Included ValueSets: {', '.join(nested_value_sets)}",
                    "Filters: " + " || ".join(filter_lines) if filter_lines else "",
                    "Concepts: " + " || ".join(concept_lines) if concept_lines else "",
                ]
            )
        )

        yield add_common_ig_metadata({
            "id": stable_id("valueset-include", url or path.name, idx),
            "sourceType": "ValueSet",
            "chunkType": "valueset-include",
            "file": str(path),
            "url": url,
            "version": version,
            "name": name,
            "title": title,
            "system": system,
            "systemVersion": version_inc,
            "includedValueSets": nested_value_sets,
            "conceptCount": len(concepts),
            "filterCount": len(filters),
            "text": text,
        }, resource, ig_context)


def extract_codesystem_rows(path: Path, resource: Dict[str, Any], ig_context: Dict[str, str | None]) -> Iterable[Dict[str, Any]]:
    url = canonical_or_url(resource)
    name = resource.get("name")
    title = resource.get("title") or name or url or path.stem
    version = resource.get("version")
    status = resource.get("status")
    content = resource.get("content")
    description = resource.get("description")
    purpose = resource.get("purpose")
    case_sensitive = resource.get("caseSensitive")
    hierarchy_meaning = resource.get("hierarchyMeaning")

    overview = clean_text(
        "\n".join(
            [
                f"FHIR CodeSystem: {title}",
                f"Canonical URL: {url}",
                f"Version: {version}",
                f"Status: {status}",
                f"Content: {content}",
                f"Case sensitive: {case_sensitive}",
                f"Hierarchy meaning: {hierarchy_meaning}",
                f"Description: {description}",
                f"Purpose: {purpose}",
            ]
        )
    )

    yield add_common_ig_metadata({
        "id": stable_id("codesystem", url or path.name, "overview"),
        "sourceType": "CodeSystem",
        "chunkType": "codesystem-overview",
        "file": str(path),
        "url": url,
        "version": version,
        "name": name,
        "title": title,
        "status": status,
        "content": content,
        "text": overview,
    }, resource, ig_context)

    concepts = resource.get("concept", []) if isinstance(resource.get("concept"), list) else []

    def walk_concepts(items: List[Dict[str, Any]], parent: str | None = None):
        for c in items:
            if not isinstance(c, dict):
                continue
            code = c.get("code")
            display = c.get("display")
            definition = c.get("definition")
            text = clean_text(
                "\n".join(
                    [
                        f"FHIR CodeSystem concept from {title}",
                        f"CodeSystem canonical: {url}",
                        f"Code: {code}",
                        f"Display: {display}",
                        f"Definition: {definition}",
                        f"Parent code: {parent}",
                    ]
                )
            )
            yield add_common_ig_metadata({
                "id": stable_id("codesystem-concept", url or path.name, parent or "", code),
                "sourceType": "CodeSystem",
                "chunkType": "codesystem-concept",
                "file": str(path),
                "url": url,
                "version": version,
                "name": name,
                "title": title,
                "code": code,
                "display": display,
                "definition": definition,
                "parentCode": parent,
                "text": text,
            }, resource, ig_context)

            children = c.get("concept", []) if isinstance(c.get("concept"), list) else []
            yield from walk_concepts(children, code)

    yield from walk_concepts(concepts)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Folder containing FHIR JSON artifacts")
    parser.add_argument("--output", required=True, help="Output terminology.jsonl")
    parser.add_argument("--ig-name", default=None, help="Optional IG name override")
    parser.add_argument("--base-url", default=None, help="Optional published IG base URL override")
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
        if not resource:
            continue
        if not isinstance(resource, dict):
            continue
        rt = get_resource_type(resource)
        if rt == "ValueSet":
            rows.extend(extract_valueset_rows(path, resource, ig_context))
        elif rt == "CodeSystem":
            rows.extend(extract_codesystem_rows(path, resource, ig_context))

    count = write_jsonl(Path(args.output), rows)
    print(f"Wrote {count} rows to {args.output}")


if __name__ == "__main__":
    main()
