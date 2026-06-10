# VERA Project Brief

## Project Name

**VERA — Vector-Embedded Retrieval Archive**

## Purpose

Create a portable file format and supporting libraries that allow documents to be semantically searched without requiring each application to re-parse, re-chunk, re-embed, and store the document in a separate vector database.

The intended concept is similar to a PDF, but instead of only preserving visual/document content, a VERA file preserves the original document plus a semantic search layer.

## Core Idea

Current semantic search pipeline:

```text
Source Document
    ↓
Parse
    ↓
Chunk
    ↓
Embed
    ↓
Store in vector database
    ↓
Search
```

Proposed VERA workflow:

```text
Source Document
    ↓
Convert once
    ↓
.vera file
    ↓
Search anywhere
```

The expensive ingestion process happens once during conversion. After that, any compatible application can open the `.vera` file and perform semantic, keyword, or hybrid search locally.

## High-Level Definition

An `.vera` file is a **portable vector-embedded retrieval archive**.

For version 0.1, define `.vera` as:

```text
VERA = SQLite database + required schema + stored document intelligence
```

The `.vera` file should be a normal SQLite database with a custom file extension and a standardized schema.

## Primary Goals

1. Preserve the original document.
2. Store parsed text.
3. Store page/block/chunk structure.
4. Store semantic embeddings.
5. Store citation/location references.
6. Support keyword search.
7. Support semantic search.
8. Support hybrid search.
9. Make the file portable and application-independent.
10. Avoid requiring a separate vector database for document-scale search.

## Non-Goals for Version 0.1

Do not attempt to solve these in the first version:

1. Multi-user server concurrency.
2. Distributed search across millions of chunks.
3. Full replacement for Qdrant, Pinecone, Weaviate, etc.
4. Perfect OCR for all PDFs.
5. Perfect table extraction.
6. Complex knowledge graph generation.
7. Multiple embedding models in one file.
8. Encryption/permissions.
9. Browser-based visual viewer.
10. Incremental remote synchronization.

These can be future extensions.

## Intended First Use Case

The first real-world target use case is regulatory, ordinance, engineering, and technical document search.

Examples:

- County zoning ordinance
- Stormwater manual
- Development regulations
- Engineering design manual
- Permit checklist
- Technical report
- PDF plan review document

Example search questions:

```text
What are the parking requirements for a restaurant?
What are the stream buffer requirements?
When is detention required?
What driveway spacing is required?
What are the landscape buffer requirements?
```

## MVP Workflow

The first working version should support:

```bash
vera convert input.pdf output.vera
vera inspect output.vera
vera search output.vera "minimum parking required for restaurant"
```

Python API:

```python
from vera import convert
from vera import VeraDocument

convert("ordinance.pdf", "ordinance.vera")

doc = VeraDocument.open("ordinance.vera")
results = doc.search("minimum parking required for restaurant")
```

## Recommended Tech Stack

### Language

Python first.

### File Container

SQLite.

### Parsing

Start with one or more of the following:

- PyMuPDF
- pdfplumber
- Docling
- unstructured
- pypdf

The parser should be abstracted so the implementation can change later.

### Embeddings

For local/offline MVP:

- `sentence-transformers/all-MiniLM-L6-v2`

Possible future models:

- BGE-small
- BGE-large
- E5
- Jina
- OpenAI text-embedding models
- Voyage embeddings

### Keyword Search

Use SQLite FTS5.

### Vector Search

For v0.1, brute-force cosine similarity is acceptable.

Later options:

- sqlite-vec
- sqlite-vss
- hnswlib
- faiss
- Qdrant export/import

## Proposed Repository Structure

```text
vera/
├── README.md
├── pyproject.toml
├── src/
│   └── vera/
│       ├── __init__.py
│       ├── cli.py
│       ├── convert.py
│       ├── document.py
│       ├── schema.py
│       ├── search.py
│       ├── embeddings.py
│       ├── parsers/
│       │   ├── __init__.py
│       │   └── pdf.py
│       └── utils.py
├── tests/
│   ├── test_convert.py
│   ├── test_search.py
│   └── test_schema.py
└── docs/
    ├── vera-spec-v0.1.md
    └── examples.md
```

## VERA Schema v0.1

The following tables should be created in every `.vera` file.

### `vera_metadata`

Stores VERA file-level metadata.

Suggested fields:

```sql
CREATE TABLE vera_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
```

Required keys:

```text
format_name
format_version
created_at
created_by
creator_library
source_file_name
source_file_hash
source_mime_type
default_embedding_model
default_embedding_dimension
chunking_strategy
parser_name
parser_version
```

### `documents`

Stores document-level records.

```sql
CREATE TABLE documents (
    document_id TEXT PRIMARY KEY,
    title TEXT,
    source_filename TEXT,
    source_mime_type TEXT,
    source_hash TEXT,
    page_count INTEGER,
    created_at TEXT
);
```

