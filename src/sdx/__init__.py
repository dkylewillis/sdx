"""SDX — Semantic Document eXchange."""

from .convert import convert
from .document import SDXDocument, SearchResult

__all__ = ["convert", "SDXDocument", "SearchResult"]
