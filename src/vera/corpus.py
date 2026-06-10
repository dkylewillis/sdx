"""Corpus search: query a folder of .vera files as a single collection."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .document import SearchResult, VeraDocument

_RRF_K = 60.0


@dataclass
class CorpusSearchResult(SearchResult):
    """A search result attributed to the .vera file it came from."""

    file: str = ""


def _with_file(result: SearchResult, file: str) -> CorpusSearchResult:
    return CorpusSearchResult(file=file, **result.as_dict())


class VeraCorpus:
    """A folder of .vera files searchable as one corpus.

    Documents are opened lazily on first use and kept open (so embedding
    matrices and connections are reused across queries) until close().
    Each file's query embedding uses that file's recorded embedding model,
    so a corpus may mix models.

    Ranking: semantic results are merged by raw cosine score (comparable
    across files that share a model). Keyword and hybrid scores are only
    normalized within a file, so those modes are fused by reciprocal-rank
    fusion (RRF) with the within-file score as tiebreaker; each result keeps
    its within-file score, which is not comparable across files.
    """

    def __init__(self, directory: str, paths: list[str]):
        self.directory = directory
        self.paths = paths
        self._docs: dict[str, VeraDocument] = {}

    @classmethod
    def open(cls, directory: str) -> "VeraCorpus":
        root = Path(directory)
        if not root.is_dir():
            raise NotADirectoryError(directory)
        paths = sorted(str(p) for p in root.glob("*.vera"))
        if not paths:
            raise FileNotFoundError(f"No .vera files found in {directory}")
        return cls(str(root), paths)

    def document(self, file: str) -> VeraDocument:
        """Return the (cached) open VeraDocument for a file in this corpus."""
        if file not in self._docs:
            self._docs[file] = VeraDocument.open(file)
        return self._docs[file]

    def close(self) -> None:
        for doc in self._docs.values():
            doc.close()
        self._docs.clear()

    def __enter__(self) -> "VeraCorpus":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def inspect(self) -> dict[str, Any]:
        """Summarize the corpus: file count, total pages/chunks, models used."""
        files = []
        total_pages = 0
        total_chunks = 0
        models = set()
        for path in self.paths:
            info = self.document(path).inspect()
            files.append(
                {
                    "file": path,
                    "source": info.get("source"),
                    "pages": info.get("pages"),
                    "chunks": info.get("chunks"),
                    "embedding_model": info.get("default_embedding_model"),
                }
            )
            total_pages += info.get("pages") or 0
            total_chunks += info.get("chunks") or 0
            models.add(info.get("default_embedding_model"))
        return {
            "directory": self.directory,
            "file_count": len(self.paths),
            "pages": total_pages,
            "chunks": total_chunks,
            "embedding_models": sorted(m for m in models if m),
            "files": files,
        }

    def search(
        self,
        query: str,
        mode: str = "hybrid",
        top_k: int = 10,
        context_chunks: int = 0,
    ) -> list[CorpusSearchResult]:
        """Search every file in the corpus and return the fused top_k results."""
        mode = mode.lower()
        if mode not in {"semantic", "keyword", "hybrid"}:
            raise ValueError("mode must be semantic, keyword, or hybrid")
        per_file = {path: self.document(path).search(query, mode=mode, top_k=top_k) for path in self.paths}
        if mode == "semantic":
            merged = [_with_file(r, path) for path, results in per_file.items() for r in results]
            merged.sort(key=lambda r: r.score, reverse=True)
            final = merged[:top_k]
        else:
            final = self._fuse_rrf(per_file, top_k)
        if context_chunks:
            for result in final:
                doc = self.document(result.file)
                before, after = doc._context_chunks_for(result.chunk_id, context_chunks)
                result.before_chunks = before
                result.after_chunks = after
        return final

    @staticmethod
    def _fuse_rrf(per_file: dict[str, list[SearchResult]], top_k: int) -> list[CorpusSearchResult]:
        fused: list[tuple[float, float, str, SearchResult]] = []
        for path, results in per_file.items():
            for rank, result in enumerate(results, start=1):
                fused.append((1.0 / (_RRF_K + rank), result.score, path, result))
        fused.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [_with_file(result, path) for _, _, path, result in fused[:top_k]]

    def regions_for(self, result: CorpusSearchResult) -> list[dict[str, Any]]:
        """Return highlight regions for a corpus result (see VeraDocument.get_chunk_regions)."""
        return self.document(result.file).regions_for(result)

    def figures_for(self, result: CorpusSearchResult, include_data: bool = False) -> list[dict[str, Any]]:
        """Return figures on the pages of a corpus result."""
        return self.document(result.file).figures_for(result, include_data=include_data)
