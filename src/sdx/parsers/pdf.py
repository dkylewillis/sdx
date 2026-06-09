from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ParsedPage:
    page_number: int
    width: float | None
    height: float | None
    text: str


def parse_pdf(path: str) -> list[ParsedPage]:
    try:
        import fitz  # PyMuPDF
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("PyMuPDF is required for PDF parsing: install sdx with pymupdf") from exc

    doc = fitz.open(path)
    pages: list[ParsedPage] = []
    try:
        for idx, page in enumerate(doc, start=1):
            rect = page.rect
            text = page.get_text("text") or ""
            pages.append(ParsedPage(idx, float(rect.width), float(rect.height), text.strip()))
    finally:
        doc.close()
    return pages
