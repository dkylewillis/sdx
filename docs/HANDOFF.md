# VERA — Development Handoff

Status notes for resuming work in a new session/agent. Last updated: 2026-06-10.

## Project context

VERA is a single-file SQLite format (`.vera`) bundling a document + parsed structure +
embeddings + keyword index for portable semantic search. See [README.md](../README.md)
and the spec at [vera-spec-v0.1.md](vera-spec-v0.1.md).

**Driving goal:** VERA is the document engine for a separate app (`vera-app`, its own
repo, not created yet) — a PDF viewer with a built-in research agent. Users query one
or many documents; the agent uses `.vera` search for context and answers with
clickable citations that scroll the viewer to the page and highlight the cited text
(visual grounding). The app imports `vera` directly as a Python library.

**Decisions made:**
- App lives in a separate repo; anything that touches `.vera` internals belongs in VERA
- Corpus = a flat folder of `.vera` files (no catalog DB)
- Integration = Python library import (no HTTP server)
- Hashing embedder stays the zero-dependency default; neural (sentence-transformers) is opt-in via the `ml` extra
- Deferred: ANN indexing, incremental updates, table extraction, encryption, multi-document-per-file

## Completed (2026-06-10)

### Phase 1 — Document access APIs (in `src/vera/document.py`)
- `SourceDocument` dataclass; `get_source_document()` / `export_source_document(path)`
  — original PDF bytes back out of the archive (raises `ValueError` if
  `store_original=False`)
- `get_page(n)`, `get_blocks(page_number=None)` (bbox parsed to lists), `get_asset(asset_id)`
- CLI: `vera export file.vera [out] --json`
- MCP: `vera_get_page` refactored onto the public API

### Phase 1.5 — Visual grounding
- `get_chunk_regions(chunk_id)` / `regions_for(result)` →
  `[{page_number, bbox, block_id, page_width, page_height}]` via
  `chunk_blocks → blocks → pages`. bbox = `[x0, y0, x1, y1]` page points, origin
  top-left (PDF.js needs a y-flip using page height)
- Regions are **block-granular**: a chunk starting/ending mid-block highlights the whole block
- CLI `vera search --regions`; MCP `vera_search(include_regions=)` + `vera_get_chunk_regions`
- Spec §7.1 documents the grounding query and coordinate contract
- No schema changes were needed — bbox/chunk_blocks/page dims already existed

### Phase 2 — Corpus search (`src/vera/corpus.py`, new)
- `VeraCorpus.open(folder)` — discovers `*.vera`, lazy-opens/caches handles, context manager
- `corpus.search(...)` → `CorpusSearchResult` (= `SearchResult` + `file` field)
- Fusion: semantic = raw cosine merge; keyword/hybrid = RRF (k=60) with within-file
  score tiebreak (BM25 scores aren't comparable across files)
- Per-file query embedding uses each file's recorded model (mixed-model corpora OK)
- `corpus.regions_for()` / `figures_for()` dispatch to the right file
- CLI: `vera search <directory> "query"`; MCP: `vera_corpus_search`
- Tests: `tests/test_document_access.py`, `tests/test_corpus.py` (140 tests total, all green)
- README + AGENTS.md updated for all of the above

## Next steps

### Phase 3 — Neural embeddings quality (next up)
1. Verify query-time embedding honors the file's recorded `default_embedding_model`
   for sentence-transformers files (it should — `_semantic_scores` reads metadata — but
   there is no end-to-end test)
2. Add an e2e test for the ST path, `pytest.mark.skipif` when the `ml` extra is missing
3. Better error message when a `.vera` needs sentence-transformers but the extra isn't installed
4. Run `vera eval` with `all-MiniLM-L6-v2` on `examples/docling-paraphrase-queries.json`
   (semantic stress set, zero vocabulary overlap) and record results in README next to
   the hashing baseline

### Phase 4 — Polish
5. Workbench: "download original PDF" button (`get_source_document()`), maybe show
   highlight regions on search results
6. Consider MCP tool exposing source-document metadata (not bytes)

### Later / app-driven (build vera-app first, promote needs back into VERA)
- Word-precise highlighting: `locate_text(page_number, text)` using PyMuPDF
  `page.search_for` against the stored original PDF (upgrade from block-granular)
- ANN index if corpus latency hurts at scale (hundreds of files ≈ 250k–500k chunks,
  cached matrices can reach several hundred MB)
- Memory cap / LRU eviction in `VeraCorpus._docs`

## Working notes / gotchas

- **Run tests with** `.\.venv\Scripts\python.exe -m pytest tests/ -q` on this machine
  (`uv run` hit a trampoline error; bare `python` lacked pytest). On a fresh machine:
  `uv sync --extra dev --extra ml --extra workbench --extra mcp` then `uv run pytest`.
- **Don't regress retrieval baselines:** GSMM hybrid ≥ 9/10 hit rate, MRR ≥ 0.900
  (`vera eval <gsmm.vera> examples/gsmm-queries.json`); the .vera for it must be
  rebuilt locally from the GSMM PDF (not in repo)
- Keep code and `docs/vera-spec-v0.1.md` in sync (repo rule, see AGENTS.md)
- `chunks` never span pages (chunking flushes at page boundaries) — citations are page-precise
- MCP tests call tools in-process via `build_server()` + `server.call_tool(...)`;
  payload extraction helper `_payload` is in `tests/test_mcp_server.py`
