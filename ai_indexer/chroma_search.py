from sentence_transformers import SentenceTransformer
import chromadb
import json

model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

client = chromadb.PersistentClient(path="index/chroma")
collection = client.get_or_create_collection("ig_chunks")

query = "What fields are required for NHSN Encounter?"
query_embedding = model.encode([query]).tolist()[0]

results = collection.query(
    query_embeddings=[query_embedding],
    n_results=8
)

for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
    print(meta)
    print(doc[:500])