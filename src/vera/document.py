from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .embeddings import cosine_similarity, deserialize_vector, get_embedder
from .schema import REQUIRED_METADATA_KEYS

_CAPTION_MAX_GAP = 60.0


def _nearest_caption(
    bbox: list[float] | None,
    captions: list[tuple[list[float] | None, str]],
) -> str | None:
    """Pick the caption vertically closest to a figure bbox, within the gap limit."""
    if not captions:
        return None
    if bbox is None:
        return captions[0][1]
    best_text = None
    best_gap = _CAPTION_MAX_GAP
    for cap_bbox, text in captions:
        if cap_bbox is None:
            continue
        if cap_bbox[3] < bbox[1]:
            gap = bbox[1] - cap_bbox[3]
        elif bbox[3] < cap_bbox[1]:
            gap = cap_bbox[1] - bbox[3]
        else:
            gap = 0.0
        if gap <= best_gap:
            best_gap = gap
            best_text = text
    return best_text


@dataclass
class SourceDocument:
    """The original source document stored inside a VERA file."""

    filename: str | None
    mime_type: str | None
    data: bytes
    hash: str | None


@dataclass
class SearchResult:
    chunk_id: str
    score: float
    text: str
    page_start: int | None
    page_end: int | None
    heading_path: str | None
    source_filename: str | None
    document_id: str
    before_chunks: list[dict[str, Any]] | None = None
    after_chunks: list[dict[str, Any]] | None = None

    def as_dict(self) -> dict[str, Any]:
        data = self.__dict__.copy()
        if self.before_chunks is None:
            data.pop("before_chunks")
        if self.after_chunks is None:
            data.pop("after_chunks")
        return data


