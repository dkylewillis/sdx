"""Tests for structured block parsing, heading-aware chunking, and figures."""

import sqlite3

import pytest

from vera import VeraDocument, convert
from vera.convert import build_chunks_from_blocks
from vera.parsers import ParsedBlock, parse_pdf_structured


def make_structured_pdf(path, with_image: bool = True):
    """PDF with sized headings, body text, and an embedded image."""
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Chapter 110 Zoning", fontsize=20)
    page.insert_text((72, 110), "Article 5 Parking", fontsize=16)
    page.insert_text(
        (72, 140),
        "Restaurants require one parking space per 100 square feet of floor area.",
        fontsize=11,
    )
    if with_image:
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 40, 40))
        pix.clear_with(128)
        page.insert_image(fitz.Rect(72, 200, 172, 300), pixmap=pix)
    page2 = doc.new_page()
    page2.insert_text((72, 72), "Chapter 200 Stormwater", fontsize=20)
    page2.insert_text(
        (72, 110),
        "Detention is required when impervious area increases beyond limits.",
        fontsize=11,
    )
    doc.save(path)
    doc.close()


@pytest.fixture
def structured_pdf(tmp_path):
    pdf = tmp_path / "structured.pdf"
    make_structured_pdf(pdf)
    return pdf


class TestParsePdfStructured:
    def test_detects_headings_and_paragraphs(self, structured_pdf):
        _, blocks = parse_pdf_structured(str(structured_pdf))
        types = {b.block_type for b in blocks}
        assert "heading" in types
        assert "paragraph" in types

    def test_larger_font_gets_higher_heading_level(self, structured_pdf):
        _, blocks = parse_pdf_structured(str(structured_pdf))
        headings = {b.text: b.heading_level for b in blocks if b.block_type == "heading"}
        assert headings["Chapter 110 Zoning"] < headings["Article 5 Parking"]

    def test_detects_embedded_image(self, structured_pdf):
        _, blocks = parse_pdf_structured(str(structured_pdf))
        images = [b for b in blocks if b.block_type == "image"]
        assert len(images) == 1
        assert images[0].page_number == 1
        assert images[0].image_bytes

    def test_pages_still_returned(self, structured_pdf):
        pages, _ = parse_pdf_structured(str(structured_pdf))
        assert len(pages) == 2
        assert "Zoning" in pages[0].text

    def test_rotated_text_is_not_a_heading(self, tmp_path):
        import fitz

        pdf = tmp_path / "rotated.pdf"
        doc = fitz.open()
        page = doc.new_page()
        # Vertical watermark in large type (like an arXiv sidebar).
        page.insert_text((30, 400), "arXiv:2408.09869v5", fontsize=22, rotate=90)
        page.insert_text((72, 72), "Chapter 1 Zoning", fontsize=20)
        page.insert_text((72, 110), "Body text about zoning regulations.", fontsize=11)
        doc.save(pdf)
        doc.close()

        _, blocks = parse_pdf_structured(str(pdf))
        headings = [b.text for b in blocks if b.block_type == "heading"]
        assert "Chapter 1 Zoning" in headings
        assert not any("arXiv" in h for h in headings)


class TestBuildChunksFromBlocks:
    def _blocks(self):
        return [
            ("b1", ParsedBlock(1, "heading", "Chapter 1 Zoning", heading_level=1)),
            ("b2", ParsedBlock(1, "heading", "Section 1.1 Parking", heading_level=2)),
            ("b3", ParsedBlock(1, "paragraph", "Parking spaces are required for restaurants.")),
            ("b4", ParsedBlock(2, "heading", "Chapter 2 Stormwater", heading_level=1)),
            ("b5", ParsedBlock(2, "paragraph", "Detention is required for impervious area.")),
        ]

    def test_hierarchical_heading_path(self):
        chunks = build_chunks_from_blocks(self._blocks())
        assert chunks[0].heading_path == "Chapter 1 Zoning > Section 1.1 Parking"

    def test_heading_stack_pops_same_level(self):
        chunks = build_chunks_from_blocks(self._blocks())
        assert chunks[1].heading_path == "Chapter 2 Stormwater"

    def test_chunks_record_block_ids(self):
        chunks = build_chunks_from_blocks(self._blocks())
        assert chunks[0].block_ids == ["b3"]
        assert chunks[1].block_ids == ["b5"]

    def test_image_blocks_excluded_from_text(self):
        blocks = [
            ("b1", ParsedBlock(1, "paragraph", "Some text here.")),
            ("b2", ParsedBlock(1, "image", "", image_bytes=b"fake")),
        ]
        chunks = build_chunks_from_blocks(blocks)
        assert len(chunks) == 1
        assert "fake" not in chunks[0].text

    def test_long_block_split_with_sliding_window(self):
        words = " ".join(f"w{i}" for i in range(50))
        blocks = [("b1", ParsedBlock(1, "paragraph", words))]
        chunks = build_chunks_from_blocks(blocks, chunk_size=10, overlap=2)
        assert len(chunks) > 1
        assert all(c.block_ids == ["b1"] for c in chunks)

    def test_invalid_chunk_size_raises(self):
        with pytest.raises(ValueError):
            build_chunks_from_blocks([], chunk_size=0)

    def test_chunks_do_not_merge_across_pages(self):
        blocks = [
            ("b1", ParsedBlock(1, "paragraph", "one " * 30)),
            ("b2", ParsedBlock(2, "paragraph", "two " * 30)),
        ]
        chunks = build_chunks_from_blocks(blocks, chunk_size=500)
        assert len(chunks) == 2
        assert (chunks[0].page_start, chunks[0].page_end) == (1, 1)
        assert (chunks[1].page_start, chunks[1].page_end) == (2, 2)


