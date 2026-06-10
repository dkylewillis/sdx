# Using VERA as an AI agent

This file teaches AI coding agents how to use VERA to retrieve context from documents.

## What is an `.vera` file?

A single SQLite file containing a document's full text, structure (pages, headings,
figures), and pre-computed embeddings. You can search it instantly — no parsing, no
chunking, no embedding API calls, no vector database. See
[docs/vera-spec-v0.1.md](docs/vera-spec-v0.1.md) for the format specification.

## Quick reference

All commands support `--json` for machine-readable output on stdout.

```bash
# Search a document (hybrid = semantic + keyword, best default)
vera search manual.vera "stormwater detention requirements" --top-k 5 --json

# Search a folder of .vera files as one corpus (results include "file")
vera search ./library "stormwater detention requirements" --top-k 5 --json

# Include figure/table metadata near each result
vera search manual.vera "pipe sizing chart" --json --figures

# Include adjacent text context around each hit
vera search manual.vera "stormwater detention requirements" --json --context-chunks 1

# Keyword-only or semantic-only search
vera search manual.vera "section 4.2" --mode keyword --json
vera search manual.vera "how big should the pond be" --mode semantic --json

# Include highlight regions (page + bounding boxes) for visual grounding
vera search manual.vera "detention requirements" --json --regions

# Export the original source document (e.g. the PDF) back out
vera export manual.vera exported.pdf --json

# What's in this file?
vera inspect manual.vera --json

# Is this file well-formed? (exit code 0 = valid, 1 = invalid)
vera validate manual.vera --json

# Create an .vera from a PDF
vera convert manual.pdf manual.vera
```

### Search result shape (`--json`)

```json
{
  "file": "manual.vera",
  "query": "stormwater detention requirements",
  "mode": "hybrid",
  "results": [
    {
      "rank": 1,
      "chunk_id": "chunk_0042",
      "score": 0.91,
      "page_start": 117,
      "page_end": 118,
      "heading_path": "Chapter 4 > 4.2 Detention Design",
      "text": "..."
    }
  ]
}
```

## Rules for agents

1. **Always cite sources.** Every result includes `page_start`/`page_end` and
   `heading_path`. Quote them when answering from a document, e.g.
   *"(p. 117, Chapter 4 > 4.2 Detention Design)"*.
2. **Prefer `--mode hybrid`** (the default). Use `keyword` only for exact phrases,
   IDs, or section numbers; use `semantic` for paraphrased natural-language questions.
3. **Use `--figures`** when the question involves tables, charts, diagrams, or maps —
   results gain a `figures` array with captions and page locations.
4. **Use `--context-chunks N`** when an answer needs surrounding prose — results gain
  `before_chunks` and `after_chunks` arrays with citation-ready neighboring chunks.
5. **Use `--regions`** when a viewer needs to highlight where a chunk came from —
   results gain a `regions` array of `{page_number, bbox, page_width, page_height}`
   (bbox in page points, origin top-left).
6. **Check exit codes.** `validate` returns non-zero for invalid files; `search` on a
   missing file returns non-zero. Parse stdout as JSON only when exit code is 0.
7. **Don't read the SQLite file directly** unless the CLI is unavailable — the schema
   is documented in the spec, but the CLI/MCP tools are the stable interface.

## MCP server

VERA ships an MCP server (stdio) exposing the same capabilities as tools:

| Tool | Purpose |
|------|---------|
| `vera_search` | Hybrid/semantic/keyword search with optional figure metadata and highlight regions |
| `vera_corpus_search` | Search every .vera file in a directory as one corpus; results attributed per file |
| `vera_inspect` | Document metadata, page/chunk counts, embedding model |
| `vera_validate` | Integrity check |
| `vera_figures` | List figures/images with captions, optionally by page range |
| `vera_get_page` | Full text of a specific page |
| `vera_get_chunk_regions` | Page numbers + bounding boxes a chunk's text came from (visual grounding) |

Requires the `mcp` extra: `pip install vera[mcp]`. Example VS Code config
(`.vscode/mcp.json`):

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

## Working on this repository

- Python 3.10+, dependencies managed with [uv](https://docs.astral.sh/uv/):
  `uv sync --extra dev --extra ml --extra workbench --extra mcp`
- Run tests with `pytest` (all tests must pass before committing).
- Core code lives in [src/vera](src/vera); the format spec is
  [docs/vera-spec-v0.1.md](docs/vera-spec-v0.1.md) — keep code and spec in sync.
- Retrieval quality is tracked with `vera eval` against the query sets in
  [examples](examples); don't regress the baselines in the README.
