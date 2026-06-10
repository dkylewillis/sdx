---
name: vera
description: Search and inspect VERA (.vera) document archives. Use when the user wants answers from a .vera file, citation-ready retrieval from local documents, semantic/keyword/hybrid search, figure metadata, archive validation, or PDF-to-VERA conversion.
---

# VERA

VERA archives are SQLite files that package a source document with parsed pages,
chunks, embeddings, keyword index, figure metadata, and citation fields. Use the
`vera` CLI to convert, inspect, validate, and search archives from a runtime
agent environment.

## When to Use

Use this skill when the user asks to:

- Answer questions from a `.vera` file.
- Search a converted document semantically, by keyword, or with hybrid retrieval.
- Inspect a VERA archive's metadata, source filename, page count, chunk count, parser, or embedding model.
- Validate that a `.vera` file is well formed.
- Find figures, captions, tables, diagrams, or page-level context in a VERA archive.

If the user has a PDF instead of a `.vera` file, convert it first with
`vera convert input.pdf output.vera`.

## Commands

All commands support `--json` where noted. Prefer JSON output so results can be
parsed reliably.

### Search

Search a VERA file and return citation-ready chunks:

```bash
vera search manual.vera "stormwater detention requirements" --mode hybrid --top-k 5 --json
```

Include figure/table metadata when visual context matters:

```bash
vera search manual.vera "pipe sizing chart" --mode hybrid --top-k 5 --json --figures
```

Arguments:

- `file`: path to the `.vera` file.
- `query`: natural-language or keyword query.
- `--mode`: `hybrid`, `semantic`, or `keyword`. Default to `hybrid` unless the user asks otherwise.
- `--top-k`: number of results. Use 5 for normal questions; increase when the user asks for broad coverage.
- `--figures`: include figure metadata and captions in JSON output.

Use `keyword` for exact phrases, identifiers, section numbers, or codes. Use
`semantic` for paraphrased questions where exact wording may not match. Use
`hybrid` for most work.

### Inspect

Get archive metadata before searching when the user asks what is in a file or
when you need to confirm the source document and available page range:

```bash
vera inspect manual.vera --json
```

### Validate

Validate schema integrity, row counts, embeddings, FTS index consistency, and
original-document presence:

```bash
vera validate manual.vera --json
```

Use validation when the user asks whether a `.vera` file is valid or when search
failures suggest the archive may be malformed.

### Convert

Convert PDFs before searching them:

```bash
vera convert input.pdf output.vera --json
```

Use the default hashing embedder unless the user asks for another installed
model.

## Citation Rules

Always cite VERA results with the source filename when present, page number or
page range, and heading path when available. A concise citation format is:

`(source.pdf, p. 42, Chapter 4 > Detention Design)`

For multi-page chunks, cite the range as `pp. 42-43`. If a result has no heading
path, cite the source and page only.

When using figures, mention the caption and page. Do not claim to have inspected
image pixels unless separate image data is available and has actually been read.

## Workflow

1. If the user gives a `.vera` path and a question, run `vera search` first with `--json`.
2. If the result set is thin or exact terms matter, retry with `keyword` or a
   tighter query.
3. If the user asks for comprehensive coverage, search several targeted queries
   and synthesize across the cited results.
4. Use `vera inspect` or `vera validate` when file metadata or archive health matters.
5. Answer from retrieved evidence and include citations for every substantive
   claim tied to the document.
