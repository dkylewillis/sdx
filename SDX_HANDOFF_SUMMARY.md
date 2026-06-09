# SDX Project Handoff Summary

## Project

**SDX — Semantic Document eXchange**

GitHub repo:

```text
https://github.com/dkylewillis/sdx
```

Local repo on Kyle’s machine:

```text
C:\Users\kwillis\work\sdx
```

Current pushed branch:

```text
main
```

Latest pushed commit at time of this summary:

```text
12ec772 Add validation command and SDX workbench
```

## Concept

SDX is a portable file format and Python library for storing a document plus its semantic search layer in one file.

Tagline:

```text
Convert once. Search anywhere.
```

The `.sdx` file is currently defined as:

```text
SQLite database + standardized schema + stored document intelligence
```

The goal is to avoid requiring every downstream app to re-parse, re-chunk, re-embed, and store a document in a separate vector database.

---

## What Has Been Built

### Repository Structure

Current main source structure:

```text
sdx/
├── README.md
├── pyproject.toml
├── uv.lock
├── app/
│   └── sdx_workbench.py
├── docs/
│   ├── examples.md
│   └── sdx-spec-v0.1.md
├── src/
│   └── sdx/
│       ├── __init__.py
│       ├── cli.py
│       ├── convert.py
│       ├── document.py
│       ├── embeddings.py
│       ├── schema.py
│       └── parsers/
│           ├── __init__.py
│           └── pdf.py
└── tests/
    ├── test_cli.py
    ├── test_convert_search.py
    ├── test_schema.py
    └── test_validate.py
```

There are also local untracked files on Kyle’s machine that were **not pushed**:

```text
examples/
sdx_project_brief.md
tests/test_unit.py
```

Those appeared to be user/local artifacts, so they were intentionally left untouched.

---

## Core MVP Features Implemented

### 1. SQLite `.sdx` Schema

Implemented in:

```text
src/sdx/schema.py
```

The schema includes:

```text
sdx_metadata
documents
pages
blocks
chunks
chunk_blocks
embeddings
assets
chunks_fts
```

`chunks_fts` uses SQLite FTS5.

The schema is created with:

```python
from sdx.schema import create_schema
```

Required metadata keys are defined in:

```python
REQUIRED_METADATA_KEYS
```

Current format version:

```text
0.1
```

---

### 2. PDF Conversion

Implemented in:

```text
src/sdx/convert.py
src/sdx/parsers/pdf.py
```

Primary API:

```python
from sdx import convert

convert("input.pdf", "output.sdx")
```

CLI:

```bash
sdx convert input.pdf output.sdx
```

or from repo:

```bash
uv run python -m sdx.cli convert input.pdf output.sdx
```

Supported options:

```bash
--model hashing
--parser pymupdf
--chunk-size 500
--overlap 75
--store-original true
```

Current parser:

```text
PyMuPDF
```

PDF parsing stores:

- document record
- page text
- page width/height
- one basic block per page
- chunks
- embeddings
- original PDF in `assets`
- FTS rows

---

### 3. Chunking

Implemented in:

```text
src/sdx/convert.py
```

Function:

```python
chunk_pages(...)
```

Current strategy:

- page-aware
- paragraph-ish splitting
- chunk size configurable
- overlap configurable
- simple heading detection
- preserves `page_start`, `page_end`, and `heading_path`

Heading detection currently looks for lines beginning with things like:

```text
chapter
section
article
part
appendix
stormwater
zoning
numeric section prefixes
```

This is simple and should be improved later.

---

### 4. Embeddings

Implemented in:

```text
src/sdx/embeddings.py
```

Current default:

```text
hashing
```

This maps to:

```text
sdx-hashing-384
```

Why this exists:

- deterministic
- offline
- lightweight
- avoids needing model downloads during early tests
- good for MVP/test pipeline

Implemented helper functions:

```python
serialize_vector(...)
deserialize_vector(...)
cosine_similarity(...)
get_embedder(...)
```

Embeddings are stored as:

```text
float32 little-endian binary blob
```

`vector_format`:

```text
float32_le
```

Optional sentence-transformers path exists:

```bash
--model sentence-transformers/all-MiniLM-L6-v2
```

or:

```bash
--model all-MiniLM-L6-v2
```

But default tests use hashing.

---

### 5. Search API

Implemented in:

```text
src/sdx/document.py
```

Primary class:

```python
from sdx import SDXDocument

doc = SDXDocument.open("file.sdx")
results = doc.search("restaurant parking", mode="hybrid", top_k=10)
doc.close()
```

Supported modes:

```text
semantic
keyword
hybrid
```

#### Semantic Search

- embeds query using stored/default embedding model
- brute-force cosine similarity against stored chunk embeddings
- acceptable for v0.1 document-scale search

#### Keyword Search

- SQLite FTS5
- uses BM25
- has fallback/sanitized OR-prefix query behavior if direct query fails or returns no results

#### Hybrid Search

Current formula:

```text
semantic * 0.7 + keyword * 0.3
```

