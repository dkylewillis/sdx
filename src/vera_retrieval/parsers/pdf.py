from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

_CAPTION_RE = re.compile(r"^(figure|fig\.?|table|diagram|exhibit|chart|map|photo)\s*[0-9]+([.:\-\u2013]|\s|$)", re.I)
_CAPTION_PROXIMITY = 60.0  # max vertical gap in points between caption and image


@dataclass
class ParsedPage:
    page_number: int
    width: float | None
    height: float | None
    text: str


@dataclass
class ParsedBlock:
    page_number: int
    block_type: str  # heading | paragraph | image
    text: str
    bbox: tuple[float, float, float, float] | None = None
    heading_level: int | None = None
    image_bytes: bytes | None = None
    image_ext: str = ""


def _open_fitz():
    try:
        import fitz  # PyMuPDF
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("PyMuPDF is required for PDF parsing: install vera with pymupdf") from exc
    return fitz


def parse_pdf(path: str) -> list[ParsedPage]:
    fitz = _open_fitz()
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


@dataclass
class _RawBlock:
    page_number: int
    text: str
    bbox: tuple[float, float, float, float]
    dominant_size: float
    bold: bool
    line_count: int
    image_bytes: bytes | None = None
    image_ext: str = ""
    rotated: bool = False


def _span_is_bold(span: dict) -> bool:
    return bool(span.get("flags", 0) & 16)


def _collect_raw_blocks(doc) -> tuple[list[ParsedPage], list[_RawBlock], Counter]:
    pages: list[ParsedPage] = []
    raw: list[_RawBlock] = []
    size_weights: Counter = Counter()
    for idx, page in enumerate(doc, start=1):
        rect = page.rect
        page_text = page.get_text("text") or ""
        pages.append(ParsedPage(idx, float(rect.width), float(rect.height), page_text.strip()))
        layout = page.get_text("dict")
        for block in layout.get("blocks", []):
            bbox = tuple(float(v) for v in block.get("bbox", (0, 0, 0, 0)))
            if block.get("type") == 1:
                raw.append(
                    _RawBlock(idx, "", bbox, 0.0, False, 0, block.get("image"), block.get("ext", "png"))
                )
                continue
            lines = block.get("lines", [])
            block_sizes: Counter = Counter()
            texts: list[str] = []
            bold_chars = 0
            total_chars = 0
            rotated_lines = 0
            for line in lines:
                direction = line.get("dir", (1.0, 0.0))
                if abs(float(direction[0])) < 0.99:
                    rotated_lines += 1
                line_parts = []
                for span in line.get("spans", []):
                    text = span.get("text", "")
                    stripped = text.strip()
                    if not stripped:
                        continue
                    line_parts.append(text)
                    size = round(float(span.get("size", 0.0)), 1)
                    block_sizes[size] += len(stripped)
                    size_weights[size] += len(stripped)
                    total_chars += len(stripped)
                    if _span_is_bold(span):
                        bold_chars += len(stripped)
                if line_parts:
                    texts.append("".join(line_parts).strip())
            text = "\n".join(t for t in texts if t).strip()
            if not text:
                continue
            dominant = block_sizes.most_common(1)[0][0] if block_sizes else 0.0
            bold = total_chars > 0 and bold_chars / total_chars > 0.8
            rotated = len(lines) > 0 and rotated_lines == len(lines)
            raw.append(_RawBlock(idx, text, bbox, dominant, bold, len(texts), rotated=rotated))
    return pages, raw, size_weights


def parse_pdf_structured(path: str) -> tuple[list[ParsedPage], list[ParsedBlock]]:
    """Parse a PDF into pages plus structured blocks.

    Detects headings via font size/weight relative to body text, keeps
    paragraphs as text blocks, and captures embedded images as image blocks.
    """
    fitz = _open_fitz()
    doc = fitz.open(path)
    try:
        pages, raw, size_weights = _collect_raw_blocks(doc)
    finally:
        doc.close()

    body_size = size_weights.most_common(1)[0][0] if size_weights else 11.0

    def is_heading(block: _RawBlock) -> bool:
        if block.rotated:
            return False
        if not block.text or len(block.text) > 300 or block.line_count > 3:
            return False
        if block.dominant_size >= body_size + 0.9:
            return True
        return block.bold and block.dominant_size >= body_size and len(block.text) < 120

    heading_sizes = sorted(
        {b.dominant_size for b in raw if b.text and is_heading(b)}, reverse=True
    )
    size_to_level = {size: min(idx + 1, 6) for idx, size in enumerate(heading_sizes)}

    blocks: list[ParsedBlock] = []
    for block in raw:
        if block.image_bytes is not None:
            blocks.append(
                ParsedBlock(
                    page_number=block.page_number,
                    block_type="image",
                    text="",
                    bbox=block.bbox,
                    image_bytes=block.image_bytes,
                    image_ext=block.image_ext or "png",
                )
            )
        elif is_heading(block):
            blocks.append(
                ParsedBlock(
                    page_number=block.page_number,
                    block_type="heading",
                    text=" ".join(block.text.split()),
                    bbox=block.bbox,
                    heading_level=size_to_level.get(block.dominant_size, 6),
                )
            )
        else:
            blocks.append(
                ParsedBlock(
                    page_number=block.page_number,
                    block_type="paragraph",
                    text=block.text,
                    bbox=block.bbox,
                )
            )
    _mark_captions(blocks)
    return pages, blocks


def _vertical_gap(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    """Vertical distance between two bboxes (0 when they overlap vertically)."""
    if a[3] < b[1]:
        return b[1] - a[3]
    if b[3] < a[1]:
        return a[1] - b[3]
    return 0.0


def _mark_captions(blocks: list[ParsedBlock]) -> None:
    """Reclassify text blocks as captions when they label a nearby image.

    A caption starts with a figure/table label (e.g. "Figure 3:") and sits
    vertically adjacent to an image block on the same page.
    """
    images_by_page: dict[int, list[ParsedBlock]] = {}
    for block in blocks:
        if block.block_type == "image":
            images_by_page.setdefault(block.page_number, []).append(block)
    for block in blocks:
        if block.block_type not in {"paragraph", "heading"}:
            continue
        first_line = block.text.splitlines()[0].strip() if block.text else ""
        if not _CAPTION_RE.match(first_line) or len(block.text) > 500:
            continue
        images = images_by_page.get(block.page_number, [])
        if not images or block.bbox is None:
            continue
        if any(
            img.bbox is not None and _vertical_gap(block.bbox, img.bbox) <= _CAPTION_PROXIMITY
            for img in images
        ):
            block.block_type = "caption"
            block.heading_level = None
