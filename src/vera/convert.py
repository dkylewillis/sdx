from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .embeddings import get_embedder, serialize_vector
from .parsers import ParsedBlock, parse_pdf, parse_pdf_structured
from .schema import FORMAT_VERSION, create_schema

_HEADING_RE = re.compile(r"^(chapter|section|article|part|appendix|stormwater|zoning|[0-9]+(?:\.[0-9]+)*)\b", re.I)


@dataclass
class Chunk:
    text: str
    page_start: int
    page_end: int
    heading_path: str
    token_count: int
    block_ids: list[str] = field(default_factory=list)


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


def build_chunks_from_blocks(
    blocks: list[tuple[str, ParsedBlock]],
    chunk_size: int = 500,
    overlap: int = 75,
) -> list[Chunk]:
    """Heading-aware chunking over structured blocks.

    blocks is a list of (block_id, ParsedBlock). Maintains a heading stack to
    produce hierarchical heading paths ("Chapter 1 > Section 1.2"), flushes
    chunks at heading boundaries, and records contributing block ids.
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    overlap = max(0, min(overlap, chunk_size - 1))

    chunks: list[Chunk] = []
    heading_stack: list[tuple[int, str]] = []
    buffer_words: list[str] = []
    buffer_blocks: list[str] = []
    buffer_pages: list[int] = []

    def heading_path() -> str:
        return " > ".join(text for _, text in heading_stack)

    def flush() -> None:
        nonlocal buffer_words, buffer_blocks, buffer_pages
        if buffer_words:
            text = " ".join(buffer_words)
            chunks.append(
                Chunk(
                    text,
                    min(buffer_pages),
                    max(buffer_pages),
                    heading_path(),
                    len(buffer_words),
                    list(dict.fromkeys(buffer_blocks)),
                )
            )
        buffer_words = []
        buffer_blocks = []
        buffer_pages = []

    for block_id, block in blocks:
        if block.block_type == "image":
            continue
        if buffer_pages and block.page_number != buffer_pages[-1]:
            # Keep citations page-precise: do not merge chunks across pages.
            flush()
        if block.block_type == "heading":
            flush()
            level = block.heading_level or 6
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, block.text))
            continue
        words = _tokens(block.text)
        if not words:
            continue
        if len(words) > chunk_size:
            flush()
            step = chunk_size - overlap
            for start in range(0, len(words), step):
                part = words[start : start + chunk_size]
                if part:
                    chunks.append(
                        Chunk(
                            " ".join(part),
                            block.page_number,
                            block.page_number,
                            heading_path(),
                            len(part),
                            [block_id],
                        )
                    )
                if start + chunk_size >= len(words):
                    break
            continue
        if buffer_words and len(buffer_words) + len(words) > chunk_size:
            carry = buffer_words[-overlap:] if overlap else []
            flush()
            buffer_words.extend(carry)
        buffer_words.extend(words)
        buffer_blocks.append(block_id)
        buffer_pages.append(block.page_number)
    flush()
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
    pages, parsed_blocks = parse_pdf_structured(str(source))
    block_records: list[tuple[str, ParsedBlock]] = [
        (f"block_{idx:06d}", block) for idx, block in enumerate(parsed_blocks, start=1)
    ]
    chunks = build_chunks_from_blocks(block_records, chunk_size=chunk_size, overlap=overlap)
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
            "format_name": "VERA",
            "format_version": FORMAT_VERSION,
            "created_at": now,
            "created_by": "vera",
            "creator_library": "vera-python/0.1.0",
            "source_file_name": source.name,
            "source_file_hash": source_hash,
            "source_mime_type": mime_type,
            "default_embedding_model": embedder.model_name,
            "default_embedding_dimension": str(embedder.dimension),
            "chunking_strategy": f"heading_block_sliding_window:{chunk_size}:{overlap}",
            "parser_name": parser,
            "parser_version": "pymupdf",
        }
        conn.executemany("INSERT INTO vera_metadata(key, value) VALUES (?, ?)", metadata.items())
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
        for sort_order, (block_id, block) in enumerate(block_records, start=1):
            page_id = f"page_{block.page_number:06d}"
            bbox_json = json.dumps(list(block.bbox)) if block.bbox else None
            conn.execute(
                "INSERT INTO blocks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    block_id,
                    doc_id,
                    page_id,
                    block.page_number,
                    block.block_type,
                    block.text,
                    bbox_json,
                    block.heading_level,
                    sort_order,
                ),
            )
            if block.block_type == "image" and block.image_bytes:
                ext = block.image_ext or "png"
                conn.execute(
                    "INSERT INTO assets VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        f"asset_{block_id}",
                        doc_id,
                        "extracted_image",
                        f"image/{ext}",
                        f"page{block.page_number:04d}_{block_id}.{ext}",
                        block.image_bytes,
                        _sha256_bytes(block.image_bytes),
                    ),
                )
        for idx, (chunk, vector) in enumerate(zip(chunks, vectors), start=1):
            chunk_id = f"chunk_{idx:06d}"
            text_hash = hashlib.sha256(chunk.text.encode("utf-8")).hexdigest()
            conn.execute(
                "INSERT INTO chunks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (chunk_id, doc_id, chunk.page_start, chunk.page_end, chunk.heading_path, chunk.text, chunk.token_count, text_hash, idx),
            )
            conn.executemany(
                "INSERT OR IGNORE INTO chunk_blocks(chunk_id, block_id) VALUES (?, ?)",
                [(chunk_id, block_id) for block_id in chunk.block_ids],
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
