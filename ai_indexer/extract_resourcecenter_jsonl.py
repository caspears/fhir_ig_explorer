from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, Optional
import os
import requests
from markdownify import markdownify as md
from bs4 import BeautifulSoup

from common_jsonl import (
    clean_text,
    chunk_text,
    stable_id,
    write_jsonl,
    strip_markdown_noise,
    ig_context_from_root,
)


# Example:
# RESOURCE_CENTER_URLS = {
#     "dqm-home": "https://www.cdc.gov/nhsn/fhirportal/dqm/",
#     "about": "https://www.cdc.gov/nhsn/fhirportal/about.html",
#     "fhir-ready": "https://www.cdc.gov/nhsn/fhirportal/dqm/fhir-ready.html",
# }
RESOURCE_CENTER_URLS: Dict[str, str] = {
    'dqm-home': 'https://www.cdc.gov/nhsn/fhirportal/dqm/',
    'about': 'https://www.cdc.gov/nhsn/fhirportal/about.html',
    'fhir-ready': 'https://www.cdc.gov/nhsn/fhirportal/dqm/fhir-ready.html',
    'faq': 'https://www.cdc.gov/nhsn/fhirportal/faqs.html'}



def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"https?://", "", value)
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-+", "-", value)
    return value.strip("-")


def title_from_markdown(path: Path, text: str, page_key: str) -> str:
    front_matter_title = re.search(
        r"(?ms)^---\s*.*?^title:\s*[\"']?([^\"'\n]+)[\"']?.*?^---\s*",
        text,
    )

    if front_matter_title:
        return clean_text(front_matter_title.group(1))

    heading = re.search(r"(?m)^\s*#\s+(.+?)\s*$", text)

    if heading:
        return clean_text(heading.group(1))

    return page_key.replace("-", " ").replace("_", " ").title()


def derive_resource_center_metadata(page_key: str, title: str, url: str, text: str) -> Dict[str, Any]:
    combined = f"{page_key} {title} {url} {text}".lower()

    page_category = None
    audience = []

    if any(term in combined for term in ["ready", "onboard", "onboarding", "prepare", "preparation"]):
        page_category = "onboarding"

    elif any(term in combined for term in ["about", "overview", "what is", "resource center"]):
        page_category = "overview"

    elif any(term in combined for term in ["role", "responsibilit", "stakeholder"]):
        page_category = "roles-responsibilities"

    elif any(term in combined for term in ["terminology", "loinc", "snomed", "rxnorm", "mapping"]):
        page_category = "terminology"

    elif any(term in combined for term in ["faq", "frequently asked"]):
        page_category = "faq"

    if any(term in combined for term in ["implementation coordinator", "coordinator"]):
        audience.append("implementation-coordinator")

    if any(term in combined for term in ["facility administrator", "digital reporting plan"]):
        audience.append("facility-administrator")

    if any(term in combined for term in ["ehr", "fhir server", "api", "vendor", "information technology", " it "]):
        audience.append("ehr-vendor-team")

    if any(term in combined for term in ["laboratory", "lab", "loinc"]):
        audience.append("laboratory-data-team")

    if any(term in combined for term in ["medication", "rxnorm", "pharmacy"]):
        audience.append("medication-data-team")

    if any(term in combined for term in ["executive", "leadership", "approval", "governance"]):
        audience.append("executive-informatics")

    # Preserve order while removing duplicates.
    audience = list(dict.fromkeys(audience))

    return {
        "pageCategory": page_category or "resource-center-guidance",
        "audience": audience,
    }


