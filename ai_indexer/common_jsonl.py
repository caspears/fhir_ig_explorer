"""
Shared utilities for FHIR IG JSONL extraction scripts.

Python 3.10+
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional

def read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            count += 1
    return count


def stable_id(*parts: Any) -> str:
    raw = "|".join("" if p is None else str(p) for p in parts)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    prefix = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(parts[0]))[:80] if parts else "row"
    return f"{prefix}-{digest}"


def clean_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return text.strip()


def strip_markdown_noise(text: str) -> str:
    text = re.sub(r"\{%\s*(include|include_relative).*?%\}", " ", text)
    text = re.sub(r"\{\{.*?\}\}", " ", text)
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.DOTALL)
    text = re.sub(r"^\s*---\s*$.*?^\s*---\s*$", " ", text, flags=re.DOTALL | re.MULTILINE)
    return clean_text(text)


def iter_json_files(root: Path) -> Iterator[Path]:
    for path in root.rglob("*.json"):
        if path.is_file():
            yield path


def first_text(*values: Any) -> Optional[str]:
    for v in values:
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def canonical_or_url(resource: Dict[str, Any]) -> Optional[str]:
    return first_text(resource.get("url"), resource.get("id"))


def get_resource_type(resource: Dict[str, Any]) -> Optional[str]:
    if type(resource) is dict:
        rt = resource.get("resourceType")
        return rt if isinstance(rt, str) else None
    return None


def human_join(values: Iterable[Any], separator: str = "; ") -> str:
    return separator.join(str(v) for v in values if v not in (None, "", [], {}))


def chunk_text(
    text: str,
    *,
    max_chars: int = 2400,
    overlap_chars: int = 250,
    min_chars: int = 200,
) -> List[str]:
    """
    Paragraph-aware chunking. Keeps chunks small enough for embedding while preserving context.
    """
    text = clean_text(text)
    if not text:
        return []

    paragraphs = re.split(r"\n\s*\n", text)
    chunks: List[str] = []
    current = ""

    for para in paragraphs:
        para = clean_text(para)
        if not para:
            continue

        if len(current) + len(para) + 2 <= max_chars:
            current = f"{current}\n\n{para}".strip()
            continue

        if current and len(current) >= min_chars:
            chunks.append(current)

        if len(para) > max_chars:
            start = 0
            while start < len(para):
                end = start + max_chars
                piece = para[start:end].strip()
                if len(piece) >= min_chars:
                    chunks.append(piece)
                start = end - overlap_chars
                if start < 0:
                    start = end
            current = ""
        else:
            if chunks and overlap_chars > 0:
                overlap = chunks[-1][-overlap_chars:]
                current = f"{overlap}\n\n{para}".strip()
            else:
                current = para

    if current and len(current) >= min_chars:
        chunks.append(current)

    if not chunks and text:
        chunks.append(text[:max_chars])

    return chunks


def binding_summary(binding: Dict[str, Any] | None) -> Dict[str, Any]:
    if not isinstance(binding, dict):
        return {}
    return {
        "bindingStrength": binding.get("strength"),
        "valueSet": binding.get("valueSet"),
        "bindingDescription": binding.get("description"),
    }


def element_text(profile_title: str, profile_url: str, element: Dict[str, Any]) -> str:
    path = element.get("path")
    slice_name = element.get("sliceName")
    element_id = element.get("id")
    short = element.get("short")
    definition = element.get("definition")
    comment = element.get("comment")
    requirements = element.get("requirements")
    minv = element.get("min")
    maxv = element.get("max")
    ms = element.get("mustSupport")
    modifier = element.get("isModifier")
    binding = binding_summary(element.get("binding"))
    constraints = element.get("constraint") if isinstance(element.get("constraint"), list) else []

    type_codes = []
    for t in element.get("type", []) if isinstance(element.get("type"), list) else []:
        code = t.get("code")
        profiles = t.get("profile") or t.get("targetProfile")
        if profiles:
            type_codes.append(f"{code}({', '.join(profiles)})")
        else:
            type_codes.append(str(code))

    pieces = [
        f"Profile: {profile_title}",
        f"Profile canonical: {profile_url}",
        f"Element: {path}",
        f"Element id: {element_id}",
    ]
    if slice_name:
        pieces.append(f"Slice: {slice_name}")
    pieces.extend([
        f"Cardinality: {minv}..{maxv}",
        f"Must Support: {ms}",
    ])
    if modifier is not None:
        pieces.append(f"Is Modifier: {modifier}")
    if type_codes:
        pieces.append(f"Types: {', '.join(type_codes)}")
    if binding:
        pieces.append(f"Terminology binding: strength={binding.get('bindingStrength')}; valueSet={binding.get('valueSet')}; description={binding.get('bindingDescription')}")
    if short:
        pieces.append(f"Short: {short}")
    if definition:
        pieces.append(f"Definition: {definition}")
    if comment:
        pieces.append(f"Comment: {comment}")
    if requirements:
        pieces.append(f"Requirements: {requirements}")
    if constraints:
        summaries = []
        for c in constraints:
            key = c.get("key")
            severity = c.get("severity")
            human = c.get("human")
            expression = c.get("expression")
            summaries.append(human_join([key, severity, human, expression], " | "))
        pieces.append("Constraints: " + " || ".join(summaries))
    return clean_text("\n".join(str(p) for p in pieces if p))

def make_artifact_url(base_url: str | None, resource: dict) -> str | None:
    if not base_url:
        return None

    resource_type = resource.get("resourceType")
    resource_id = resource.get("id")

    if not resource_type or not resource_id:
        return None

    return f"{base_url.rstrip('/')}/{resource_type}-{resource_id}.html"

####################################################################
# Functions to extract IG name and artifact urls.
####################################################################
def find_implementation_guide(root: Path) -> Optional[Dict[str, Any]]:
    """
    Finds the first ImplementationGuide resource under root.
    Prefer package/ImplementationGuide-*.json when available.
    """
    candidates = []

    for path in root.rglob("*.json"):
        resource = read_json(path)


        if not isinstance(resource, dict):
            continue

        if resource.get("resourceType") == "ImplementationGuide":
            candidates.append((path, resource))

    if not candidates:
        return None

    candidates.sort(key=lambda x: (
        0 if "ImplementationGuide-" in x[0].name else 1,
        len(str(x[0]))
    ))

    return candidates[0][1]


def ig_context_from_root(root: Path) -> Dict[str, Optional[str]]:
    """
    Extracts IG-level metadata from the ImplementationGuide resource.

    Returns:
      ig_name
      ig_title
      ig_url
      ig_version
      package_id
      base_url
    """
    
    ig = find_implementation_guide(root)
    if not ig:
        ig = find_implementation_guide(root.resolve("../package"))


    if not ig:
        return {
            "ig_name": None,
            "ig_title": None,
            "ig_url": None,
            "ig_version": None,
            "package_id": None,
            "base_url": None,
        }

    ig_url = ig.get("url")
    base_url = None

    if isinstance(ig_url, str) and ig_url:
        # Canonical is usually:
        # https://example.org/fhir/ImplementationGuide/package.id
        # Published artifact pages are usually under the canonical base.
        base_url = re.sub(r"/ImplementationGuide/[^/]+$", "", ig_url.rstrip("/"))

    return {
        "ig_name": ig.get("name"),
        "ig_title": ig.get("title") or ig.get("name"),
        "ig_url": ig_url,
        "ig_version": ig.get("version"),
        "package_id": ig.get("packageId"),
        "base_url": base_url,
    }


def artifact_url_from_resource(
    resource: Dict[str, Any],
    ig_context: Dict[str, Optional[str]],
) -> Optional[str]:
    """
    Builds the expected generated IG artifact page URL for a resource.

    Example:
      StructureDefinition-ach-daily-event-encounter.html
      ValueSet-ach-location-type.html
      CodeSystem-ach-codes.html
      Library-ach-daily.html
      Measure-ach-daily.html
    """
    base_url = ig_context.get("base_url")
    resource_type = resource.get("resourceType")
    resource_id = resource.get("id")

    if not base_url or not resource_type or not resource_id:
        return None

    return f"{base_url.rstrip('/')}/{resource_type}-{resource_id}.html"


def artifact_url_from_canonical(
    canonical: Optional[str],
    resource_type: Optional[str],
    ig_context: Dict[str, Optional[str]],
) -> Optional[str]:
    """
    Fallback when only canonical URL is available.

    Uses final canonical segment as the artifact id.
    """
    base_url = ig_context.get("base_url")

    if not base_url or not canonical or not resource_type:
        return None

    artifact_id = canonical.rstrip("/").split("/")[-1]

    if not artifact_id:
        return None

    return f"{base_url.rstrip('/')}/{resource_type}-{artifact_id}.html"


def add_common_ig_metadata(
    row: Dict[str, Any],
    resource: Optional[Dict[str, Any]],
    ig_context: Dict[str, Optional[str]],
) -> Dict[str, Any]:
    """
    Adds common IG metadata to an extracted JSONL row.
    """
    row = dict(row)

    row["ig"] = row.get("ig") or ig_context.get("ig_title") or ig_context.get("ig_name")
    row["igName"] = ig_context.get("ig_name")
    row["igTitle"] = ig_context.get("ig_title")
    row["igVersion"] = ig_context.get("ig_version")
    row["igCanonical"] = ig_context.get("ig_url")
    row["packageId"] = ig_context.get("package_id")
    row["igBaseUrl"] = ig_context.get("base_url")

    if resource:
        row["artifactUrl"] = artifact_url_from_resource(resource, ig_context)

    return row

def add_common_file_metadata(
    row: Dict[str, Any],
    ig_context: Dict[str, Optional[str]],
) -> Dict[str, Any]:
    row = dict(row)
    row["ig"] = row.get("ig") or ig_context.get("ig_title") or ig_context.get("ig_name")
    row["igName"] = ig_context.get("ig_name")
    row["igTitle"] = ig_context.get("ig_title")
    row["igVersion"] = ig_context.get("ig_version")
    row["igCanonical"] = ig_context.get("ig_url")
    row["packageId"] = ig_context.get("package_id")
    row["igBaseUrl"] = ig_context.get("base_url")
    return row


######################################################
# CQL related functions
######################################################
def find_library_resources(root: Path) -> list[dict]:
    libraries = []

    for path in root.rglob("*.json"):
        resource = read_json(path)

        if not isinstance(resource, dict):
            continue

        if resource.get("resourceType") == "Library":
            libraries.append({
                "path": path,
                "resource": resource,
            })

    return libraries


def build_cql_library_lookup(root: Path, ig_context: dict) -> dict:
    """
    Maps CQL file names and content URLs to Library metadata.
    """
    lookup = {}

    for item in find_library_resources(root):
        path = item["path"]
        library = item["resource"]

        library_id = library.get("id")
        library_name = library.get("name")
        library_title = library.get("title") or library_name or library_id
        library_url = library.get("url")
        artifact_url = artifact_url_from_resource(library, ig_context)

        for content in library.get("content", []):
            if not isinstance(content, dict):
                continue

            url = content.get("url")
            if not url:
                continue

            file_name = url.split("/")[-1]

            metadata = {
                "libraryResourceId": library_id,
                "libraryName": library_name,
                "libraryTitle": library_title,
                "libraryCanonical": library_url,
                "libraryArtifactUrl": artifact_url,
                "libraryContentUrl": url,
                "libraryContentFileName": file_name,
            }

            lookup[url] = metadata
            lookup[file_name] = metadata
            lookup[file_name.lower()] = metadata

    return lookup