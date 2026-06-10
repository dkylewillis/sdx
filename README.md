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
vera search ./library "stream buffer requirements"   # search a folder of .vera files
vera export output.vera original.pdf                 # get the source document back out
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

# Visual grounding: where on the page did this chunk come from?
for region in doc.regions_for(results[0]):
    print(region["page_number"], region["bbox"])  # [x0, y0, x1, y1] in page points

# The original PDF is stored inside the .vera file
source = doc.get_source_document()                # filename, mime_type, data, hash
doc.export_source_document("original.pdf")
```

Search many documents at once:

```python
from vera import VeraCorpus

with VeraCorpus.open("./library") as corpus:      # a folder of .vera files
    for r in corpus.search("when is detention required", top_k=5):
        print(r.file, r.page_start, r.text[:80])  # each result knows its file
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
- **Visual grounding** — every chunk maps back to the page regions it came from. `doc.regions_for(result)` (or `vera search --regions`) returns page numbers and bounding boxes (page points, origin top-left) plus page dimensions, so a viewer can scroll to the page and highlight the cited text.
- **Document access** — the original source file is stored inside the archive and comes back out intact: `doc.get_source_document()` / `vera export`. Pages (`get_page`), layout blocks with bounding boxes (`get_blocks`), and stored assets (`get_asset`) are all directly accessible for building viewers.
- **Corpus search** — `VeraCorpus.open(folder)` (or `vera search <folder> "query"`) searches every `.vera` file in a directory as one collection and fuses the rankings; each result is attributed to its file.
- **Transparent** — every file records its parser, chunking strategy, and embedding model in `vera_metadata`.

## CLI

| Command | Purpose |
| ------- | ------- |
| `vera convert input.pdf output.vera` | Convert a PDF (options: `--model`, `--chunk-size`, `--overlap`) |
| `vera inspect output.vera` | Print metadata: pages, chunks, model, parser |
| `vera validate output.vera` | Check schema, counts, and index consistency |
| `vera search output.vera "query"` | Search a file — or a directory of `.vera` files — (`--mode semantic\|keyword\|hybrid`, `--top-k`, `--context-chunks`, `--figures`, `--regions`) |
| `vera export output.vera [path]` | Write the original source document back out of the archive |
| `vera eval output.vera queries.json` | Measure retrieval quality against an expected-answer query set |
| `vera mcp` | Run the MCP server (stdio) exposing VERA tools to AI agents |
| `vera workbench` | Launch the Streamlit GUI |

Every command accepts `--json` for machine-readable output (see below).

## Using VERA with AI agents

VERA was built to give agents grounded, citation-ready context from large documents without a retrieval service. Agents can call the CLI directly — every command supports `--json` and meaningful exit codes (`validate`/`eval` exit non-zero on failure):

```bash
vera search ordinance.vera "when is detention required" --top-k 5 --json --figures --context-chunks 1
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
      "before_chunks": [{"chunk_id": "chunk_000411", "text": "...", "page_start": 119, "page_end": 119}],
      "after_chunks": [{"chunk_id": "chunk_000413", "text": "...", "page_start": 121, "page_end": 121}],
      "figures": [
        {"page_number": 120, "caption": "Figure 4-1: Detention sizing", "asset_id": "asset_block_000371", "...": "..."}
      ]
    }
  ]
}
```

Every result carries its citation (source file, page, heading path), so agent answers can point back to the exact location in the source document. `--figures` adds metadata and captions for images on the result's pages, and `--context-chunks N` adds N chunks before and after each result as `before_chunks` and `after_chunks`. Add `--regions` and each result also carries a `regions` array — the page numbers and bounding boxes (`[x0, y0, x1, y1]` in page points, origin top-left, with page dimensions) of the blocks the chunk came from — so a viewer can scroll to the citation and highlight it. Point `vera search` at a directory instead of a file and the agent searches every `.vera` file in it as one corpus, with each result attributed to its `file`.

### MCP server

VERA also ships a [Model Context Protocol](https://modelcontextprotocol.io/) server so MCP-capable agents can use VERA as native tools — `vera_search`, `vera_corpus_search`, `vera_inspect`, `vera_validate`, `vera_figures`, `vera_get_page`, and `vera_get_chunk_regions`. Install the `mcp` extra and point your client at `vera mcp`:

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

Run the automated suite (140 tests, also run in CI on Ubuntu/Windows × Python 3.10/3.12):

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
