# SDX — Semantic Document eXchange

SDX is a portable semantic document exchange format that stores a document, parsed pages, chunks, embeddings, keyword indexes, and citation metadata in one SQLite `.sdx` file.

Tagline: **Convert once. Search anywhere.**

## MVP

```bash
sdx convert input.pdf output.sdx
sdx inspect output.sdx
sdx search output.sdx "stream buffer requirements" --mode hybrid
```

Python:

```python
from sdx import convert, SDXDocument
convert("input.pdf", "output.sdx")
doc = SDXDocument.open("output.sdx")
print(doc.search("parking requirements", mode="hybrid"))
```

The MVP uses SQLite + FTS5 and brute-force cosine vector search. It supports PyMuPDF parsing and a deterministic local hashing embedder by default, with optional sentence-transformers support via `--model sentence-transformers/all-MiniLM-L6-v2`.
