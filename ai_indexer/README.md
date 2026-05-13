# IG RAG Extractors

These scripts extract FHIR Implementation Guide content into JSONL files suitable for local vector search / RAG indexing.

## Output files

- `pages.jsonl` - narrative guidance pages, preferably from source markdown/xml; optionally from generated HTML with boilerplate removed.
- `profiles.jsonl` - StructureDefinition profile-level and element-level chunks.
- `terminology.jsonl` - ValueSet and CodeSystem chunks.
- `examples.jsonl` - example resource chunks.

## Typical use
Run from individual repo base folder

```bash
python ../../ai_indexer/extract_profiles_jsonl.py --input output --output ./extracted/profiles.jsonl
python ../../ai_indexer/extract_terminology_jsonl.py --input output --output ./extracted/terminology.jsonl
python ../../ai_indexer/extract_examples_jsonl.py --input output --output ./extracted/examples.jsonl
python ../../ai_indexer/extract_pages_jsonl.py --input ./input/pagecontent --output ./extracted/pages.jsonl
python ../../ai_indexer/extract_cql_jsonl.py --input ./input/cql --output ./extracted/cql.jsonl
```

For narrative pages, prefer source content directories such as:
- `input/pagecontent`
- `input/includes`
- `input/intro-notes`
- `input/requirements`
- `input/images-source` if diagrams have narrative source

Use generated HTML only as a fallback:

```bash
python extract_pages_jsonl.py --input ./output --output ./extracted/pages.jsonl --mode html
```

Then run the reindexer
```bash
python ../../ai_indexer/build_chroma_index.py --input extracted/pages.jsonl extracted/profiles.jsonl extracted/terminology.jsonl extracted/examples.jsonl extracted/cql.jsonl --db-path index/chroma --collection ig_chunks
```

## Feature Considerations
TODO
It will be necessary to index specific pages of the IGs the target IG is dependent upon. These pages will need to be identified and it is preferable to index the source (md/xml) files. 
We should add a mechanism to identify specific pages (and their source files) maybe as part of links and metadata included in the target IG pages?