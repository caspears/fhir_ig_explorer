from fastapi import FastAPI
from pydantic import BaseModel
#from sentence_transformers import SentenceTransformer
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import chromadb
import re
from openai import OpenAI
import os
from html import escape
import json
from pathlib import Path

openai_client = OpenAI(
    api_key=os.environ.get("OPENAI_API_KEY")
)

BASE_DIR = Path(__file__).resolve().parent

STATIC_DIR = BASE_DIR / "static"
CONFIG_DIR = BASE_DIR / "config"
INDEX_DIR = BASE_DIR / "index" / "chroma"

print(STATIC_DIR)

# What data does the ACH Monthly measure logic extract?
# What are the terminology bindings for Encounter.type in ACH Daily?

# To run
# python -m uvicorn api:app --reload --port 8001 
# Will be available at http://127.0.0.1:8001

# TODO Consider:
# redirect api.py is pointing to the a direct path

# If you ran the indexer from one folder but run uvicorn from another, this relative path may point somewhere else:

# client = chromadb.PersistentClient(path="index/chroma")

# Use an absolute path or path relative to api.py:

# from pathlib import Path
# import chromadb

# BASE_DIR = Path(__file__).resolve().parent
# CHROMA_PATH = BASE_DIR / "index" / "chroma"

# client = chromadb.PersistentClient(path=str(CHROMA_PATH))
# collection = client.get_collection("ig_chunks")

# ---------------------------------------
# Initialize API
# ---------------------------------------

app = FastAPI()

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
@app.get("/")
def home():
    return FileResponse(str(STATIC_DIR / "ask.html"))

# ---------------------------------------
# Load embedding model
# ---------------------------------------

# model = SentenceTransformer(
#     "sentence-transformers/all-MiniLM-L6-v2"
# )

# ---------------------------------------
# Open Chroma DB
# ---------------------------------------

client = chromadb.PersistentClient(
    path=str(INDEX_DIR)
)

collection = client.get_collection(
    "ig_chunks"
)

# ---------------------------------------
# Request model
# ---------------------------------------

class AskRequest(BaseModel):
    question: str
    role: str | None = None

# ---------------------------------------
# API endpoint
# ---------------------------------------

@app.post("/ask")
def ask(req: AskRequest):

    where_filter = None

    # if element_path:
    #     where_filter = {
    #         "elementPath": element_path
    #     }

    # -----------------------------------
    # Detect structured hints
    # -----------------------------------

    element_path = detect_element_path(
        req.question
    )

    detected = detect_profile_metadata(
        req.question
    )

    role_context = get_role_context(req.role)

    program = detected["program"]
    reporting_frequency = detected["reporting_frequency"]
    domain = detected["domain"]

    # -----------------------------------
    # Build vector embedding
    # -----------------------------------

    # Convert question into vector
    # embedding = model.encode(
    #     [req.question]
    # ).tolist()[0]

    embedding = get_query_embedding(req.question)

    # -----------------------------------
    # Build Chroma where filter
    # -----------------------------------
    where_filter = build_where_filter(
        element_path=element_path,
        program=program,
        reporting_frequency=reporting_frequency,
        domain=domain,
    )

    # -----------------------------------
    # Build query args
    # -----------------------------------

    query_args = {
        "query_embeddings": [embedding],
        "n_results": 25,
        "include": [
            "documents",
            "metadatas",
            "distances"
        ]
    }

    if where_filter:
        query_args["where"] = where_filter

    # -----------------------------------
    # Query Chroma
    # -----------------------------------

    results = collection.query(
        **query_args
    )
    # Search vector DB
    # results = collection.query(
    #     query_embeddings=[embedding],
    #     n_results=25, 
    #     where={"elementPath": element_path},
    #     include=[
    #         "documents",
    #         "metadatas",
    #         "distances"
    #     ]
    # )

    # Build response
    sources = build_sources(results)
    sources = rerank_sources(req.question, sources)
    sources = dedupe_sources_by_artifact_and_element(sources)
    sources = sources[:8]

    ###############################
    # Before LLM
    ###############################
    # for doc, meta in zip(
    #     results["documents"][0],
    #     results["metadatas"][0]
    # ):

    #     sources.append({
    #         "text": doc,
    #         "metadata": meta
    #     })

    # # return {
    # #     "question": req.question,
    # #     "sources": sources
    # # }

    # # return {
    # #     "question": req.question,
    # #     "answer": simple_answer(req.question, sources),
    # #     "sources": sources
    # # }

    # return {
    #     "question": req.question,
    #     "detected": {
    #         "elementPath": element_path,
    #         "program": program,
    #         "reportingFrequency": reporting_frequency,
    #         "domain": domain,
    #     },
    #     "sources": sources
    # }

    ###############################
    # LLM answer synthesis
    ###############################
    detected_info = {
    "elementPath": element_path,
    "program": program,
    "reportingFrequency": reporting_frequency,
    "domain": domain,
    }

    answer = safe_synthesize_answer(
        req.question,
        sources,
        detected=detected_info,
        role_context=role_context
    )

    answer_html = linkify_answer_text(answer, artifact_lookup)

    return {
        "question": req.question,
        "role": role_context,
        "answer": answer,
        "answerHtml": answer_html,
        "detected": detected_info,
        "sources": sources
    }



