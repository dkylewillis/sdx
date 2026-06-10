"""Tests for document access APIs (source document, pages, blocks, assets)
and visual grounding (chunk regions)."""

import json
import subprocess
import sys

import pytest

from vera import SourceDocument, VeraDocument, convert
from test_blocks_figures import make_structured_pdf


@pytest.fixture
def vera_doc(tmp_path):
    pdf = tmp_path / "structured.pdf"
    make_structured_pdf(pdf)
    out = tmp_path / "structured.vera"
    convert(str(pdf), str(out), model="hashing")
    doc = VeraDocument.open(str(out))
    yield doc, pdf, out
    doc.close()


class TestGetSourceDocument:
    def test_returns_original_bytes(self, vera_doc):
        doc, pdf, _ = vera_doc
        source = doc.get_source_document()
        assert isinstance(source, SourceDocument)
        assert source.data == pdf.read_bytes()

    def test_metadata_fields(self, vera_doc):
        doc, pdf, _ = vera_doc
        source = doc.get_source_document()
        assert source.filename == pdf.name
        assert source.mime_type == "application/pdf"
        assert source.hash == doc.inspect()["source_file_hash"]

    def test_raises_when_original_not_stored(self, tmp_path):
        pdf = tmp_path / "nosave.pdf"
        make_structured_pdf(pdf)
        out = tmp_path / "nosave.vera"
        convert(str(pdf), str(out), model="hashing", store_original=False)
        doc = VeraDocument.open(str(out))
        try:
            with pytest.raises(ValueError):
                doc.get_source_document()
        finally:
            doc.close()


class TestExportSourceDocument:
    def test_export_to_explicit_path(self, vera_doc, tmp_path):
        doc, pdf, _ = vera_doc
        target = tmp_path / "exported" / "copy.pdf"
        written = doc.export_source_document(str(target))
        assert written == str(target)
        assert target.read_bytes() == pdf.read_bytes()

    def test_export_to_directory_uses_stored_filename(self, vera_doc, tmp_path):
        doc, pdf, _ = vera_doc
        outdir = tmp_path / "outdir"
        outdir.mkdir()
        written = doc.export_source_document(str(outdir))
        assert written == str(outdir / pdf.name)
        assert (outdir / pdf.name).read_bytes() == pdf.read_bytes()


class TestGetPage:
    def test_returns_text_and_dimensions(self, vera_doc):
        doc, _, _ = vera_doc
        page = doc.get_page(1)
        assert page["page_number"] == 1
        assert "Zoning" in page["text"]
        assert page["width"] > 0
        assert page["height"] > 0

    def test_missing_page_returns_none(self, vera_doc):
        doc, _, _ = vera_doc
        assert doc.get_page(99) is None


class TestGetBlocks:
    def test_all_blocks_in_reading_order(self, vera_doc):
        doc, _, _ = vera_doc
        blocks = doc.get_blocks()
        assert blocks
        orders = [b["sort_order"] for b in blocks]
        assert orders == sorted(orders)
        types = {b["block_type"] for b in blocks}
        assert "heading" in types
        assert "paragraph" in types

    def test_filter_by_page(self, vera_doc):
        doc, _, _ = vera_doc
        blocks = doc.get_blocks(page_number=2)
        assert blocks
        assert all(b["page_number"] == 2 for b in blocks)

    def test_bbox_parsed_as_list(self, vera_doc):
        doc, _, _ = vera_doc
        blocks = doc.get_blocks(page_number=1)
        boxed = [b for b in blocks if b["bbox"] is not None]
        assert boxed
        assert len(boxed[0]["bbox"]) == 4


class TestGetAsset:
    def test_original_document_asset(self, vera_doc):
        doc, pdf, _ = vera_doc
        asset = doc.get_asset("asset_original_001")
        assert asset["asset_type"] == "original_document"
        assert asset["data"] == pdf.read_bytes()

    def test_without_data(self, vera_doc):
        doc, _, _ = vera_doc
        asset = doc.get_asset("asset_original_001", include_data=False)
        assert "data" not in asset
        assert asset["mime_type"] == "application/pdf"

    def test_missing_asset_returns_none(self, vera_doc):
        doc, _, _ = vera_doc
        assert doc.get_asset("nope") is None


class TestChunkRegions:
    def test_regions_have_bbox_and_page_dimensions(self, vera_doc):
        doc, _, _ = vera_doc
        chunk = doc.conn.execute("SELECT chunk_id, page_start FROM chunks LIMIT 1").fetchone()
        regions = doc.get_chunk_regions(chunk["chunk_id"])
        assert regions
        for region in regions:
            assert region["page_number"] == chunk["page_start"]
            assert len(region["bbox"]) == 4
            assert region["page_width"] > 0
            assert region["page_height"] > 0

    def test_unknown_chunk_returns_empty(self, vera_doc):
        doc, _, _ = vera_doc
        assert doc.get_chunk_regions("chunk_999999") == []

    def test_regions_for_search_result(self, vera_doc):
        doc, _, _ = vera_doc
        results = doc.search("detention impervious", mode="keyword", top_k=1)
        assert results
        regions = doc.regions_for(results[0])
        assert regions
        pages = {r["page_number"] for r in regions}
        assert pages <= set(range(results[0].page_start, results[0].page_end + 1))


class TestCli:
    def run(self, *argv):
        proc = subprocess.run(
            [sys.executable, "-m", "vera.cli", *argv],
            capture_output=True,
            text=True,
        )
        return proc

    def test_export_command(self, vera_doc, tmp_path):
        _, pdf, out = vera_doc
        target = tmp_path / "cli_export.pdf"
        proc = self.run("export", str(out), str(target), "--json")
        assert proc.returncode == 0
        payload = json.loads(proc.stdout)
        assert payload["ok"] is True
        assert payload["mime_type"] == "application/pdf"
        assert target.read_bytes() == pdf.read_bytes()

    def test_export_fails_without_original(self, tmp_path):
        pdf = tmp_path / "nosave.pdf"
        make_structured_pdf(pdf)
        out = tmp_path / "nosave.vera"
        convert(str(pdf), str(out), model="hashing", store_original=False)
        proc = self.run("export", str(out), "--json")
        assert proc.returncode == 1
        assert json.loads(proc.stdout)["ok"] is False

    def test_search_with_regions(self, vera_doc):
        _, _, out = vera_doc
        proc = self.run("search", str(out), "parking", "--top-k", "1", "--json", "--regions")
        assert proc.returncode == 0
        payload = json.loads(proc.stdout)
        first = payload["results"][0]
        assert "regions" in first
        assert first["regions"]
        assert len(first["regions"][0]["bbox"]) == 4
