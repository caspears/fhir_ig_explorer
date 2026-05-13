REM python .\unzip_package.py --input .\dqm\package.tgz --output ./dqm/temp

python ./ai_indexer/extract_profiles_jsonl.py --input ./dqm/temp --output ./dqm/extracted/profiles.jsonl
python ./ai_indexer/extract_terminology_jsonl.py --input ./dqm/temp --output ./dqm/extracted/terminology.jsonl
python ./ai_indexer/extract_examples_jsonl.py --input ./dqm/temp --output ./dqm/extracted/examples.jsonl
python ./ai_indexer/extract_pages_jsonl.py --input ./dqm/temp/pagecontent --output ./dqm/extracted/pages.jsonl
python ./ai_indexer/extract_cql_jsonl.py --input ./dqm/temp/cql --output ./dqm/extracted/cql.jsonl

python ./ai_indexer/build_chroma_index.py --input ./dqm/extracted/pages.jsonl ./dqm/extracted/profiles.jsonl ./dqm/extracted/terminology.jsonl ./dqm/extracted/examples.jsonl ./dqm/extracted/cql.jsonl --db-path ./dqm/index/chroma --collection ig_chunks