def simple_answer(question, sources):
    if not sources:
        return "I could not find relevant IG content for that question."

    first = sources[0]["metadata"]
    source_type = first.get("sourceType")
    element = first.get("elementPath")
    title = first.get("profileName") or first.get("title")

    # if source_type == "StructureDefinition":
    #     element = first.get("elementPath")
    #     title = first.get("profileName") or first.get("title")
    #     return (
    #         f"I found relevant profile guidance in {title}. "
    #         f"The most relevant element appears to be {element}. "
    #         f"Review the sources below for the exact requirement."
    #     )

    # if source_type == "ValueSet":
    #     return (
    #         "I found relevant terminology guidance. "
    #         "Review the ValueSet and CodeSystem sources below for the allowed or expected codes."
    #     )

    # return (
    #     "I found relevant IG narrative or artifact content. "
    #     "Review the summarized sources below."
    # )

    if is_terminology_question(question):
        binding = first.get("bindingStrength")
        valueset = first.get("valueSet")

        if binding or valueset:
            return (
                f"{element} in {title} has a terminology binding. "
                f"Binding strength: {binding or 'not specified'}. "
                f"ValueSet: {valueset or 'not specified'}."
            )

        return (
            f"I found {element} in {title}, but the retrieved profile chunk "
            f"does not show a terminology binding for that element."
        )

    if source_type == "StructureDefinition":
        if element:
            return (
                f"I found profile guidance in {title} for {element}. "
                f"Review the matching source details below for the exact requirement."
            )

        return (
            f"I found relevant profile guidance in {title}. "
            f"Review the source details below for the exact requirement."
        )

    return "I found relevant IG content. Review the sources below."

    
def detect_element_path(question: str):
    """
    Detect explicit FHIR element paths such as Encounter.type,
    Observation.code, Patient.birthDate, etc.
    """
    match = re.search(r"\b([A-Z][A-Za-z]+)\.([A-Za-z][A-Za-z0-9_\[\]]*)\b", question)
    if match:
        return match.group(0)
    return None


def is_terminology_question(question: str) -> bool:
    q = question.lower()
    return any(term in q for term in [
        "terminology",
        "terminologies",
        "codes",
        "code system",
        "valueset",
        "value set",
        "binding"
    ])

def detect_profile_hint(question: str):
    q = question.lower()

    hints = []

    if "ach" in q:
        hints.append("ach")

    if "daily" in q:
        hints.append("daily")

    if "monthly" in q:
        hints.append("monthly")

    if "encounter" in q:
        hints.append("encounter")

    return hints

def is_cql_question(question: str) -> bool:
    q = question.lower()
    return any(term in q for term in [
        "cql",
        "initial population",
        "initial pop",
        "measure logic",
        "population",
        "measure group",
        "extraction",
        "processing",
        "define",
        "library",
        "rules"
    ])

