"""Retrieval quality evaluation for VERA files.

Runs a set of expected-answer queries against a VERA document and reports
hit rate and mean reciprocal rank (MRR) so chunking/embedding/search changes
can be compared objectively.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .document import VeraDocument, SearchResult

MODES = ("semantic", "keyword", "hybrid")


@dataclass
class QueryCase:
    query: str
    expected_pages: list[int] = field(default_factory=list)
    expected_terms: list[str] = field(default_factory=list)
    note: str = ""

    def __post_init__(self) -> None:
        if not self.query or not str(self.query).strip():
            raise ValueError("Query case is missing 'query' text")
        if not self.expected_pages and not self.expected_terms:
            raise ValueError(f"Query case {self.query!r} needs expected_pages and/or expected_terms")

    def matches(self, result: SearchResult) -> bool:
        if self.expected_pages:
            pages = {p for p in (result.page_start, result.page_end) if p is not None}
            if result.page_start is not None and result.page_end is not None:
                pages.update(range(result.page_start, result.page_end + 1))
            if not pages.intersection(self.expected_pages):
                return False
        if self.expected_terms:
            text = result.text.lower()
            if not all(term.lower() in text for term in self.expected_terms):
                return False
        return True


def _normalize_case(raw: dict[str, Any]) -> QueryCase:
    pages = raw.get("expected_pages") or []
    if "expected_page" in raw and raw["expected_page"] is not None:
        pages = list(pages) + [raw["expected_page"]]
    return QueryCase(
        query=str(raw.get("query", "")).strip(),
        expected_pages=[int(p) for p in pages],
        expected_terms=[str(t) for t in (raw.get("expected_terms") or [])],
        note=str(raw.get("note", "")),
    )


def load_queries(path: str) -> list[QueryCase]:
    """Load query cases from a JSON (or YAML, if pyyaml is installed) file."""
    file = Path(path)
    if not file.exists():
        raise FileNotFoundError(path)
    text = file.read_text(encoding="utf-8")
    if file.suffix.lower() in {".yaml", ".yml"}:
        try:
            import yaml
        except ImportError as exc:
            raise RuntimeError(
                "YAML query files require pyyaml: pip install pyyaml (or use a .json file)"
            ) from exc
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)
    if not isinstance(data, list) or not data:
        raise ValueError("Query file must contain a non-empty list of query cases")
    return [_normalize_case(item) for item in data]


def evaluate_document(
    doc: VeraDocument,
    cases: list[QueryCase],
    mode: str = "hybrid",
    top_k: int = 5,
) -> dict[str, Any]:
    """Evaluate one search mode against all query cases."""
    per_query = []
    reciprocal_ranks = []
    hits = 0
    for case in cases:
        results = doc.search(case.query, mode=mode, top_k=top_k)
        rank = None
        for idx, result in enumerate(results, start=1):
            if case.matches(result):
                rank = idx
                break
        hit = rank is not None
        hits += int(hit)
        reciprocal_ranks.append(1.0 / rank if rank else 0.0)
        per_query.append(
            {
                "query": case.query,
                "note": case.note,
                "hit": hit,
                "rank": rank,
                "top_score": results[0].score if results else None,
                "top_page": results[0].page_start if results else None,
            }
        )
    total = len(cases)
    return {
        "mode": mode,
        "top_k": top_k,
        "total": total,
        "hits": hits,
        "hit_rate": hits / total if total else 0.0,
        "mrr": sum(reciprocal_ranks) / total if total else 0.0,
        "queries": per_query,
    }


def evaluate(
    vera_path: str,
    queries_path: str,
    mode: str = "hybrid",
    top_k: int = 5,
) -> dict[str, Any]:
    """Evaluate a VERA file against a query file.

    mode may be one of semantic/keyword/hybrid, or "all" to compare every mode.
    """
    cases = load_queries(queries_path)
    modes = list(MODES) if mode == "all" else [mode]
    for m in modes:
        if m not in MODES:
            raise ValueError(f"mode must be one of {', '.join(MODES)}, or 'all'")
    doc = VeraDocument.open(vera_path)
    try:
        reports = [evaluate_document(doc, cases, mode=m, top_k=top_k) for m in modes]
    finally:
        doc.close()
    return {
        "file": vera_path,
        "queries_file": queries_path,
        "reports": reports,
    }
