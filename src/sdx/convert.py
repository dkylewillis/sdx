from __future__ import annotations

import hashlib
import mimetypes
import os
import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .embeddings import get_embedder, serialize_vector
from .parsers import parse_pdf
from .schema import FORMAT_VERSION, create_schema

_HEADING_RE = re.compile(r"^(chapter|section|article|part|appendix|stormwater|zoning|[0-9]+(?:\.[0-9]+)*)\b", re.I)


@dataclass
class Chunk:
    text: str
    page_start: int
    page_end: int
    heading_path: str
    token_count: int


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _tokens(text: str) -> list[str]:
    return text.split()


def _detect_heading(text: str, current: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and len(stripped) < 120 and _HEADING_RE.match(stripped):
            return stripped
    return current


def chunk_pages(pages, chunk_size: int = 500, overlap: int = 75) -> list[Chunk]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    overlap = max(0, min(overlap, chunk_size - 1))
    chunks: list[Chunk] = []
    heading = ""
    for page in pages:
        heading = _detect_heading(page.text, heading)
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n|(?<=\.)\s*\n", page.text) if p.strip()]
        if not paragraphs and page.text.strip():
            paragraphs = [page.text.strip()]
        buffer: list[str] = []
        for para in paragraphs:
            words = _tokens(para)
            if len(words) > chunk_size:
                if buffer:
                    text = " ".join(buffer)
                    chunks.append(Chunk(text, page.page_number, page.page_number, heading, len(_tokens(text))))
                    buffer = []
                step = chunk_size - overlap
                for start in range(0, len(words), step):
                    part = words[start : start + chunk_size]
                    if part:
                        chunks.append(Chunk(" ".join(part), page.page_number, page.page_number, heading, len(part)))
                    if start + chunk_size >= len(words):
                        break
            elif len(buffer) + len(words) > chunk_size and buffer:
                text = " ".join(buffer)
                chunks.append(Chunk(text, page.page_number, page.page_number, heading, len(_tokens(text))))
                buffer = buffer[-overlap:] if overlap else []
                buffer.extend(words)
            else:
                buffer.extend(words)
        if buffer:
            text = " ".join(buffer)
            chunks.append(Chunk(text, page.page_number, page.page_number, heading, len(_tokens(text))))
    return chunks


def convert(
    input_path: str,
    output_path: str,
    *,
    model: str = "hashing",
    parser: str = "pymupdf",
    chunk_size: int = 500,
    overlap: int = 75,
    store_original: bool = True,
) -> str:
    source = Path(input_path)
    target = Path(output_path)
    if not source.exists():
        raise FileNotFoundError(input_path)
    if parser != "pymupdf":
        raise ValueError("v0.1 currently supports parser='pymupdf'")

    source_data = source.read_bytes()
    source_hash = _sha256_bytes(source_data)
    mime_type = mimetypes.guess_type(source.name)[0] or "application/pdf"
    pages = parse_pdf(str(source))
    chunks = chunk_pages(pages, chunk_size=chunk_size, overlap=overlap)
    embedder = get_embedder(model)
    vectors = embedder.embed([c.text for c in chunks]) if chunks else []

    if target.exists():
        target.unlink()
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target)
    try:
        create_schema(conn)
        now = _utc_now()
        doc_id = "doc_001"
        metadata = {
            "format_name": "SDX",
            "format_version": FORMAT_VERSION,
            "created_at": now,
            "created_by": "sdx",
            "creator_library": "sdx-python/0.1.0",
            "source_file_name": source.name,
            "source_file_hash": source_hash,
            "source_mime_type": mime_type,
            "default_embedding_model": embedder.model_name,
            "default_embedding_dimension": str(embedder.dimension),
            "chunking_strategy": f"page_paragraph_sliding_window:{chunk_size}:{overlap}",
            "parser_name": parser,
            "parser_version": "pymupdf",
        }
        conn.executemany("INSERT INTO sdx_metadata(key, value) VALUES (?, ?)", metadata.items())
        conn.execute(
            "INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?, ?)",
            (doc_id, source.stem, source.name, mime_type, source_hash, len(pages), now),
        )
        for page in pages:
            page_id = f"page_{page.page_number:06d}"
            conn.execute(
                "INSERT INTO pages VALUES (?, ?, ?, ?, ?, ?)",
                (page_id, doc_id, page.page_number, page.width, page.height, page.text),
            )
            # MVP block: one text block per page.
            conn.execute(
                "INSERT INTO blocks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (f"block_{page.page_number:06d}", doc_id, page_id, page.page_number, "paragraph", page.text, None, None, page.page_number),
            )
        for idx, (chunk, vector) in enumerate(zip(chunks, vectors), start=1):
            chunk_id = f"chunk_{idx:06d}"
            text_hash = hashlib.sha256(chunk.text.encode("utf-8")).hexdigest()
            conn.execute(
                "INSERT INTO chunks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (chunk_id, doc_id, chunk.page_start, chunk.page_end, chunk.heading_path, chunk.text, chunk.token_count, text_hash, idx),
            )
            conn.execute("INSERT INTO chunks_fts(chunk_id, text, heading_path) VALUES (?, ?, ?)", (chunk_id, chunk.text, chunk.heading_path))
            conn.execute(
                "INSERT INTO embeddings VALUES (?, ?, ?, ?, ?, ?, ?)",
                (f"emb_{idx:06d}", chunk_id, embedder.model_name, embedder.dimension, serialize_vector(vector), "float32_le", now),
            )
        if store_original:
            conn.execute(
                "INSERT INTO assets VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("asset_original_001", doc_id, "original_document", mime_type, source.name, source_data, source_hash),
            )
        conn.commit()
    finally:
        conn.close()
    return str(target)
