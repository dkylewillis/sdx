# SDX Specification v0.1

An `.sdx` file is a SQLite database with a standardized schema for storing a source document, parsed text, structural chunks, vector embeddings, source assets, and an FTS5 keyword index.

Required tables: `sdx_metadata`, `documents`, `pages`, `blocks`, `chunks`, `chunk_blocks`, `embeddings`, `assets`, and `chunks_fts`.

Vector format for v0.1 is `float32_le` binary blob. Search modes are `semantic`, `keyword`, and `hybrid`.
