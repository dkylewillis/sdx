from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from .embeddings import cosine_similarity, deserialize_vector, get_embedder


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

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


class SDXDocument:
    def __init__(self, path: str, conn: sqlite3.Connection):
        self.path = path
        self.conn = conn
        self.conn.row_factory = sqlite3.Row

    @classmethod
    def open(cls, path: str) -> "SDXDocument":
        conn = sqlite3.connect(path)
        return cls(path, conn)

    def close(self) -> None:
        self.conn.close()

    def inspect(self) -> dict[str, Any]:
        metadata = {row["key"]: row["value"] for row in self.conn.execute("SELECT key, value FROM sdx_metadata")}
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

    def search(self, query: str, mode: str = "hybrid", top_k: int = 10) -> list[SearchResult]:
        mode = mode.lower()
        if mode not in {"semantic", "keyword", "hybrid"}:
            raise ValueError("mode must be semantic, keyword, or hybrid")
        if mode == "semantic":
            return self._semantic_search(query, top_k)
        if mode == "keyword":
            return self._keyword_search(query, top_k)
        return self._hybrid_search(query, top_k)

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

    def _chunk_join_sql(self) -> str:
        return """
            SELECT c.*, d.source_filename
            FROM chunks c JOIN documents d ON c.document_id = d.document_id
        """

    def _semantic_search(self, query: str, top_k: int) -> list[SearchResult]:
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
        semantic = self._semantic_search(query, max(top_k, 20))
        keyword = self._keyword_search(query, max(top_k, 20))
        by_id: dict[str, SearchResult] = {}
        sem_scores = {r.chunk_id: r.score for r in semantic}
        key_scores = {r.chunk_id: r.score for r in keyword}
        for result in semantic + keyword:
            by_id[result.chunk_id] = result
        max_key = max(key_scores.values(), default=1.0) or 1.0
        results = []
        for chunk_id, result in by_id.items():
            sem = max(sem_scores.get(chunk_id, 0.0), 0.0)
            key = key_scores.get(chunk_id, 0.0) / max_key
            combined = (sem * 0.7) + (key * 0.3)
            copy = SearchResult(**result.as_dict())
            copy.score = combined
            results.append(copy)
        return sorted(results, key=lambda r: r.score, reverse=True)[:top_k]