def detect_profile_metadata(question: str):
    q = question.lower()

    result = {
        "program": None,
        "reporting_frequency": None,
        "domain": None,
    }

    # -----------------------------------
    # Program detection
    # -----------------------------------

    if "ach" in q:
        result["program"] = "ACH"

    elif "ahs" in q:
        result["program"] = "AHS"

    # -----------------------------------
    # Frequency detection
    # -----------------------------------

    if "daily" in q:
        result["reporting_frequency"] = "daily"

    elif "monthly" in q:
        result["reporting_frequency"] = "monthly"

    elif "annual" in q:
        result["reporting_frequency"] = "annual"

    # -----------------------------------
    # Domain/resource detection
    # -----------------------------------

    if "encounter" in q:
        result["domain"] = "Encounter"

    elif "observation" in q:
        result["domain"] = "Observation"

    elif "patient" in q:
        result["domain"] = "Patient"

    #TODO add more domain.resources to hint detection

    return result

def dedupe_sources_by_artifact_and_element(sources):
    """
    Keeps the best source per artifact/profile + elementPath.
    Prefer snapshot rows over differential rows because snapshot rows
    contain the fully resolved effective constraint.
    """

    best = {}

    for source in sources:
        meta = source.get("metadata", {})

        key = (
            meta.get("url")
            or meta.get("artifactUrl")
            or meta.get("profileName")
            or meta.get("title"),
            meta.get("elementPath"),
        )

        chunk_type = meta.get("chunkType") or ""

        priority = 0

        if chunk_type == "snapshot-element":
            priority += 100

        if chunk_type == "differential-element":
            priority += 50

        if meta.get("bindingStrength"):
            priority += 25

        if meta.get("valueSet"):
            priority += 25

        if meta.get("mustSupport") in [True, "True", "true"]:
            priority += 10

        existing = best.get(key)

        if existing is None:
            best[key] = (priority, source)
            continue

        existing_priority = existing[0]

        if priority > existing_priority:
            best[key] = (priority, source)

    return [item[1] for item in best.values()]

def rerank_sources(question: str, sources: list[dict]) -> list[dict]:
    q = question.lower()
    profile_hints = detect_profile_hint(question)
    element_path = detect_element_path(question)

    ranked = []

    for source in sources:
        meta = source.get("metadata", {})
        text = source.get("text", "")

        title = (
            meta.get("profileName")
            or meta.get("title")
            or ""
        ).lower()

        element = (
            meta.get("elementPath")
            or ""
        ).lower()

        score = 0

        # Strongly prefer exact element match
        if element_path and element == element_path.lower():
            score += 100

        # Strongly prefer profile/title words from the question
        for hint in profile_hints:
            if hint in title:
                score += 25

        # Penalize contradictory temporal/program hints
        if "daily" in q and "monthly" in title:
            score -= 100

        if "monthly" in q and "daily" in title:
            score -= 100

        if "daily" in q and meta.get("reportingFrequency") == "daily":
            score += 40

        if "daily" in q and meta.get("reportingFrequency") == "monthly":
            score -= 100


        if "monthly" in q and meta.get("reportingFrequency") == "monthly":
            score += 40

        if "monthly" in q and meta.get("reportingFrequency") == "daily":
            score -= 100

        if is_terminology_question(question):
            if meta.get("bindingStrength"):
                score += 50

            if meta.get("valueSet"):
                score += 50

            if meta.get("sourceType") == "StructureDefinition" and not meta.get("valueSet"):
                score -= 25

        if meta.get("effectiveConstraint") in [True, "True", "true"]:
            score += 100

        if is_cql_question(question):
            if meta.get("sourceType") == "CQL":
                score += 80

            if "initial population" in q and meta.get("chunkType") == "cql-initial-population":
                score += 100

            if "daily" in q and meta.get("reportingFrequency") == "daily":
                score += 40

            if "daily" in q and meta.get("reportingFrequency") == "monthly":
                score -= 100
            
            if "monthly" in q and meta.get("reportingFrequency") == "monthly":
                score += 40

            if "monthly" in q and meta.get("reportingFrequency") == "daily":
                score -= 100

        # Light boost if text also contains the hints
        lower_text = text.lower()
        for hint in profile_hints:
            if hint in lower_text:
                score += 5

        ranked.append((score, source))

    ranked.sort(key=lambda x: x[0], reverse=True)

    return [source for score, source in ranked]