class VeraDocument:
    def __init__(self, path: str, conn: sqlite3.Connection):
        self.path = path
        self.conn = conn
        self.conn.row_factory = sqlite3.Row

    @classmethod
    def open(cls, path: str) -> "VeraDocument":
        conn = sqlite3.connect(path)
        return cls(path, conn)

    def close(self) -> None:
        self.conn.close()

    def inspect(self) -> dict[str, Any]:
        metadata = {row["key"]: row["value"] for row in self.conn.execute("SELECT key, value FROM vera_metadata")}
        doc = self.conn.execute("SELECT * FROM documents LIMIT 1").fetchone()
        metadata.update(
            {
                "file": self.path,
                "source": doc["source_filename"] if doc else None,
                "pages": self.conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0],
                "chunks": self.conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0],
                "embeddings": self.conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0],
            }
        )
        return metadata

    def validate(self) -> dict[str, Any]:
        """Validate the VERA container, schema, metadata, indexes, and embeddings."""
        issues: list[str] = []
        warnings: list[str] = []
        required_tables = {
            "vera_metadata",
            "documents",
            "pages",
            "blocks",
            "chunks",
            "chunk_blocks",
            "embeddings",
            "assets",
            "chunks_fts",
        }

        integrity = self.conn.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            issues.append(f"SQLite integrity check failed: {integrity}")

        existing_tables = {
            row["name"]
            for row in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','virtual table')"
            )
        }
        for table in sorted(required_tables - existing_tables):
            issues.append(f"Missing required table: {table}")

        counts = {
            "documents": self._safe_count("documents", existing_tables),
            "pages": self._safe_count("pages", existing_tables),
            "chunks": self._safe_count("chunks", existing_tables),
            "embeddings": self._safe_count("embeddings", existing_tables),
            "fts_rows": self._safe_count("chunks_fts", existing_tables),
            "assets": self._safe_count("assets", existing_tables),
        }

        metadata = {}
        if "vera_metadata" in existing_tables:
            metadata = {row["key"]: row["value"] for row in self.conn.execute("SELECT key, value FROM vera_metadata")}
            for key in REQUIRED_METADATA_KEYS:
                if key not in metadata:
                    issues.append(f"Missing required metadata key: {key}")

        if counts["documents"] < 1:
            issues.append("No document records found")
        if counts["pages"] < 1:
            issues.append("No page records found")
        if counts["chunks"] < 1:
            issues.append("No chunks found")
        if counts["embeddings"] != counts["chunks"]:
            issues.append(f"Embedding count ({counts['embeddings']}) does not match chunk count ({counts['chunks']})")
        if counts["fts_rows"] != counts["chunks"]:
            issues.append(f"FTS row count ({counts['fts_rows']}) does not match chunk count ({counts['chunks']})")

        original_document_present = False
        if "assets" in existing_tables:
            original_document_present = (
                self.conn.execute("SELECT COUNT(*) FROM assets WHERE asset_type='original_document'").fetchone()[0] > 0
            )
            if not original_document_present:
                issues.append("Original document asset is missing")

        if "embeddings" in existing_tables:
            for row in self.conn.execute(
                "SELECT embedding_id, chunk_id, model_dimension, vector FROM embeddings ORDER BY embedding_id"
            ):
                expected = int(row["model_dimension"] or 0) * 4
                actual = len(row["vector"] or b"")
                if expected <= 0 or actual != expected:
                    issues.append(
                        f"Invalid embedding blob for {row['embedding_id']} / {row['chunk_id']}: expected {expected} bytes, got {actual}"
                    )

        if "chunks" in existing_tables and "pages" in existing_tables:
            bad_page_refs = self.conn.execute(
                """
                SELECT COUNT(*) FROM chunks
                WHERE page_start IS NOT NULL
                  AND page_start NOT IN (SELECT page_number FROM pages)
                """
            ).fetchone()[0]
            if bad_page_refs:
                issues.append(f"Chunks with invalid page_start references: {bad_page_refs}")

        return {
            "ok": not issues,
            "issues": issues,
            "warnings": warnings,
            "counts": counts,
            "checks": {
                "sqlite_integrity": integrity,
                "required_tables_present": required_tables.issubset(existing_tables),
                "original_document_present": original_document_present,
            },
            "metadata": metadata,
        }

    def _safe_count(self, table: str, existing_tables: set[str]) -> int:
        if table not in existing_tables:
            return 0
        return int(self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

    def figures(
        self,
        page_start: int | None = None,
        page_end: int | None = None,
        include_data: bool = False,
    ) -> list[dict[str, Any]]:
        """Return extracted figures (image blocks + stored image assets).

        Each figure includes its caption text when a caption block sits
        vertically adjacent on the same page. Optionally filter to a page
        range, e.g. the pages of a search result. Set include_data=True to
        also return the image bytes.
        """
        sql = """
            SELECT b.block_id, b.page_number, b.bbox_json,
                   a.asset_id, a.mime_type, a.filename
            FROM blocks b
            JOIN assets a ON a.asset_id = 'asset_' || b.block_id
            WHERE b.block_type = 'image'
        """
        params: list[Any] = []
        if page_start is not None:
            sql += " AND b.page_number >= ?"
            params.append(page_start)
        if page_end is not None:
            sql += " AND b.page_number <= ?"
            params.append(page_end)
        sql += " ORDER BY b.page_number, b.sort_order"
        rows = self.conn.execute(sql, params).fetchall()
        captions_by_page: dict[int, list[tuple[list[float] | None, str]]] = {}
        if rows:
            pages = sorted({row["page_number"] for row in rows})
            placeholders = ",".join("?" * len(pages))
            for cap in self.conn.execute(
                f"SELECT page_number, bbox_json, text FROM blocks "
                f"WHERE block_type = 'caption' AND page_number IN ({placeholders})",
                pages,
            ):
                bbox = json.loads(cap["bbox_json"]) if cap["bbox_json"] else None
                captions_by_page.setdefault(cap["page_number"], []).append((bbox, cap["text"]))
        figures = []
        for row in rows:
            bbox = json.loads(row["bbox_json"]) if row["bbox_json"] else None
            figure = {
                "block_id": row["block_id"],
                "page_number": row["page_number"],
                "bbox": bbox,
                "asset_id": row["asset_id"],
                "mime_type": row["mime_type"],
                "filename": row["filename"],
                "caption": _nearest_caption(bbox, captions_by_page.get(row["page_number"], [])),
            }
            if include_data:
                figure["data"] = self.conn.execute(
                    "SELECT data FROM assets WHERE asset_id = ?", (row["asset_id"],)
                ).fetchone()["data"]
            figures.append(figure)
        return figures

    def figures_for(self, result: SearchResult, include_data: bool = False) -> list[dict[str, Any]]:
        """Return figures located on the pages of a search result."""
        return self.figures(result.page_start, result.page_end, include_data=include_data)

    def get_source_document(self) -> SourceDocument:
        """Return the original source document (e.g. the PDF) stored in this file.

        Raises ValueError if the file was created with store_original=False.
        """
        row = self.conn.execute(
            "SELECT filename, mime_type, data, hash FROM assets WHERE asset_type = 'original_document'"
        ).fetchone()
        if row is None or row["data"] is None:
            raise ValueError("No original document stored in this VERA file")
        return SourceDocument(
            filename=row["filename"],
            mime_type=row["mime_type"],
            data=row["data"],
            hash=row["hash"],
        )

    def export_source_document(self, path: str | None = None) -> str:
        """Write the original source document to disk and return its path.

        When path is omitted, the stored source filename is used in the
        current working directory. When path is an existing directory, the
        stored filename is written inside it.
        """
        source = self.get_source_document()
        fallback = source.filename or "source_document"
        target = Path(path) if path else Path(fallback)
        if target.is_dir():
            target = target / fallback
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.data)
        return str(target)

    def get_page(self, page_number: int) -> dict[str, Any] | None:
        """Return a single page (1-based) with its text and dimensions, or None."""
        row = self.conn.execute(
            "SELECT page_id, page_number, width, height, text FROM pages WHERE page_number = ?",
            (page_number,),
        ).fetchone()
        return dict(row) if row is not None else None

    def get_blocks(self, page_number: int | None = None) -> list[dict[str, Any]]:
        """Return layout blocks in reading order, optionally for a single page.

        Each block carries its bbox ([x0, y0, x1, y1] in page points, origin
        top-left) so applications can render page overlays.
        """
        sql = """
            SELECT block_id, page_number, block_type, text, bbox_json, heading_level, sort_order
            FROM blocks
        """
        params: list[Any] = []
        if page_number is not None:
            sql += " WHERE page_number = ?"
            params.append(page_number)
        sql += " ORDER BY sort_order"
        blocks = []
        for row in self.conn.execute(sql, params):
            block = dict(row)
            bbox_json = block.pop("bbox_json")
            block["bbox"] = json.loads(bbox_json) if bbox_json else None
            blocks.append(block)
        return blocks

    def get_asset(self, asset_id: str, include_data: bool = True) -> dict[str, Any] | None:
        """Return a stored asset by id (image, original document, ...), or None."""
        row = self.conn.execute(
            "SELECT asset_id, document_id, asset_type, mime_type, filename, data, hash FROM assets WHERE asset_id = ?",
            (asset_id,),
        ).fetchone()
        if row is None:
            return None
        asset = dict(row)
        if not include_data:
            asset.pop("data")
        return asset

    def get_chunk_regions(self, chunk_id: str) -> list[dict[str, Any]]:
        """Return the page regions (bounding boxes) a chunk's text came from.

        Each region is one contributing block: {page_number, bbox, block_id,
        page_width, page_height}. bbox is [x0, y0, x1, y1] in page points with
        the origin at the top-left; page dimensions let viewers scale the box
        to any rendered size. Regions are block-granular: a chunk that starts
        or ends mid-block highlights the whole block.
        """
        rows = self.conn.execute(
            """
            SELECT b.block_id, b.page_number, b.bbox_json, p.width AS page_width, p.height AS page_height
            FROM chunk_blocks cb
            JOIN blocks b ON b.block_id = cb.block_id
            LEFT JOIN pages p ON p.page_id = b.page_id
            WHERE cb.chunk_id = ?
            ORDER BY b.sort_order
            """,
            (chunk_id,),
        ).fetchall()
        regions = []
        for row in rows:
            regions.append(
                {
                    "block_id": row["block_id"],
                    "page_number": row["page_number"],
                    "bbox": json.loads(row["bbox_json"]) if row["bbox_json"] else None,
                    "page_width": row["page_width"],
                    "page_height": row["page_height"],
                }
            )
        return regions

    def regions_for(self, result: SearchResult) -> list[dict[str, Any]]:
        """Return highlight regions for a search result (see get_chunk_regions)."""
        return self.get_chunk_regions(result.chunk_id)

    def search(self, query: str, mode: str = "hybrid", top_k: int = 10, context_chunks: int = 0) -> list[SearchResult]:
        mode = mode.lower()
        if mode not in {"semantic", "keyword", "hybrid"}:
            raise ValueError("mode must be semantic, keyword, or hybrid")
        if context_chunks < 0:
            raise ValueError("context_chunks must be non-negative")
        if mode == "semantic":
            results = self._semantic_search(query, top_k)
        elif mode == "keyword":
            results = self._keyword_search(query, top_k)
        else:
            results = self._hybrid_search(query, top_k)
        if context_chunks:
            self._add_context_chunks(results, context_chunks)
        return results

    def _add_context_chunks(self, results: list[SearchResult], context_chunks: int) -> None:
        for result in results:
            before_chunks, after_chunks = self._context_chunks_for(result.chunk_id, context_chunks)
            result.before_chunks = before_chunks
            result.after_chunks = after_chunks

    def _context_chunks_for(self, chunk_id: str, context_chunks: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        origin = self.conn.execute(
            "SELECT document_id, sort_order FROM chunks WHERE chunk_id = ?",
            (chunk_id,),
        ).fetchone()
        if origin is None:
            return [], []

        before_rows = self.conn.execute(
            """
            SELECT c.*, d.source_filename
            FROM chunks c
            JOIN documents d ON c.document_id = d.document_id
            WHERE c.document_id = ? AND c.sort_order < ?
            ORDER BY c.sort_order DESC
            LIMIT ?
            """,
            (origin["document_id"], origin["sort_order"], context_chunks),
        ).fetchall()
        after_rows = self.conn.execute(
            """
            SELECT c.*, d.source_filename
            FROM chunks c
            JOIN documents d ON c.document_id = d.document_id
            WHERE c.document_id = ? AND c.sort_order > ?
            ORDER BY c.sort_order ASC
            LIMIT ?
            """,
            (origin["document_id"], origin["sort_order"], context_chunks),
        ).fetchall()
        return (
            [self._row_to_context_chunk(row) for row in reversed(before_rows)],
            [self._row_to_context_chunk(row) for row in after_rows],
        )

    def _row_to_context_chunk(self, row) -> dict[str, Any]:
        return {
            "chunk_id": row["chunk_id"],
            "text": row["text"],
            "page_start": row["page_start"],
            "page_end": row["page_end"],
            "heading_path": row["heading_path"],
            "source_filename": row["source_filename"],
            "document_id": row["document_id"],
        }

    def _row_to_result(self, row, score: float) -> SearchResult:
        return SearchResult(
            chunk_id=row["chunk_id"],
            score=float(score),
            text=row["text"],
            page_start=row["page_start"],
            page_end=row["page_end"],
            heading_path=row["heading_path"],
            source_filename=row["source_filename"],
            document_id=row["document_id"],
        )

    def _semantic_scores(self, query: str) -> list[SearchResult]:
        """Score every chunk against the query (brute-force cosine), unsorted."""
        info = self.inspect()
        embedder = get_embedder(info.get("default_embedding_model") or "hashing")
        query_vec = embedder.embed([query])[0]
        rows = self.conn.execute(
            """
            SELECT c.*, d.source_filename, e.vector
            FROM chunks c
            JOIN documents d ON c.document_id = d.document_id
            JOIN embeddings e ON e.chunk_id = c.chunk_id
            ORDER BY c.sort_order
            """
        ).fetchall()
        scored = []
        for row in rows:
            vec = deserialize_vector(row["vector"])
            scored.append(self._row_to_result(row, cosine_similarity(query_vec, vec)))
        return scored

    def _semantic_search(self, query: str, top_k: int) -> list[SearchResult]:
        scored = self._semantic_scores(query)
        return sorted(scored, key=lambda r: r.score, reverse=True)[:top_k]

    def _keyword_search(self, query: str, top_k: int) -> list[SearchResult]:
        # FTS5 bm25 is lower-is-better; convert to bounded positive-ish score.
        sql = """
            SELECT c.*, d.source_filename, bm25(chunks_fts) AS rank
            FROM chunks_fts
            JOIN chunks c ON c.chunk_id = chunks_fts.chunk_id
            JOIN documents d ON c.document_id = d.document_id
            WHERE chunks_fts MATCH ?
            ORDER BY rank LIMIT ?
        """

        def safe_query(raw: str) -> str:
            terms = []
            for token in raw.split():
                cleaned = "".join(ch for ch in token if ch.isalnum() or ch == "_")
                if cleaned:
                    terms.append(f"{cleaned}*")
            return " OR ".join(terms) or raw

        try:
            rows = self.conn.execute(sql, (query, top_k)).fetchall()
        except sqlite3.OperationalError:
            rows = []
        if not rows:
            rows = self.conn.execute(sql, (safe_query(query), top_k)).fetchall()
        results = []
        for row in rows:
            rank = float(row["rank"])
            score = 1.0 / (1.0 + max(rank, 0.0)) if rank >= 0 else 1.0 + abs(rank)
            results.append(self._row_to_result(row, score))
        return results

    def _hybrid_search(self, query: str, top_k: int) -> list[SearchResult]:
        """Fuse semantic and keyword scores: hybrid = semantic*0.5 + keyword*0.5.

        Semantic search is brute-force, so every chunk has a true cosine score
        and keyword candidates are never starved of their semantic signal.
        Both score sets are min-max normalized to [0, 1] before weighting so
        the unbounded bm25-derived scores cannot swamp the cosine scores.
        Equal weights sit in the middle of the robust plateau found by
        sweeping weights over the GSMM and docling eval sets.
        """
        semantic = self._semantic_scores(query)
        keyword = self._keyword_search(query, max(top_k * 5, 50))

        def normalize(results: list[SearchResult]) -> dict[str, float]:
            if not results:
                return {}
            scores = [r.score for r in results]
            lo, hi = min(scores), max(scores)
            if hi <= lo:
                return {r.chunk_id: 1.0 for r in results}
            return {r.chunk_id: (r.score - lo) / (hi - lo) for r in results}

        sem_norm = normalize(semantic)
        key_norm = normalize(keyword)
        by_id = {r.chunk_id: r for r in semantic}
        for r in keyword:
            by_id.setdefault(r.chunk_id, r)
        results = []
        for chunk_id, result in by_id.items():
            combined = sem_norm.get(chunk_id, 0.0) * 0.5 + key_norm.get(chunk_id, 0.0) * 0.5
            copy = SearchResult(**result.as_dict())
            copy.score = combined
            results.append(copy)
        return sorted(results, key=lambda r: r.score, reverse=True)[:top_k]