class TestConvertWithBlocks:
    def test_blocks_and_chunk_blocks_populated(self, tmp_path, structured_pdf):
        out = tmp_path / "out.vera"
        convert(str(structured_pdf), str(out), model="hashing")
        conn = sqlite3.connect(out)
        assert conn.execute("SELECT COUNT(*) FROM blocks WHERE block_type='heading'").fetchone()[0] >= 3
        assert conn.execute("SELECT COUNT(*) FROM blocks WHERE block_type='image'").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM chunk_blocks").fetchone()[0] >= 1
        conn.close()

    def test_heading_path_stored_in_chunks(self, tmp_path, structured_pdf):
        out = tmp_path / "out.vera"
        convert(str(structured_pdf), str(out), model="hashing")
        conn = sqlite3.connect(out)
        paths = [row[0] for row in conn.execute("SELECT heading_path FROM chunks")]
        conn.close()
        assert any("Chapter 110 Zoning" in (p or "") for p in paths)

    def test_image_asset_stored(self, tmp_path, structured_pdf):
        out = tmp_path / "out.vera"
        convert(str(structured_pdf), str(out), model="hashing")
        conn = sqlite3.connect(out)
        count = conn.execute("SELECT COUNT(*) FROM assets WHERE asset_type='extracted_image'").fetchone()[0]
        conn.close()
        assert count == 1

    def test_validation_still_passes(self, tmp_path, structured_pdf):
        out = tmp_path / "out.vera"
        convert(str(structured_pdf), str(out), model="hashing")
        doc = VeraDocument.open(str(out))
        try:
            report = doc.validate()
        finally:
            doc.close()
        assert report["ok"], report["issues"]


class TestFiguresAPI:
    @pytest.fixture
    def vera_doc(self, tmp_path, structured_pdf):
        out = tmp_path / "out.vera"
        convert(str(structured_pdf), str(out), model="hashing")
        doc = VeraDocument.open(str(out))
        yield doc
        doc.close()

    def test_figures_lists_extracted_images(self, vera_doc):
        figures = vera_doc.figures()
        assert len(figures) == 1
        assert figures[0]["page_number"] == 1
        assert figures[0]["mime_type"].startswith("image/")
        assert "data" not in figures[0]

    def test_figures_include_data(self, vera_doc):
        figures = vera_doc.figures(include_data=True)
        assert figures[0]["data"]

    def test_figures_page_filter(self, vera_doc):
        assert len(vera_doc.figures(page_start=1, page_end=1)) == 1
        assert vera_doc.figures(page_start=2, page_end=2) == []

    def test_figures_for_search_result(self, vera_doc):
        result = vera_doc.search("restaurant parking", mode="keyword", top_k=1)[0]
        assert result.page_start == 1
        figures = vera_doc.figures_for(result)
        assert len(figures) == 1

    def test_no_figures_for_other_page_result(self, vera_doc):
        result = vera_doc.search("detention impervious", mode="keyword", top_k=1)[0]
        assert result.page_start == 2
        assert vera_doc.figures_for(result) == []


def make_captioned_pdf(path):
    """PDF with an image followed by a caption, plus a decoy 'Table 1' sentence far away."""
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Chapter 5 Stormwater Design", fontsize=20)
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 40, 40))
    pix.clear_with(90)
    page.insert_image(fitz.Rect(72, 120, 272, 270), pixmap=pix)
    page.insert_text((72, 295), "Figure 3: Detention pond sizing diagram", fontsize=10)
    page.insert_text(
        (72, 600),
        "Table 1 lists requirements but this paragraph is far from any image and long enough to read like prose.",
        fontsize=11,
    )
    doc.save(path)
    doc.close()


class TestCaptions:
    @pytest.fixture
    def captioned_pdf(self, tmp_path):
        pdf = tmp_path / "captioned.pdf"
        make_captioned_pdf(pdf)
        return pdf

    def test_caption_block_detected(self, captioned_pdf):
        _, blocks = parse_pdf_structured(str(captioned_pdf))
        captions = [b for b in blocks if b.block_type == "caption"]
        assert len(captions) == 1
        assert "Detention pond sizing" in captions[0].text

    def test_distant_table_sentence_not_marked_caption(self, captioned_pdf):
        _, blocks = parse_pdf_structured(str(captioned_pdf))
        captions = [b.text for b in blocks if b.block_type == "caption"]
        assert not any("Table 1 lists" in c for c in captions)

    def test_caption_text_searchable_in_chunks(self, tmp_path, captioned_pdf):
        out = tmp_path / "out.vera"
        convert(str(captioned_pdf), str(out), model="hashing")
        doc = VeraDocument.open(str(out))
        try:
            results = doc.search("detention pond sizing diagram", mode="keyword", top_k=1)
            assert results
            assert "detention pond sizing" in results[0].text.lower()
        finally:
            doc.close()

    def test_figures_return_caption(self, tmp_path, captioned_pdf):
        out = tmp_path / "out.vera"
        convert(str(captioned_pdf), str(out), model="hashing")
        doc = VeraDocument.open(str(out))
        try:
            figures = doc.figures()
            assert len(figures) == 1
            assert figures[0]["caption"] is not None
            assert "Detention pond sizing" in figures[0]["caption"]
        finally:
            doc.close()

    def test_figure_without_caption_returns_none(self, tmp_path, structured_pdf):
        out = tmp_path / "out.vera"
        convert(str(structured_pdf), str(out), model="hashing")
        doc = VeraDocument.open(str(out))
        try:
            figures = doc.figures()
            assert figures[0]["caption"] is None
        finally:
            doc.close()