For v0.1, the file may contain only one document, but the schema should allow multiple documents later.

### `pages`

Stores page-level text and geometry.

```sql
CREATE TABLE pages (
    page_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    page_number INTEGER NOT NULL,
    width REAL,
    height REAL,
    text TEXT,
    FOREIGN KEY (document_id) REFERENCES documents(document_id)
);
```

### `blocks`

Stores layout or structural blocks extracted from the document.

```sql
CREATE TABLE blocks (
    block_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    page_id TEXT,
    page_number INTEGER,
    block_type TEXT,
    text TEXT,
    bbox_json TEXT,
    heading_level INTEGER,
    sort_order INTEGER,
    FOREIGN KEY (document_id) REFERENCES documents(document_id),
    FOREIGN KEY (page_id) REFERENCES pages(page_id)
);
```

Suggested `block_type` values:

```text
heading
paragraph
list_item
table
image
caption
header
footer
unknown
```

### `chunks`

Stores the primary searchable text units.

```sql
CREATE TABLE chunks (
    chunk_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    page_start INTEGER,
    page_end INTEGER,
    heading_path TEXT,
    text TEXT NOT NULL,
    token_count INTEGER,
    chunk_hash TEXT,
    sort_order INTEGER,
    FOREIGN KEY (document_id) REFERENCES documents(document_id)
);
```

### `chunk_blocks`

Optional mapping table connecting chunks to source blocks.

```sql
CREATE TABLE chunk_blocks (
    chunk_id TEXT NOT NULL,
    block_id TEXT NOT NULL,
    PRIMARY KEY (chunk_id, block_id),
    FOREIGN KEY (chunk_id) REFERENCES chunks(chunk_id),
    FOREIGN KEY (block_id) REFERENCES blocks(block_id)
);
```

### `embeddings`

Stores vector embeddings for chunks.

For v0.1, embeddings can be stored as binary blobs using float32 arrays.

```sql
CREATE TABLE embeddings (
    embedding_id TEXT PRIMARY KEY,
    chunk_id TEXT NOT NULL,
    model_name TEXT NOT NULL,
    model_dimension INTEGER NOT NULL,
    vector BLOB NOT NULL,
    vector_format TEXT NOT NULL,
    created_at TEXT,
    FOREIGN KEY (chunk_id) REFERENCES chunks(chunk_id)
);
```

Suggested `vector_format`:

```text
float32_le
```

### `assets`

Stores original source document and optional extracted assets.

```sql
CREATE TABLE assets (
    asset_id TEXT PRIMARY KEY,
    document_id TEXT,
    asset_type TEXT NOT NULL,
    mime_type TEXT,
    filename TEXT,
    data BLOB,
    hash TEXT,
    FOREIGN KEY (document_id) REFERENCES documents(document_id)
);
```

Suggested `asset_type` values:

```text
original_document
page_image
extracted_image
table_json
table_csv
other
```

### `search_index`

For v0.1, use SQLite FTS5.

```sql
CREATE VIRTUAL TABLE chunks_fts USING fts5(
    chunk_id UNINDEXED,
    text,
    heading_path
);
```

The converter should populate this from the `chunks` table.

## Search Requirements

The search API should support at least three modes:

```python
doc.search(query, mode="semantic")
doc.search(query, mode="keyword")
doc.search(query, mode="hybrid")
```

### Semantic Search

1. Embed the user query with the same embedding model used for the stored chunk embeddings.
2. Compare query vector to chunk vectors.
3. Return top-k results ranked by similarity.

For v0.1, brute-force cosine similarity is acceptable.

### Keyword Search

Use SQLite FTS5.

### Hybrid Search

For v0.1, combine semantic and keyword scores with a simple weighted formula:

```text
hybrid_score = (semantic_score * 0.7) + (keyword_score * 0.3)
```

This can be adjusted later.

## Search Result Format

Every search result should be citation-ready.

Example Python result:

```python
{
    "chunk_id": "chunk_000123",
    "score": 0.87,
    "text": "Restaurants shall provide one parking space per...",
    "page_start": 42,
    "page_end": 43,
    "heading_path": "Chapter 110 > Zoning > Parking",
    "source_filename": "coweta-ordinance.pdf",
    "document_id": "doc_001"
}
```

CLI output should include:

```text
Score: 0.87
Source: coweta-ordinance.pdf
Page: 42
Heading: Chapter 110 > Zoning > Parking

Restaurants shall provide one parking space per...
```

## Chunking Strategy

For v0.1:

1. Prefer heading-aware chunks when headings are available.
2. Otherwise chunk by paragraphs.
3. Target chunk size: 300–800 tokens.
4. Use overlap of approximately 50–100 tokens.
5. Preserve page references.
6. Preserve heading path when available.

