"""
Build a local Chroma vector index from one or more JSONL extraction files.

Example:
python build_chroma_index.py \
  --input extracted/pages.jsonl extracted/profiles.jsonl extracted/terminology.jsonl extracted/examples.jsonl \
  --db-path index/chroma \
  --collection ig_chunks
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, Iterable, List
from openai import OpenAI
import os

import chromadb
from sentence_transformers import SentenceTransformer

openai_client = OpenAI(
    api_key=os.environ.get("OPENAI_API_KEY")
)

def read_jsonl(paths: List[Path]) -> List[Dict]:
    rows = []
    for path in paths:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    rows.append(json.loads(line))
    return rows


def metadata_for(row: Dict) -> Dict:
    allowed = {}
    for key in [
        "sourceType",
        "chunkType",
        "ig",
        "file",
        "url",
        "version",
        "title",
        "name",
        "profileName",
        "resourceType",
        "fhirType",
        "elementPath",
        "elementId",
        "bindingStrength",
        "valueSet",
        "pageUrl",
        "code",
        "display",
        "profileNameNormalized",
        "program",
        "reportingFrequency",
        "domain",
        "igName",
        "igTitle",
        "igVersion",
        "igCanonical",
        "packageId",
        "igBaseUrl",
        "artifactUrl",
        "effectiveConstraint",
        "isConstraint",
        "constraintKey",
        "constraintSeverity",
        "constraintHuman",
        "constraintExpression",
        "constraintSource",
         # CQL metadata
         "libraryResourceId",
        "libraryTitle",
        "libraryCanonical",
        "libraryArtifactUrl",
        "libraryContentUrl",
        "libraryContentFileName",
        "libraryName",
        "libraryVersion",
        "libraryNameNormalized",
        "defineName",
        "declarationType",
        "measureGroup",
        "program",
        "reportingFrequency",
    ]:
        value = row.get(key)
        if value is None:
            continue
        if isinstance(value, (str, int, float, bool)):
            allowed[key] = value
        elif isinstance(value, list):
            allowed[key] = ", ".join(str(v) for v in value[:20])
    return allowed

def deduplicate_rows(rows):
    seen = {}
    deduped = []

    for row in rows:
        original_id = str(row["id"])
        row_id = original_id

        if row_id in seen:
            seen[original_id] += 1
            row_id = f"{original_id}-{seen[original_id]}"
            row = dict(row)
            row["id"] = row_id
        else:
            seen[original_id] = 0

        deduped.append(row)

    return deduped

def get_embeddings(texts: list[str]) -> list[list[float]]:
    response = openai_client.embeddings.create(
        model="text-embedding-3-small",
        input=texts
    )

    return [
        item.embedding
        for item in response.data
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", nargs="+", required=True, help="JSONL files")
    parser.add_argument("--db-path", required=True, help="Chroma persistent db folder")
    parser.add_argument("--collection", default="ig_chunks")
    parser.add_argument("--embedding-model", default="sentence-transformers/all-MiniLM-L6-v2")
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()

    rows = read_jsonl([Path(p) for p in args.input])
    rows = [r for r in rows if isinstance(r.get("text"), str) and r["text"].strip()]
    rows = deduplicate_rows(rows)
    print(f"Loaded {len(rows)} rows")

    model = SentenceTransformer(args.embedding_model)
    client = chromadb.PersistentClient(path=args.db_path)

    if args.reset:
        try:
            client.delete_collection(args.collection)
        except Exception:
            pass

    collection = client.get_or_create_collection(args.collection)

    for start in range(0, len(rows), args.batch_size):
        batch = rows[start:start + args.batch_size]
        ids = [str(r["id"]) for r in batch]
        docs = [r["text"] for r in batch]
        metas = [metadata_for(r) for r in batch]
        #embeddings = model.encode(docs, show_progress_bar=False).tolist()
        embeddings = get_embeddings(docs)

        # Use upsert so repeated indexing updates the collection.
        collection.upsert(
            ids=ids,
            documents=docs,
            metadatas=metas,
            embeddings=embeddings,
        )
        print(f"Indexed {min(start + args.batch_size, len(rows))}/{len(rows)}")

    print(f"Done. Collection '{args.collection}' stored at {args.db_path}")


if __name__ == "__main__":
    main()
