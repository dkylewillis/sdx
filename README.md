# SDX — Semantic Document eXchange

SDX is a portable semantic document exchange format: one SQLite `.sdx` file that carries a document **and** everything needed to search it — parsed structure, chunks, embeddings, keyword index, figures, and citation metadata.

Tagline: **Convert once. Search anywhere.**

## What is SDX?

```text
   The old way (every app repeats this):       The SDX way (do it once):

   PDF ─> parse ─> chunk ─> embed ─┐           PDF ──> sdx convert ──> ordinance.sdx
                                   │                                       │
                              vector DB             ┌──────────────────────┼──────────────┐
                                   │                ▼                      ▼              ▼
                                search           your app             CLI search      workbench

   ┌─────────────────── ordinance.sdx (a single SQLite file) ────────────────────┐
   │                                                                             │
   │   original PDF      parsed pages & blocks       chunks with citations       │
   │   (assets)          headings / paragraphs /     "Ch 110 > Art 5 > Parking"  │
   │                     images / captions           page 42                     │
   │                                                                             │
   │   embeddings        FTS5 keyword index          figures + captions          │
   │   (float32)         (bm25)                      (extracted images)          │
   │                                                                             │
   └── open it anywhere: semantic, keyword, and hybrid search with no server, ───┘
       no vector database, and no re-ingestion
```

A search result always points back to its source: filename, page range, heading path, score, and the figures on those pages.

## Quick start

```bash
sdx convert input.pdf output.sdx
sdx inspect output.sdx
sdx validate output.sdx
sdx search output.sdx "stream buffer requirements" --mode hybrid
```

Python:

```python
from sdx import convert, SDXDocument

convert("input.pdf", "output.sdx")

doc = SDXDocument.open("output.sdx")
results = doc.search("when is detention required", mode="hybrid", top_k=5)
for r in results:
    print(r.score, r.page_start, r.heading_path)
    print(r.text)
```

## Features

- **Single-file format** — a `.sdx` file is a normal SQLite database with a standardized schema. No server, no vector database, no re-ingestion to open one.
- **Three search modes** — `semantic` (brute-force cosine over stored embeddings), `keyword` (SQLite FTS5 / bm25), and `hybrid` (both score sets min-max normalized and blended equally).
- **Structured parsing** — headings are detected from font size/weight and produce hierarchical heading paths (`Chapter 110 > Article 5 > Parking`); rotated watermark text is filtered out; chunks never span pages and map back to their source blocks via `chunk_blocks`.
- **Figures and captions** — embedded images are extracted into the `assets` table; caption blocks ("Figure 3: Detention pond sizing diagram") are detected, flow into chunk text so figures are searchable, and are returned alongside figures:

```python
result = doc.search("detention pond sizing", top_k=1)[0]
for fig in doc.figures_for(result, include_data=True):  # figures on the result's pages
    print(fig["page_number"], fig["caption"])           # caption text or None
```

- **Pluggable embeddings** — a deterministic local hashing embedder (384-dim, zero dependencies) is the default; `--model sentence-transformers/all-MiniLM-L6-v2` enables neural embeddings via the optional `ml` extra.
- **Transparent** — every file records its parser, chunking strategy, and embedding model in `sdx_metadata`.

## CLI

| Command | Purpose |
|---------|---------|
| `sdx convert input.pdf output.sdx` | Convert a PDF (options: `--model`, `--chunk-size`, `--overlap`) |
| `sdx inspect output.sdx` | Print metadata: pages, chunks, model, parser |
| `sdx validate output.sdx` | Check schema, counts, and index consistency |
| `sdx search output.sdx "query"` | Search (`--mode semantic\|keyword\|hybrid`, `--top-k`) |
| `sdx eval output.sdx queries.json` | Measure retrieval quality against an expected-answer query set |
| `sdx workbench` | Launch the Streamlit GUI |

## Testing & retrieval evaluation

Run the automated suite (97 tests, also run in CI on Ubuntu/Windows × Python 3.10/3.12):

```bash
uv run --extra dev pytest -q
```

Measure retrieval quality against an expected-answer query set:

```bash
uv run python -m sdx.cli eval output.sdx queries.json --mode all --top-k 5
```

Query files are JSON (or YAML with pyyaml installed) lists of cases:

```json
[
  {"query": "restaurant parking", "expected_pages": [42, 43], "expected_terms": ["parking"]}
]
```

The command reports hit rate and MRR per search mode and exits non-zero on any miss — handy for CI regression checks. Example sets in [examples/](examples/):

- [examples/docling-queries.json](examples/docling-queries.json) — technical paper, lexical queries
- [examples/docling-paraphrase-queries.json](examples/docling-paraphrase-queries.json) — zero vocabulary overlap, stresses semantic search
- [examples/gsmm-queries.json](examples/gsmm-queries.json) — 1,038-page stormwater manual, real-world regulatory queries

Current baseline on the stormwater manual (2,442 chunks, hashing embedder): hybrid and keyword both hit 9/10 at MRR 0.900.

## SDX Workbench

For easy manual testing, install the optional Streamlit extra and launch the workbench:

```bash
uv run --extra workbench python -m sdx.cli workbench
```

The workbench lets you upload a PDF, convert it to `.sdx`, inspect metadata, run validation, browse chunks, compare semantic/keyword/hybrid search results, and view figures (with captions) co-located with each result.

## Status

SDX is v0.1 and experimental. The schema and format may change. See [docs/sdx-spec-v0.1.md](docs/sdx-spec-v0.1.md) for the format specification (in progress).