def build_sources(results):
    """
    Convert raw Chroma query results into a normalized
    list of source dictionaries.
    """

    sources = []

    documents = results.get("documents", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]

    for i in range(len(documents)):

        doc = documents[i]

        meta = (
            metadatas[i]
            if i < len(metadatas)
            else {}
        )

        distance = (
            distances[i]
            if i < len(distances)
            else None
        )

        sources.append({
            "text": doc,
            "metadata": meta,
            "distance": distance,
            "retrievalScore": (
                1.0 - distance
                if distance is not None
                else None
            )
        })

    return sources


def build_where_filter(
    element_path=None,
    program=None,
    reporting_frequency=None,
    domain=None,
    source_type=None,
):
    clauses = []

    if element_path:
        clauses.append({"elementPath": element_path})

    if program:
        clauses.append({"program": program})

    if reporting_frequency:
        clauses.append({"reportingFrequency": reporting_frequency})

    if domain:
        clauses.append({"domain": domain})

    if source_type:
        clauses.append({"sourceType": source_type})

    if not clauses:
        return None

    if len(clauses) == 1:
        return clauses[0]

    return {"$and": clauses}


# OpenAI Functions
def build_context_from_sources(sources, max_chars=12000):
    parts = []

    for i, source in enumerate(sources, start=1):
        meta = source.get("metadata", {})
        text = source.get("text", "")

        label_parts = [
            f"Source {i}",
            f"type={meta.get('sourceType')}",
            f"title={meta.get('title') or meta.get('profileName')}",
            f"element={meta.get('elementPath')}",
            f"valueSet={meta.get('valueSet')}",
            f"bindingStrength={meta.get('bindingStrength')}",
            f"library={meta.get('libraryName')}",
            f"define={meta.get('defineName')}",
            f"artifactUrl={meta.get('artifactUrl')}",
            f"url={meta.get('url') or meta.get('pageUrl')}",
            f"file={meta.get('file')}",
        ]

        label = " | ".join(
            p for p in label_parts
            if not p.endswith("=None")
        )

        parts.append(
            f"[{label}]\n{text}"
        )

    context = "\n\n---\n\n".join(parts)

    if len(context) > max_chars:
        context = context[:max_chars] + "\n\n[Context truncated]"

    return context

def build_artifact_lookup(collection):
    lookup = {}

    results = collection.get(
        include=["metadatas"]
    )

    for meta in results.get("metadatas", []):
        if not meta:
            continue

        artifact_url = meta.get("artifactUrl") or meta.get("libraryArtifactUrl")
        canonical = meta.get("url") or meta.get("valueSet") or meta.get("libraryCanonical")

        if canonical and artifact_url:
            # Strip version suffix if present
            base_canonical = canonical.split("|")[0]
            lookup[canonical] = artifact_url
            lookup[base_canonical] = artifact_url

        title = meta.get("profileName") or meta.get("title") or meta.get("libraryTitle")
        if title and artifact_url:
            lookup[title] = artifact_url
            lookup[title.lower()] = artifact_url

    return lookup


artifact_lookup = build_artifact_lookup(collection)

def safe_synthesize_answer(question, sources, detected=None, role_context=None):
    try:
        if not os.environ.get("OPENAI_API_KEY"):
            return simple_answer(question, sources)

        return synthesize_answer(question, sources, detected, role_context)

    except Exception as e:
        return (
            simple_answer(question, sources)
            + f"\n\n[LLM synthesis unavailable: {type(e).__name__}]"
        )