def normalize_markdown(text: str) -> str:
    text = strip_markdown_noise(text)

    # Remove repeated CDC/templating remnants if present.
    text = re.sub(r"(?im)^\s*(home|menu|search|close|print|share)\s*$", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return clean_text(text)


def find_markdown_for_page(resource_folder: Path, page_key: str, url: str) -> Optional[Path]:
    candidates = [
        resource_folder / f"{page_key}.md",
        resource_folder / f"{page_key}.markdown",
        resource_folder / f"{slugify(page_key)}.md",
        resource_folder / f"{slugify(url)}.md",
        resource_folder / f"{Path(url).stem}.md",
    ]

    for candidate in candidates:
        if candidate.exists():
            return candidate

    # Fallback: look for key in filename.
    key_slug = slugify(page_key)

    for path in resource_folder.glob("*.md"):
        if key_slug in path.stem.lower():
            return path

    return None


def extract_resource_center_rows(
    resource_folder: Path,
    url_map: Dict[str, str],
    ig_context: Dict[str, Optional[str]],
    max_chars: int,
) -> Iterable[Dict[str, Any]]:
    rows = []

    for page_key, url in url_map.items():
        path = find_markdown_for_page(resource_folder, page_key, url)

        if not path:
            print(f"WARNING: No markdown file found for {page_key}: {url}")
            continue

        raw = path.read_text(encoding="utf-8", errors="ignore")
        title = title_from_markdown(path, raw, page_key)
        text = normalize_markdown(raw)

        if len(text) < 100:
            print(f"WARNING: Skipping very small resource center page: {path}")
            continue

        derived = derive_resource_center_metadata(page_key, title, url, text)

        chunks = chunk_text(
            text,
            max_chars=max_chars,
            overlap_chars=200,
            min_chars=150,
        )

        for chunk_index, chunk in enumerate(chunks):
            row = {
                "id": stable_id("resource-center", page_key, url, chunk_index),
                "sourceType": "ResourceCenterPage",
                "chunkType": "resource-center-page",
                "ig": ig_context.get("ig_title") or ig_context.get("ig_name") or "NHSN dQM",
                "igName": ig_context.get("ig_name"),
                "igTitle": ig_context.get("ig_title"),
                "igVersion": ig_context.get("ig_version"),
                "igCanonical": ig_context.get("ig_url"),
                "packageId": ig_context.get("package_id"),
                "pageKey": page_key,
                "title": title,
                "url": url,
                "pageUrl": url,
                "artifactUrl": url,
                "file": str(path),
                "pageCategory": derived["pageCategory"],
                "audience": derived["audience"],
                "chunkIndex": chunk_index,
                "text": clean_text(
                    f"Resource Center Page: {title}\n"
                    f"Page key: {page_key}\n"
                    f"URL: {url}\n"
                    f"Category: {derived['pageCategory']}\n"
                    f"Audience: {', '.join(derived['audience'])}\n\n"
                    f"{chunk}"
                ),
            }

            rows.append(row)

    return rows


def load_url_map(path: Optional[str]) -> Dict[str, str]:
    if not path:
        return RESOURCE_CENTER_URLS

    data = json.loads(Path(path).read_text(encoding="utf-8"))

    if not isinstance(data, dict):
        raise ValueError("URL map JSON must be an object in the form {\"page-key\": \"url\"}")

    return {str(k): str(v) for k, v in data.items()}


def download_resource_content_markdown(url_map: Dict[str, str], resource_folder: Path):
    for key, value in url_map.items():
        response = requests.get(value)

    # Check if the request was successful
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')

            # Find all divs with the specific class
            divs = soup.find_all('div', class_='syndicate')

            heads = soup.find_all('head')
            #print(head)
            new_html = "<html><body>"

            # Shouldn't have more than one head, but hey.
            for head in heads:
                new_html = new_html + str(head) #print(div.text) # or div.get_text()

            for div in divs:
                new_html = new_html + str(div) #print(div.text) # or div.get_text()
            
            new_html = new_html + "</body></html>"

            
            #with open(key + ".html", "w", encoding="utf-8") as file:
            #    file.write(new_html)
            # 2. Convert the HTML to Markdown
            markdown_content = md(new_html, heading_style="ATX")

            with open(str(resource_folder) + '/' + key + ".md", 'w', encoding='utf-8') as f:
                f.write(markdown_content)



def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Folder containing ResourceCenterPage markdown folder, or the ResourceCenterPage folder itself",)
    parser.add_argument("--output", required=True, help="Output resource_center.jsonl",)
    parser.add_argument("--url-map", default=None, help="Optional JSON file containing {page-key: url}",)
    parser.add_argument("--max-chars", type=int, default=1800, help="Max characters per chunk",)

    args = parser.parse_args()

    root = Path(args.input)

    if root.name.lower() == "resourcecenterpage":
        resource_folder = root
        ig_root = root.parent / "package"
    else:
        resource_folder = root / "ResourceCenterPage"
        ig_root = root / "package"

    if not resource_folder.exists():
        #raise FileNotFoundError(f"ResourceCenterPage folder not found: {resource_folder}")
        os.makedirs(resource_folder, exist_ok=True)


    ig_context = ig_context_from_root(ig_root)
    url_map = load_url_map(args.url_map)

    download_resource_content_markdown(url_map, resource_folder=resource_folder)

    rows = extract_resource_center_rows(
        resource_folder=resource_folder,
        url_map=url_map,
        ig_context=ig_context,
        max_chars=args.max_chars,
    )

    count = write_jsonl(Path(args.output), rows)

    print(f"Wrote {count} rows to {args.output}")


if __name__ == "__main__":
    main()