Search result class:

```python
SearchResult
```

Fields:

```python
chunk_id
score
text
page_start
page_end
heading_path
source_filename
document_id
```

SearchResult has:

```python
result.as_dict()
```

---

### 6. CLI

Implemented in:

```text
src/sdx/cli.py
```

Current commands:

```bash
sdx convert input.pdf output.sdx
sdx inspect output.sdx
sdx validate output.sdx
sdx search output.sdx "query" --mode hybrid --top-k 10
sdx workbench
```

From repo, use:

```bash
uv run python -m sdx.cli ...
```

Examples:

```bash
uv run python -m sdx.cli convert ordinance.pdf ordinance.sdx
uv run python -m sdx.cli inspect ordinance.sdx
uv run python -m sdx.cli validate ordinance.sdx
uv run python -m sdx.cli search ordinance.sdx "restaurant parking" --mode hybrid --top-k 5
```

---

## Validation Layer

### `sdx validate`

Added in commit:

```text
12ec772 Add validation command and SDX workbench
```

Python API:

```python
doc = SDXDocument.open("file.sdx")
report = doc.validate()
doc.close()
```

CLI:

```bash
sdx validate file.sdx
```

Validation currently checks:

- SQLite integrity via `PRAGMA integrity_check`
- required SDX tables
- required metadata keys
- document count
- page count
- chunk count
- embedding count equals chunk count
- FTS row count equals chunk count
- original document asset exists
- embedding blob byte length matches `model_dimension * 4`
- chunk `page_start` references exist in `pages`

Return shape:

```python
{
    "ok": bool,
    "issues": list[str],
    "warnings": list[str],
    "counts": {
        "documents": int,
        "pages": int,
        "chunks": int,
        "embeddings": int,
        "fts_rows": int,
        "assets": int,
    },
    "checks": {
        "sqlite_integrity": str,
        "required_tables_present": bool,
        "original_document_present": bool,
    },
    "metadata": dict,
}
```

Example CLI output verified:

```text
SDX validation: PASS
File: tmp-smoke.sdx
Documents: 1
Pages: 1
Chunks: 1
Embeddings: 1
FTS rows: 1
Original document: present
Issues: 0
```

---

## SDX Workbench GUI

A lightweight Streamlit testing GUI was added at:

```text
app/sdx_workbench.py
```

Launch command:

```bash
uv run --extra workbench python -m sdx.cli workbench
```

The workbench currently supports:

- upload a PDF
- convert PDF to `.sdx`
- open existing `.sdx` by path
- inspect metadata
- validate SDX file
- show validation issues
- run search queries
- choose mode:
  - hybrid
  - semantic
  - keyword
- choose top K
- display result score/page/heading/text
- browse first 100 chunks

Optional dependency added in `pyproject.toml`:

```toml
[project.optional-dependencies]
workbench = ["streamlit>=1.35"]
```

The Streamlit dependency was verified:

```text
workbench import ok 1.58.0
```

---

## Testing

### Test Command

Run:

```bash
uv run --extra dev pytest -q
```

Verified full test result:

```text
........................................................... [100%]
```

At the time of verification, there were 59 passing tests.

### Test Files

Current pushed test files:

```text
tests/test_schema.py
tests/test_convert_search.py
tests/test_cli.py
tests/test_validate.py
```

#### `test_schema.py`

Covers:

- schema creation
- required tables
- embedding serialize/deserialize round trip

#### `test_convert_search.py`

Covers:

- generating a small PDF with PyMuPDF
- converting to `.sdx`
- documents/pages/chunks/embeddings/assets/FTS populated
- inspect API
- keyword search
- semantic search
- hybrid search

#### `test_cli.py`

Covers:

- CLI convert
- CLI inspect
- CLI search

#### `test_validate.py`

Covers:

- valid `.sdx` passes validation
- missing required metadata key fails validation
- invalid embedding blob fails validation
- CLI validate outputs PASS

### Smoke Test That Was Run

A temporary PDF was generated, then:

```bash
uv run --extra dev python -m sdx.cli convert tmp-smoke.pdf tmp-smoke.sdx --model hashing
uv run --extra dev python -m sdx.cli validate tmp-smoke.sdx
uv run --extra dev python -m sdx.cli search tmp-smoke.sdx 'restaurant parking' --mode hybrid --top-k 1
```

Verified output included:

```text
Created tmp-smoke.sdx

SDX validation: PASS
Documents: 1
Pages: 1
Chunks: 1
Embeddings: 1
FTS rows: 1
Original document: present
Issues: 0

Score: 0.4429
Source: tmp-smoke.pdf
Page: 1
Heading: Chapter 110 Zoning
```

Temporary smoke files were deleted afterward.

---

## Dependencies / Tooling

Project uses:

```text
Python >= 3.10
uv
hatchling
pytest
numpy
pymupdf
```

Optional:

```text
sentence-transformers
streamlit
```

`pyproject.toml` contains:

