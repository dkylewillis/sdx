# VERA Format Specification

**Version:** 0.1 (draft)
**Status:** Experimental — the schema may change before 1.0
**License:** Apache-2.0

VERA (Vector-Embedded Retrieval Archive) is a portable, single-file format for semantically searchable documents. An `.vera` file carries a source document together with its parsed structure, text chunks, vector embeddings, keyword index, extracted figures, and citation metadata, so that any compatible application can search the document without re-parsing, re-chunking, or re-embedding it.

This document specifies what a conforming **writer** must produce and what a conforming **reader** can rely on. The reference implementation is the [`vera` Python package](https://github.com/dkylewillis/vera).

The key words MUST, SHOULD, and MAY are to be interpreted as described in RFC 2119.

---

## 1. Container

- A VERA file **MUST** be a valid SQLite 3 database.
- The recommended file extension is `.vera`.
- The database **MUST** contain the tables defined in Section 3 and **MUST** pass `PRAGMA integrity_check`.
- The FTS index (`chunks_fts`) requires SQLite compiled with the FTS5 extension (default in virtually all distributions).
- Readers **MUST** ignore unrecognized tables, columns, and metadata keys. Writers **MAY** add their own, but extension tables SHOULD be prefixed (e.g. `x_myapp_*`) to avoid collisions with future spec versions.

## 2. Metadata (`vera_metadata`)

```sql
CREATE TABLE vera_metadata (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
```

The following keys **MUST** be present:

| Key | Meaning | Example |
|-----|---------|---------|
| `format_name` | Always `VERA` | `VERA` |
| `format_version` | Spec version of this file | `0.1` |
| `created_at` | ISO-8601 UTC timestamp | `2026-06-09T19:52:31+00:00` |
| `created_by` | Tool or user that created the file | `vera-cli` |
| `creator_library` | Library name/version | `vera 0.1.0` |
| `source_file_name` | Original filename | `ordinance.pdf` |
| `source_file_hash` | SHA-256 hex digest of the source file | `9f86d08…` |
| `source_mime_type` | MIME type of the source | `application/pdf` |
| `default_embedding_model` | Model used for stored embeddings (Section 6) | `vera-hashing-384` |
| `default_embedding_dimension` | Vector dimension | `384` |
| `chunking_strategy` | Writer-defined description of chunking | `heading_block_sliding_window:500:75` |
| `parser_name` | Parser used | `pymupdf` |
| `parser_version` | Parser version | `1.24.0` |

`chunking_strategy`, `parser_name`, and `parser_version` are informational: readers **MUST NOT** need them to search, but writers **MUST** record them so files are self-describing (the transparency principle).

## 3. Required tables

Every VERA file **MUST** contain these tables (writers create them exactly as below; readers SHOULD tolerate additional columns):

```sql
CREATE TABLE documents (
    document_id      TEXT PRIMARY KEY,
    title            TEXT,
    source_filename  TEXT,
    source_mime_type TEXT,
    source_hash      TEXT,
    page_count       INTEGER,
    created_at       TEXT
);

CREATE TABLE pages (
    page_id     TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(document_id),
    page_number INTEGER NOT NULL,   -- 1-based
    width       REAL,               -- points
    height      REAL,
    text        TEXT
);

CREATE TABLE blocks (
    block_id      TEXT PRIMARY KEY,
    document_id   TEXT NOT NULL REFERENCES documents(document_id),
    page_id       TEXT REFERENCES pages(page_id),
    page_number   INTEGER,
    block_type    TEXT,              -- see Section 4
    text          TEXT,
    bbox_json     TEXT,              -- JSON [x0, y0, x1, y1] in page points, origin top-left
    heading_level INTEGER,           -- 1 (highest) .. 6, headings only
    sort_order    INTEGER            -- reading order within the document
);

CREATE TABLE chunks (
    chunk_id     TEXT PRIMARY KEY,
    document_id  TEXT NOT NULL REFERENCES documents(document_id),
    page_start   INTEGER,            -- 1-based, inclusive
    page_end     INTEGER,
    heading_path TEXT,               -- "Chapter 110 > Article 5 > Parking"
    text         TEXT NOT NULL,
    token_count  INTEGER,            -- approximate (whitespace tokens acceptable)
    chunk_hash   TEXT,
    sort_order   INTEGER
);

CREATE TABLE chunk_blocks (
    chunk_id TEXT NOT NULL REFERENCES chunks(chunk_id),
    block_id TEXT NOT NULL REFERENCES blocks(block_id),
    PRIMARY KEY (chunk_id, block_id)
);

CREATE TABLE embeddings (
    embedding_id    TEXT PRIMARY KEY,
    chunk_id        TEXT NOT NULL REFERENCES chunks(chunk_id),
    model_name      TEXT NOT NULL,
    model_dimension INTEGER NOT NULL,
    vector          BLOB NOT NULL,
    vector_format   TEXT NOT NULL,   -- "float32_le" in v0.1
    created_at      TEXT
);

CREATE TABLE assets (
    asset_id    TEXT PRIMARY KEY,
    document_id TEXT REFERENCES documents(document_id),
    asset_type  TEXT NOT NULL,       -- see Section 5
    mime_type   TEXT,
    filename    TEXT,
    data        BLOB,
    hash        TEXT
);

CREATE VIRTUAL TABLE chunks_fts USING fts5(
    chunk_id UNINDEXED,
    text,
    heading_path
);
```

Integrity requirements (1–5 enforced by `vera validate`):

1. At least one row in `documents`, `pages`, and `chunks`.
2. Exactly one embedding per chunk for the default model: `COUNT(embeddings) = COUNT(chunks)`.
3. One FTS row per chunk: `COUNT(chunks_fts) = COUNT(chunks)`.
4. Exactly one asset with `asset_type = 'original_document'` containing the unmodified source bytes.
5. Every `chunks.page_start` **MUST** reference an existing page number.
6. Writers **SHOULD NOT** let chunks span page boundaries (`page_start = page_end`); this keeps citations precise. Readers **MUST** still handle multi-page chunks.

In v0.1 a file contains exactly one document. The schema permits multiple; readers SHOULD NOT assume a single document, writers **MUST** write exactly one.

## 4. Blocks

`block_type` **MUST** be one of:

```text
heading   paragraph   caption   image   list_item   table   header   footer   unknown
```

v0.1 writers are only required to emit `heading`, `paragraph`, `caption`, and `image`; the rest are reserved.

- **heading** — `heading_level` 1–6, where 1 is the most prominent. `text` is the heading text with whitespace collapsed.
- **paragraph** — body text.
- **caption** — a text block that labels a nearby figure or table (e.g. `Figure 3: Detention pond sizing diagram`). Caption text **MUST** also be included in chunk text so figures are searchable.
- **image** — an extracted raster image. `text` is empty. Each image block **MUST** have a companion asset whose `asset_id` is `'asset_' || block_id` (Section 5).

`bbox_json`, when present, is a JSON array `[x0, y0, x1, y1]` in page coordinate points with the origin at the top-left of the page.

## 5. Assets

`asset_type` **MUST** be one of:

```text
original_document   page_image   extracted_image   table_json   table_csv   other
```

- `original_document` — required, exactly one. `data` holds the unmodified source file bytes; `hash` is its SHA-256 hex digest and **MUST** equal `vera_metadata.source_file_hash`.
- `extracted_image` — one per `image` block, with `asset_id = 'asset_' || block_id`. This naming convention is how readers join figures to their location and nearby captions without an additional table.

## 6. Embeddings

- `vector` is the raw little-endian IEEE-754 float32 array (`vector_format = "float32_le"`); its byte length **MUST** equal `4 × model_dimension`.
- Vectors **SHOULD** be L2-normalized at write time. Readers **MUST NOT** assume normalization and SHOULD compute full cosine similarity.
- All stored embeddings in v0.1 use the single model named in `default_embedding_model`. Multiple models per file are reserved for a future version.

### 6.1 Model portability contract

Semantic search requires embedding the **query with the same model** used at write time. `model_name` values:

- Names beginning `sentence-transformers/` refer to the corresponding [Sentence-Transformers](https://www.sbert.net/) model with `normalize_embeddings=True`.
- `vera-hashing-384` is VERA's built-in zero-dependency lexical embedder, defined normatively below so it can be reimplemented in any language.
- Other names are writer-defined; readers that do not recognize a model can still perform keyword search (see conformance levels, Section 8).

### 6.2 The `vera-hashing-384` embedder (normative)

A deterministic feature-hashing embedder. For input text:

1. Lowercase the text and extract tokens with the regex `[A-Za-z0-9_]+`.
2. Start with a zero vector of dimension 384 (float32).
3. For each token:
   - `digest = BLAKE2b(token_utf8, digest_size=8)` (8 bytes).
   - `bucket = little_endian_uint32(digest[0..4]) mod 384`.
   - `sign = +1.0` if `digest[4]` is even, else `−1.0`.
   - `vector[bucket] += sign`.
4. L2-normalize the vector (leave as zeros if the norm is 0).

Identical text always yields an identical vector; the same algorithm embeds queries at search time.

## 7. Search semantics (informative)

How a reader ranks results is implementation-defined. The reference implementation provides three modes and the following is **recommended** behavior:

- **keyword** — FTS5 `MATCH` over `chunks_fts`, ranked by `bm25()`. Fall back to OR-joined prefix terms (`term*`) when the raw query is not valid FTS syntax.
- **semantic** — brute-force cosine similarity between the query vector and every stored chunk vector. At document scale (≤ ~10⁴ chunks) this is fast enough without an ANN index.
- **hybrid** — min-max normalize both score sets to [0, 1] over their candidate pools, then `score = 0.5 × semantic + 0.5 × keyword`. Raw bm25 and cosine scores are on incomparable scales and **MUST NOT** be combined without normalization.

Search results SHOULD be citation-ready: chunk text, score, `page_start`/`page_end`, `heading_path`, and `source_filename`. Readers MAY also return adjacent chunk context, such as chunks before and after a ranked hit, using `chunks.sort_order` within the same `document_id`.

### 7.1 Visual grounding (informative)

Because `chunk_blocks` links every chunk to its contributing blocks, and blocks carry `bbox_json` plus a `page_id` into `pages` (which stores `width`/`height`), readers can resolve a chunk to its **highlight regions** — the page numbers and bounding boxes of the text it came from:

```sql
SELECT b.page_number, b.bbox_json, p.width, p.height
FROM chunk_blocks cb
JOIN blocks b ON b.block_id = cb.block_id
LEFT JOIN pages p ON p.page_id = b.page_id
WHERE cb.chunk_id = ?
ORDER BY b.sort_order;
```

Coordinates are in page points with the origin at the **top-left** (Section 3); viewers rendering with a bottom-left origin (e.g. PDF.js) must flip the y-axis using the page height. Regions are block-granular: a chunk that starts or ends mid-block maps to the whole block's bbox, so a highlight MAY cover slightly more text than the chunk itself.

## 8. Conformance levels

| Level | Requirements | Needs |
|-------|--------------|-------|
| **1 — Basic reader** | Open the file, read metadata/chunks/pages, keyword search via FTS5 | SQLite only — no ML stack |
| **2 — Semantic reader** | Level 1 + embed queries with `default_embedding_model` and rank by cosine similarity | Embedding model (or just BLAKE2b for `vera-hashing-384`) |
| **3 — Writer** | Produce files satisfying every MUST in Sections 1–6 and passing `vera validate` | Full pipeline |

Level 1 is deliberately trivial: any environment with SQLite can read, cite, and keyword-search a VERA file.

## 9. Versioning

- `format_version` follows `MAJOR.MINOR`. Readers **SHOULD** accept any file whose major version they support and tolerate additive minor-version changes (new tables, columns, metadata keys, block/asset types).
- Breaking changes (removing/renaming tables or columns, changing vector encoding) require a major version bump.
- v0.x is experimental: breaking changes may occur between minor versions until 1.0.

## 10. Future extensions (reserved, non-normative)

Multiple documents per file, multiple embedding models, ANN indexes (sqlite-vec), page thumbnails, table extraction (`table_json` / `table_csv` assets), JSON export/import, signed and encrypted files.