Chunks should not lose citation information.

## Important Design Principles

### 1. Convert Once, Search Anywhere

The VERA file should contain enough information to avoid repeating the ingestion pipeline.

### 2. Preserve Source Truth

The original document should be stored in the file. Search results should always point back to source pages or locations.

### 3. Be Transparent

The file must state which parser, chunking strategy, and embedding model were used.

### 4. Avoid Lock-In

The format should not depend on one embedding provider, one vector database, or one parser.

### 5. Be Useful Before It Is Perfect

A simple version that can convert PDFs and search them locally is more valuable than a perfect design that never ships.

## CLI Requirements

Implement a command-line interface.

### `vera convert`

```bash
vera convert input.pdf output.vera
```

Options:

```bash
--model all-MiniLM-L6-v2
--parser pymupdf
--chunk-size 500
--overlap 75
--store-original true
```

### `vera inspect`

```bash
vera inspect output.vera
```

Should print:

```text
File: output.vera
Format: VERA v0.1
Source: input.pdf
Pages: 128
Chunks: 642
Embedding model: sentence-transformers/all-MiniLM-L6-v2
Embedding dimensions: 384
Parser: pymupdf
Created: 2026-06-09T...
```

### `vera search`

```bash
vera search output.vera "stream buffer requirements"
```

Options:

```bash
--mode semantic
--mode keyword
--mode hybrid
--top-k 10
```

### `vera export`

Optional for v0.1, but useful:

```bash
vera export output.vera --format json
```

Could export chunks and metadata.

## Python API Requirements

Minimum API:

```python
from vera import convert
from vera import VeraDocument

convert("input.pdf", "output.vera")

doc = VeraDocument.open("output.vera")
results = doc.search("stream buffer requirements", mode="hybrid", top_k=10)

for result in results:
    print(result.text)
    print(result.page_start)
    print(result.heading_path)
```

Suggested classes:

```python
class VeraDocument:
    @classmethod
    def open(cls, path: str) -> "VeraDocument":
        ...

    def search(self, query: str, mode: str = "hybrid", top_k: int = 10):
        ...

    def inspect(self):
        ...

    def close(self):
        ...
```

## Acceptance Criteria for MVP

The MVP is complete when:

1. A PDF can be converted to `.vera`.
2. The `.vera` file is valid SQLite.
3. The original PDF is stored in the `assets` table.
4. Parsed page text is stored.
5. Chunks are created and stored.
6. Embeddings are created and stored.
7. FTS keyword index is populated.
8. Semantic search returns relevant chunks.
9. Keyword search returns relevant chunks.
10. Hybrid search returns relevant chunks.
11. Search results include source filename, page number, heading path when available, score, and text.
12. CLI commands `convert`, `inspect`, and `search` work.
13. Python API can open and search a VERA file.
14. Basic tests exist.

## Testing Plan

Create tests for:

1. Schema creation.
2. PDF conversion.
3. Metadata population.
4. Original document storage.
5. Chunk creation.
6. Embedding serialization/deserialization.
7. Keyword search.
8. Semantic search.
9. Hybrid search.
10. CLI smoke tests.

Use a small sample PDF in tests.

## Possible Future Features

### VERA v0.2

- sqlite-vec support
- better table extraction
- page thumbnails
- richer citations with bounding boxes
- multiple documents per VERA
- JSON export/import
- Qdrant import/export

### VERA v0.3

- multiple embedding models
- incremental update system
- document collections
- summaries
- topic tags
- entity extraction
- section-level summaries

### VERA v1.0

- formal specification
- validation tool
- viewer application
- browser support
- plugin system
- signed files
- encrypted files
- cross-document semantic links
- knowledge graph layer

## Development Guidance

Build the project in small pieces.

Recommended order:

1. Create SQLite schema.
2. Build `vera init` or schema creation function.
3. Build simple PDF parser.
4. Store source document and parsed pages.
5. Create simple chunks.
6. Add embeddings.
7. Add FTS5 index.
8. Add semantic search.
9. Add keyword search.
10. Add hybrid search.
11. Add CLI.
12. Add tests.
13. Refactor after it works.

Avoid overengineering the first version.

## Naming

File extension:

```text
.vera
```

Name:

```text
Vector-Embedded Retrieval Archive
```

Short description:

```text
VERA is a portable vector-embedded retrieval archive that stores a document, its parsed structure, embeddings, indexes, and citation metadata in one searchable file.
```

Tagline:

```text
Convert once. Search anywhere.
```

## Final Instruction to Agent

Create a working Python MVP for the VERA format.

Focus on making a single PDF convertible to a searchable `.vera` SQLite file. Prioritize a working end-to-end pipeline over advanced features. The first milestone is a CLI and Python API that can convert a PDF, inspect the resulting VERA file, and perform semantic, keyword, and hybrid search with page-aware citations.