def synthesize_answer(question, sources, detected=None, role_context=None):
    if not sources:
        return (
            "I could not find relevant IG content for that question. "
            "Try using a more specific profile, element, measure group, or terminology name."
        )

    context = build_context_from_sources(sources)

    orig_system_prompt = """
You are an assistant helping hospital business analysts, informaticists, EHR managers, and implementation teams understand a FHIR Implementation Guide.

Answer only from the provided IG excerpts.
Do not invent requirements.
Do not infer conformance requirements unless they are directly supported by the excerpts.
Use plain language first, then include technical details when useful.
If the excerpts do not answer the question, say that the retrieved IG content does not answer it.
When discussing FHIR elements, include the element path, cardinality, Must Support status, binding strength, and ValueSet when available.
When discussing CQL, include the CQL library and define name when available.
End with a short "Sources used" list.
"""

    system_prompt = """
You are helping hospital personnel understand a FHIR Implementation Guide.

Answer only from the provided IG excerpts.
Do not invent requirements.
Use the selected user role to adjust framing, vocabulary, and operational guidance.
Do not change the underlying technical meaning based on the role.
Do not infer conformance requirements unless directly supported by the excerpts.
Use plain language first, then technical detail.

Format every answer exactly like this:

Short answer:
Provide a concise 1-3 sentence answer first.

Details:
Relevant technical details from the retrieved sources.
Provide supporting detail in plain language and, as appropriate for the selected role, include relevant technical details such as FHIR element paths, cardinality, Must Support, binding strength, ValueSet, CQL library, define name, Measure, or Library when available.

Operational meaning:
Explain what this means for the selected role.

Sources used:
List the specific sources used, source titles, artifact names, element paths, libraries, and URLs when available.

If the retrieved excerpts do not answer the question, say that clearly in the Short answer.
"""

    role_text = ""

    if role_context:
        role_text = f"""
Selected user role:
Role: {role_context.get("label")}
Description: {role_context.get("description")}
Response guidance: {role_context.get("answerGuidance")}
"""


    user_prompt = f"""
Question:
{question}

{role_text}

Detected search hints:
{detected or {}}

Retrieved IG excerpts:
{context}
"""

    

    response = openai_client.responses.create(
        model="gpt-4.1-mini",
        input=[
            {
                "role": "system",
                "content": system_prompt
            },
            {
                "role": "user",
                "content": user_prompt
            }
        ],
        temperature=0.1
    )

    return response.output_text


def get_query_embedding(text: str) -> list[float]:
    response = openai_client.embeddings.create(
        model="text-embedding-3-small",
        input=text
    )

    return response.data[0].embedding


def linkify_answer_text(text: str, artifact_lookup: dict) -> str:
    """
    Converts known artifact names and canonical URLs into HTML links.
    Returns safe HTML.
    """
    if not text:
        return ""

    escaped = escape(text)

    # Link canonical URLs, including versioned canonicals like url|6.1.0
    url_pattern = re.compile(
        r"(https?://[^\s\)\],]+(?:\|[A-Za-z0-9_.-]+)?)"
    )

    def replace_url(match):
        display = match.group(1)
        canonical = display.split("|")[0]
        href = artifact_lookup.get(display) or artifact_lookup.get(canonical) or canonical
        return f'<a href="{escape(href)}" target="_blank">{escape(display)}</a>'

    escaped = url_pattern.sub(replace_url, escaped)

    # Link known titles/profile names.
    # Sort longest first so "ACH Daily Event Encounter" wins over "ACH Daily".
    names = sorted(
        [k for k in artifact_lookup.keys() if not k.startswith("http") and len(k) > 4],
        key=len,
        reverse=True
    )

    for name in names[:500]:
        href = artifact_lookup.get(name)
        if not href:
            continue

        pattern = re.compile(rf"\b{re.escape(name)}\b", re.IGNORECASE)

        escaped = pattern.sub(
            lambda m: f'<a href="{escape(href)}" target="_blank">{m.group(0)}</a>',
            escaped
        )

    return escaped


BASE_DIR = Path(__file__).resolve().parent
ROLES_PATH = BASE_DIR / "config" / "roles.json"

def load_roles_config():
    with open(ROLES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

@app.get("/config/roles")
def get_roles():
    return load_roles_config()

def get_role_context(role_id: str | None):
    config = load_roles_config()
    default_role = config.get("defaultRole")

    selected_id = role_id or default_role

    for role in config.get("roles", []):
        if role.get("id") == selected_id:
            return role

    for role in config.get("roles", []):
        if role.get("id") == default_role:
            return role

    return None    