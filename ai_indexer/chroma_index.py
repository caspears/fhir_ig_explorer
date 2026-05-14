from sentence_transformers import SentenceTransformer
import chromadb
import json
from openai import OpenAI
import os

openai_client = OpenAI(
    api_key=os.environ.get("OPENAI_API_KEY")
)

def clean_metadata(row):
    metadata = {}

    for key, value in row.items():
        if key == "text":
            continue

        if value is None:
            continue

        if isinstance(value, (str, int, float, bool)):
            metadata[key] = value
        elif isinstance(value, list):
            metadata[key] = ", ".join(str(v) for v in value)
        elif isinstance(value, dict):
            metadata[key] = json.dumps(value, ensure_ascii=False)
        else:
            metadata[key] = str(value)

    return metadata

def get_embeddings(texts: list[str]) -> list[list[float]]:
    response = openai_client.embeddings.create(
        model="text-embedding-3-small",
        input=texts
    )

    return [
        item.embedding
        for item in response.data
    ]

model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

client = chromadb.PersistentClient(path="index/chroma")
collection = client.get_or_create_collection("ig_chunks")

rows = []
with open("extracted/profiles.jsonl", "r", encoding="utf-8") as f:
    for line in f:
        if line.strip():
            rows.append(json.loads(line))

documents = [r["text"] for r in rows]
ids = [str(r["id"]) for r in rows]
metadatas = [clean_metadata(r) for r in rows]

BATCH_SIZE = 500

for start in range(0, len(rows), BATCH_SIZE):
    end = start + BATCH_SIZE

    batch_rows = rows[start:end]
    batch_documents = [r["text"] for r in batch_rows]
    batch_ids = [str(r["id"]) for r in batch_rows]
    batch_metadatas = [clean_metadata(r) for r in batch_rows]
    batch_embeddings = model.encode(batch_documents).tolist()
    embeddings = get_embeddings(batch_documents)

    collection.upsert(
        ids=batch_ids,
        documents=batch_documents,
        metadatas=batch_metadatas,
        embeddings=batch_embeddings
    )

    print(f"Indexed {min(end, len(rows))} of {len(rows)}")