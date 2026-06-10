# VERA — Vector-Embedded Retrieval Archive

VERA is a Vector-Embedded Retrieval Archive: one SQLite `.vera` file that carries a document **and** everything needed to search it — parsed structure, chunks, embeddings, keyword index, figures, and citation metadata.

Tagline: **Convert once. Search anywhere.**

## What is VERA?

```text
   The old way (every app repeats this):       The VERA way (do it once):

   PDF ─> parse ─> chunk ─> embed ─┐           PDF ──> vera convert ──> ordinance.vera
                                   │                                       │
                              vector DB             ┌──────────────────────┼──────────────┐
                                   │                ▼                      ▼              ▼
                                search           your app             CLI search      workbench

   ┌─────────────────── ordinance.vera (a single SQLite file) ────────────────────┐
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
vera convert input.pdf output.vera
vera inspect output.vera
vera validate output.vera
vera search output.vera "stream buffer requirements" --mode hybrid
```

Python:

```python
from vera import convert, VeraDocument

convert("input.pdf", "output.vera")

doc = VeraDocument.open("output.vera")
results = doc.search("when is detention required", mode="hybrid", top_k=5)
for r in results:
    print(r.score, r.page_start, r.heading_path)
    print(r.text)
```

## Features

- **Single-file format** — a `.vera` file is a normal SQLite database with a standardized schema. No server, no vector database, no re-ingestion to open one.
- **Three search modes** — `semantic` (brute-force cosine over stored embeddings), `keyword` (SQLite FTS5 / bm25), and `hybrid` (both score sets min-max normalized and blended equally).
- **Structured parsing** — headings are detected from font size/weight and produce hierarchical heading paths (`Chapter 110 > Article 5 > Parking`); rotated watermark text is filtered out; chunks never span pages and map back to their source blocks via `chunk_blocks`.
- **Figures and captions** — embedded images are extracted into the `assets` table; caption blocks ("Figure 3: Detention pond sizing diagram") are detected, flow into chunk text so figures are searchable, and are returned alongside figures:

```python
result = doc.search("detention pond sizing", top_k=1)[0]
for fig in doc.figures_for(result, include_data=True):  # figures on the result's pages
    print(fig["page_number"], fig["caption"])           # caption text or None
```

- **Pluggable embeddings** — a deterministic local hashing embedder (384-dim, zero dependencies) is the default; `--model sentence-transformers/all-MiniLM-L6-v2` enables neural embeddings via the optional `ml` extra.
- **Transparent** — every file records its parser, chunking strategy, and embedding model in `vera_metadata`.

## CLI

| Command | Purpose |
| ------- | ------- |
| `vera convert input.pdf output.vera` | Convert a PDF (options: `--model`, `--chunk-size`, `--overlap`) |
| `vera inspect output.vera` | Print metadata: pages, chunks, model, parser |
| `vera validate output.vera` | Check schema, counts, and index consistency |
| `vera search output.vera "query"` | Search (`--mode semantic\|keyword\|hybrid`, `--top-k`) |
| `vera eval output.vera queries.json` | Measure retrieval quality against an expected-answer query set |
| `vera mcp` | Run the MCP server (stdio) exposing VERA tools to AI agents |
| `vera workbench` | Launch the Streamlit GUI |

Every command accepts `--json` for machine-readable output (see below).

## Using VERA with AI agents

VERA was built to give agents grounded, citation-ready context from large documents without a retrieval service. Agents can call the CLI directly — every command supports `--json` and meaningful exit codes (`validate`/`eval` exit non-zero on failure):

```bash
vera search ordinance.vera "when is detention required" --top-k 5 --json --figures
```

```json
{
  "query": "when is detention required",
  "mode": "hybrid",
  "results": [
    {
      "chunk_id": "chunk_000412",
      "score": 0.93,
      "text": "Stream channel protection shall be provided by...",
      "page_start": 120,
      "page_end": 120,
      "heading_path": "4. Implementing Stormwater Management > ...",
      "source_filename": "ordinance.pdf",
      "figures": [
        {"page_number": 120, "caption": "Figure 4-1: Detention sizing", "asset_id": "asset_block_000371", "...": "..."}
      ]
    }
  ]
}
```

Every result carries its citation (source file, page, heading path), so agent answers can point back to the exact location in the source document. `--figures` adds metadata and captions for images on the result's pages — agents can mention or fetch the relevant diagram.

### MCP server

VERA also ships a [Model Context Protocol](https://modelcontextprotocol.io/) server so MCP-capable agents can use VERA as native tools — `vera_search`, `vera_inspect`, `vera_validate`, `vera_figures`, and `vera_get_page`. Install the `mcp` extra and point your client at `vera mcp`:

```bash
pip install vera[mcp]
```

Example VS Code configuration (`.vscode/mcp.json`):

```json
{
  "servers": {
    "vera": {
      "command": "uv",
      "args": ["run", "--extra", "mcp", "vera", "mcp"]
    }
  }
}
```

See [AGENTS.md](AGENTS.md) and [skills/vera/SKILL.md](skills/vera/SKILL.md) for agent-facing usage guidance.

## Testing & retrieval evaluation

Run the automated suite (102 tests, also run in CI on Ubuntu/Windows × Python 3.10/3.12):

```bash
uv run --extra dev pytest -q
```

Measure retrieval quality against an expected-answer query set:

```bash
uv run python -m vera.cli eval output.vera queries.json --mode all --top-k 5
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

## VERA Workbench

For easy manual testing, install the optional Streamlit extra and launch the workbench:

```bash
uv run --extra workbench python -m vera.cli workbench
```

The workbench lets you upload a PDF, convert it to `.vera`, inspect metadata, run validation, browse chunks, compare semantic/keyword/hybrid search results, and view figures (with captions) co-located with each result.

## Status

VERA is v0.1 and experimental. The schema and format may change. See [docs/vera-spec-v0.1.md](docs/vera-spec-v0.1.md) for the format specification.

## License

Apache-2.0 — see [LICENSE](LICENSE).
