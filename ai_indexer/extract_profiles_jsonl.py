"""
Extract FHIR StructureDefinition profile content into JSONL.

Produces:
- one profile overview chunk per StructureDefinition
- one element-level chunk per snapshot element
- optional differential element chunks when present

This is intended for RAG / vector indexing where users may ask:
- Is an element required?
- Is it Must Support?
- What ValueSet is bound?
- What constraints apply?
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Dict, Iterable, List

from common_jsonl import (
    binding_summary,
    canonical_or_url,
    clean_text,
    element_text,
    get_resource_type,
    iter_json_files,
    read_json,
    stable_id,
    write_jsonl,
    make_artifact_url,
    ig_context_from_root, 
    add_common_ig_metadata,
)


def is_structure_definition(resource: Dict[str, Any]) -> bool:
    return get_resource_type(resource) == "StructureDefinition"


def derive_profile_metadata(title: str) -> dict:
    """
    Derive normalized metadata from profile titles
    to improve filtering and reranking.
    """

    t = (title or "").lower()

    result = {
        "profileNameNormalized": t,
        "program": None,
        "reportingFrequency": None,
        "domain": None
    }

    # ------------------------------------
    # Program/domain detection
    # ------------------------------------

    if "ach" in t:
        result["program"] = "ACH"

    elif "ahs" in t:
        result["program"] = "AHS"

    # ------------------------------------
    # Frequency detection
    # ------------------------------------

    if "daily" in t:
        result["reportingFrequency"] = "daily"

    elif "monthly" in t:
        result["reportingFrequency"] = "monthly"

    elif "annual" in t:
        result["reportingFrequency"] = "annual"

    # ------------------------------------
    # Domain/resource hints
    # ------------------------------------

    if "encounter" in t:
        result["domain"] = "Encounter"

    elif "observation" in t:
        result["domain"] = "Observation"

    elif "patient" in t:
        result["domain"] = "Patient"

    return result

def extract_profile_rows(path: Path, resource: Dict[str, Any], ig_context: Dict[str, str | None]) -> Iterable[Dict[str, Any]]:
    url = canonical_or_url(resource)
    artifact_url = make_artifact_url(ig_context["base_url"], resource)
    name = resource.get("name")
    title = resource.get("title") or name or url or path.stem
    derived = derive_profile_metadata(str(title))
    kind = resource.get("kind")
    derivation = resource.get("derivation")
    type_ = resource.get("type")
    base = resource.get("baseDefinition")
    description = resource.get("description")
    purpose = resource.get("purpose")
    status = resource.get("status")
    version = resource.get("version")

    overview_text = clean_text(
        "\n".join(
            [
                f"FHIR StructureDefinition profile: {title}",
                f"Canonical URL: {url}",
                f"Version: {version}",
                f"Status: {status}",
                f"Kind: {kind}",
                f"Type: {type_}",
                f"Derivation: {derivation}",
                f"Base definition: {base}",
                f"Description: {description}",
                f"Purpose: {purpose}",
            ]
        )
    )

    yield add_common_ig_metadata({
        "id": stable_id("profile", url or path.name, "overview"),
        "sourceType": "StructureDefinition",
        "chunkType": "profile-overview",
        "file": str(path),
        "url": url,
        "artifactUrl": artifact_url,
        "version": version,
        "name": name,
        "title": title,
        "profileName": title,
        "profileNameNormalized": derived["profileNameNormalized"],
        "program": derived["program"],
        "reportingFrequency": derived["reportingFrequency"],
        "domain": derived["domain"],
        "resourceType": "StructureDefinition",
        "fhirType": type_,
        "kind": kind,
        "derivation": derivation,
        "baseDefinition": base,
        "status": status,
        "text": overview_text,
    }, resource, ig_context)

    for section_name in ["snapshot", "differential"]:
        elements: List[Dict[str, Any]] = (
            resource.get(section_name, {}).get("element", [])
            if isinstance(resource.get(section_name), dict)
            else []
        )
        for element in elements:
            if not isinstance(element, dict):
                continue

            binding = binding_summary(element.get("binding"))
            element_id = element.get("id")
            element_path = element.get("path")
            text = element_text(str(title), str(url), element)
            

            yield add_common_ig_metadata({
                "id": stable_id("profile-element", url or path.name, section_name, element_id or element_path),
                "sourceType": "StructureDefinition",
                "chunkType": f"{section_name}-element",
                "effectiveConstraint": (section_name == "snapshot"),
                "file": str(path),
                "url": url,
                "artifactUrl": artifact_url,
                "version": version,
                "name": name,
                "title": title,
                "profileName": title,
                "profileNameNormalized": derived["profileNameNormalized"],
                "program": derived["program"],
                "reportingFrequency": derived["reportingFrequency"],
                "domain": derived["domain"],
                "resourceType": "StructureDefinition",
                "fhirType": type_,
                "kind": kind,
                "derivation": derivation,
                "baseDefinition": base,
                "section": section_name,
                "elementId": element_id,
                "elementPath": element_path,
                "sliceName": element.get("sliceName"),
                "min": element.get("min"),
                "max": element.get("max"),
                "mustSupport": element.get("mustSupport"),
                "isModifier": element.get("isModifier"),
                "bindingStrength": binding.get("bindingStrength"),
                "valueSet": binding.get("valueSet"),
                "short": element.get("short"),
                "definition": element.get("definition"),
                "text": text,
            }, resource, ig_context)


            constraints = (
                element.get("constraint")
                if isinstance(element.get("constraint"), list)
                else []
            )

            for constraint_index, constraint in enumerate(constraints):
                if not isinstance(constraint, dict):
                    continue

                constraint_key = constraint.get("key")
                severity = constraint.get("severity")
                human = constraint.get("human")
                expression = constraint.get("expression")
                xpath = constraint.get("xpath")
                source = constraint.get("source")

                constraint_text = clean_text(
                    "\n".join([
                        f"Profile: {title}",
                        f"Profile canonical: {url}",
                        f"Resource type: {type_}",
                        f"Element: {element_path}",
                        f"Element id: {element_id}",
                        f"Constraint key: {constraint_key}",
                        f"Severity: {severity}",
                        f"Human description: {human}",
                        f"FHIRPath expression: {expression}",
                        f"XPath: {xpath}",
                        f"Source: {source}",
                    ])
                )

                yield add_common_ig_metadata({
                    "id": stable_id(
                        "profile-constraint",
                        url or path.name,
                        section_name,
                        element_id or element_path,
                        constraint_key or constraint_index,
                        constraint_index
                    ),

                    "sourceType": "StructureDefinition",
                    "chunkType": f"{section_name}-constraint",

                    # useful for ranking/filtering
                    "isConstraint": True,
                    "effectiveConstraint": section_name == "snapshot",

                    "file": str(path),
                    "url": url,
                    "version": version,
                    "name": name,
                    "title": title,
                    "profileName": title,

                    "profileNameNormalized": derived["profileNameNormalized"],
                    "program": derived["program"],
                    "reportingFrequency": derived["reportingFrequency"],
                    "domain": derived["domain"],

                    "resourceType": "StructureDefinition",
                    "fhirType": type_,
                    "kind": kind,
                    "derivation": derivation,
                    "baseDefinition": base,

                    "section": section_name,
                    "elementId": element_id,
                    "elementPath": element_path,

                    "constraintKey": constraint_key,
                    "constraintSeverity": severity,
                    "constraintHuman": human,
                    "constraintExpression": expression,
                    "constraintSource": source,

                    "text": constraint_text,

                }, resource, ig_context)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Folder containing FHIR JSON artifacts")
    parser.add_argument("--output", required=True, help="Output profiles.jsonl")
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
    for path in iter_json_files(root):
        resource = read_json(path)
        if not isinstance(resource, dict):
            continue
        if resource and is_structure_definition(resource):
            rows.extend(extract_profile_rows(path, resource, ig_context))

    count = write_jsonl(Path(args.output), rows)
    print(f"Wrote {count} rows to {args.output}")


if __name__ == "__main__":
    main()