```toml
[project.scripts]
sdx = "sdx.cli:main"
```

Optional extras:

```toml
ml = ["sentence-transformers>=2.7"]
workbench = ["streamlit>=1.35"]
dev = ["pytest>=8", "reportlab>=4"]
```

---

## Git History Created So Far

Initial MVP commit:

```text
a5f8ead Create SDX Python MVP
```

Added:

- repo scaffold
- schema
- convert
- search
- CLI
- docs
- tests

Second pushed commit:

```text
12ec772 Add validation command and SDX workbench
```

Added:

- `SDXDocument.validate()`
- `sdx validate`
- `sdx workbench`
- Streamlit workbench
- validation tests
- README updates
- workbench optional dependency

---

## Important Notes / Cautions

### 1. Do not assume `examples/` is pushed

Local status after latest push showed untracked files:

```text
?? examples/
?? sdx_project_brief.md
?? tests/test_unit.py
```

These were not committed. The next agent should inspect them before deciding whether to keep, modify, or commit.

### 2. `tests/test_unit.py` exists locally but is untracked

This file contains additional unit tests. It was not created by the prior assistant’s main commits and was left alone to avoid accidentally committing local/user work.

Next agent should inspect it and decide whether to integrate it.

### 3. Hashing embeddings are MVP-only

The hashing embedder is useful for testing and offline deterministic behavior, but it is not as semantically strong as a real embedding model.

For more realistic semantic quality, test with:

```bash
--model sentence-transformers/all-MiniLM-L6-v2
```

Potential next work:

- make model availability clearer
- add fallback warnings
- add model download docs
- benchmark retrieval quality

### 4. Current parsing/chunking is simple

The current PDF parser and chunker are intentionally basic.

Good next improvements:

- better section/heading hierarchy
- Docling parser option
- table extraction
- bounding boxes
- chunk-to-block mapping
- better citations
- page image/thumbnails

### 5. GUI is a workbench, not production viewer

The Streamlit app is intentionally a testing workbench. It is not yet a polished SDX viewer.

---

## Suggested Next Steps

### Highest Priority

#### 1. Inspect and integrate local untracked files

Check:

```bash
git status --short
```

Then inspect:

```text
examples/
sdx_project_brief.md
tests/test_unit.py
```

Decide whether to commit them.

#### 2. Add GitHub Actions CI

Add workflow:

```text
.github/workflows/ci.yml
```

Run:

```bash
uv run --extra dev pytest -q
```

on pushes and pull requests.

#### 3. Improve validation

Add checks for:

- duplicate chunk hashes
- orphan embeddings
- orphan chunk_blocks
- empty chunk text
- missing source hash
- invalid metadata values
- `default_embedding_dimension` matches embeddings
- `vector_format == float32_le`
- FTS content matches chunks

#### 4. Add `sdx export`

Useful command:

```bash
sdx export file.sdx --format json
```

Should export:

- metadata
- documents
- pages
- chunks
- maybe embeddings optionally excluded by default

#### 5. Add query evaluation harness

Useful future command:

```bash
sdx eval file.sdx expected_queries.yaml
```

Example YAML:

```yaml
- query: restaurant parking
  expected_page: 42
  expected_terms:
    - restaurant
    - parking
```

This would let Kyle test actual zoning/stormwater documents for retrieval quality.

#### 6. Improve Workbench

Potential features:

- save converted `.sdx` to selected path
- compare two embedding models
- show all three search modes side by side
- show page text around a result
- export result JSON
- show raw SQL table counts
- show original PDF download button
- add query evaluation panel

---

## Basic Commands for Next Agent

Clone/update:

```bash
git clone https://github.com/dkylewillis/sdx.git
cd sdx
```

Run tests:

```bash
uv run --extra dev pytest -q
```

Convert:

```bash
uv run python -m sdx.cli convert input.pdf output.sdx
```

Inspect:

```bash
uv run python -m sdx.cli inspect output.sdx
```

Validate:

```bash
uv run python -m sdx.cli validate output.sdx
```

Search:

```bash
uv run python -m sdx.cli search output.sdx "restaurant parking" --mode hybrid --top-k 5
```

Launch GUI:

```bash
uv run --extra workbench python -m sdx.cli workbench
```

Python API:

```python
from sdx import convert, SDXDocument

convert("input.pdf", "output.sdx")

doc = SDXDocument.open("output.sdx")
print(doc.inspect())
print(doc.validate())

for result in doc.search("restaurant parking", mode="hybrid", top_k=5):
    print(result.score, result.page_start, result.heading_path)
    print(result.text)

doc.close()
```

---

## Summary

The project now has a working Python MVP for a portable semantic document file format:

```text
PDF → .sdx SQLite file → inspect / validate / search / GUI workbench
```

The pushed repo includes a tested conversion pipeline, search API, CLI, validation command, and Streamlit workbench. The next agent should focus on CI, improving validation, integrating local example/test artifacts if appropriate, and then improving retrieval quality with better parsing/chunking/embedding workflows.
