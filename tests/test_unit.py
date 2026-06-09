"""Unit tests for individual modules (no PDF file required for most cases)."""

import pytest

from sdx.convert import chunk_pages, _detect_heading
from sdx.embeddings import (
    HashingEmbedder,
    cosine_similarity,
    deserialize_vector,
    get_embedder,
    serialize_vector,
)
from sdx.document import SDXDocument, SearchResult
from sdx.cli import _str_to_bool
from sdx.parsers.pdf import ParsedPage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pages(*texts: str) -> list[ParsedPage]:
    """Build a list of ParsedPage objects from plain strings."""
    return [ParsedPage(page_number=i + 1, width=612.0, height=792.0, text=t)
            for i, t in enumerate(texts)]


# ---------------------------------------------------------------------------
# chunk_pages
# ---------------------------------------------------------------------------

class TestChunkPages:
    def test_empty_pages_returns_no_chunks(self):
        assert chunk_pages([]) == []

    def test_invalid_chunk_size_raises(self):
        with pytest.raises(ValueError, match="chunk_size must be positive"):
            chunk_pages(_pages("hello world"), chunk_size=0)

    def test_negative_chunk_size_raises(self):
        with pytest.raises(ValueError, match="chunk_size must be positive"):
            chunk_pages(_pages("hello world"), chunk_size=-1)

    def test_page_with_empty_text_produces_no_chunks(self):
        assert chunk_pages(_pages("")) == []

    def test_page_with_only_whitespace_produces_no_chunks(self):
        assert chunk_pages(_pages("   \n\n  ")) == []

    def test_short_text_produces_one_chunk(self):
        chunks = chunk_pages(_pages("The quick brown fox."), chunk_size=500)
        assert len(chunks) == 1
        assert "fox" in chunks[0].text

    def test_chunk_page_numbers_are_preserved(self):
        chunks = chunk_pages(_pages("Page one text.", "Page two text."), chunk_size=500)
        page_numbers = {c.page_start for c in chunks}
        assert 1 in page_numbers
        assert 2 in page_numbers

    def test_large_paragraph_is_split_into_multiple_chunks(self):
        # 120 words > chunk_size=10
        words = " ".join(f"word{i}" for i in range(120))
        chunks = chunk_pages(_pages(words), chunk_size=10, overlap=2)
        assert len(chunks) > 1

    def test_overlap_is_clamped_to_chunk_size_minus_one(self):
        # overlap >= chunk_size should be clamped rather than crash
        words = " ".join(f"w{i}" for i in range(30))
        chunks = chunk_pages(_pages(words), chunk_size=5, overlap=10)
        assert len(chunks) >= 1

    def test_all_chunks_have_positive_token_count(self):
        text = " ".join(f"token{i}" for i in range(50))
        chunks = chunk_pages(_pages(text), chunk_size=10, overlap=2)
        for c in chunks:
            assert c.token_count > 0

    def test_heading_detected_from_chapter_line(self):
        text = "Chapter 3 Land Use\nSome content about land use regulations."
        chunks = chunk_pages(_pages(text), chunk_size=500)
        assert any("chapter" in (c.heading_path or "").lower() for c in chunks)

    def test_heading_detected_from_section_line(self):
        text = "Section 4.2 Zoning Districts\nContent describing the districts."
        chunks = chunk_pages(_pages(text), chunk_size=500)
        assert any("section" in (c.heading_path or "").lower() for c in chunks)

    def test_no_heading_uses_empty_string(self):
        chunks = chunk_pages(_pages("Just some plain text with no heading."), chunk_size=500)
        assert chunks[0].heading_path == ""


# ---------------------------------------------------------------------------
# _detect_heading
# ---------------------------------------------------------------------------

class TestDetectHeading:
    def test_chapter_line_detected(self):
        result = _detect_heading("Chapter 1 Introduction\nText here.", "")
        assert "Chapter" in result

    def test_non_heading_line_returns_current(self):
        result = _detect_heading("This is just a sentence.", "current heading")
        assert result == "current heading"

    def test_very_long_line_is_not_a_heading(self):
        long_line = "word " * 30  # > 120 chars
        result = _detect_heading(long_line.strip(), "old heading")
        assert result == "old heading"


# ---------------------------------------------------------------------------
# cosine_similarity
# ---------------------------------------------------------------------------

class TestCosineSimilarity:
    def test_identical_vectors_return_one(self):
        import numpy as np
        v = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        assert pytest.approx(cosine_similarity(v, v), abs=1e-6) == 1.0

    def test_orthogonal_vectors_return_zero(self):
        import numpy as np
        a = np.array([1.0, 0.0], dtype=np.float32)
        b = np.array([0.0, 1.0], dtype=np.float32)
        assert pytest.approx(cosine_similarity(a, b), abs=1e-6) == 0.0

    def test_zero_vector_returns_zero(self):
        import numpy as np
        z = np.zeros(4, dtype=np.float32)
        v = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
        assert cosine_similarity(z, v) == 0.0

    def test_both_zero_vectors_return_zero(self):
        import numpy as np
        z = np.zeros(4, dtype=np.float32)
        assert cosine_similarity(z, z) == 0.0


# ---------------------------------------------------------------------------
# HashingEmbedder
# ---------------------------------------------------------------------------

class TestHashingEmbedder:
    def test_dimension_matches_output(self):
        emb = HashingEmbedder(dimension=128)
        vecs = emb.embed(["hello world"])
        assert vecs[0].shape == (128,)

    def test_empty_text_list_returns_empty(self):
        emb = HashingEmbedder()
        assert emb.embed([]) == []

    def test_vectors_are_normalised(self):
        import numpy as np
        emb = HashingEmbedder()
        v = emb.embed(["some text here"])[0]
        assert pytest.approx(float(np.linalg.norm(v)), abs=1e-5) == 1.0

    def test_same_text_produces_same_vector(self):
        emb = HashingEmbedder()
        v1 = emb.embed(["deterministic test"])[0]
        v2 = emb.embed(["deterministic test"])[0]
        assert (v1 == v2).all()

    def test_different_texts_produce_different_vectors(self):
        emb = HashingEmbedder()
        v1 = emb.embed(["apples and oranges"])[0]
        v2 = emb.embed(["quantum mechanics theory"])[0]
        assert not (v1 == v2).all()


# ---------------------------------------------------------------------------
# get_embedder
# ---------------------------------------------------------------------------

class TestGetEmbedder:
    def test_hashing_keyword_returns_hashing_embedder(self):
        e = get_embedder("hashing")
        assert isinstance(e, HashingEmbedder)

    def test_unknown_model_falls_back_to_hashing_with_custom_name(self):
        e = get_embedder("my-custom-model-xyz")
        assert isinstance(e, HashingEmbedder)
        assert e.model_name == "my-custom-model-xyz"


# ---------------------------------------------------------------------------
# serialize / deserialize vector round-trip
# ---------------------------------------------------------------------------

class TestVectorSerialization:
    def test_round_trip_preserves_values(self):
        original = [1.5, -0.25, 3.0, 0.0]
        blob = serialize_vector(original)
        recovered = deserialize_vector(blob).tolist()
        assert recovered == pytest.approx(original, abs=1e-6)

    def test_serialization_produces_bytes(self):
        blob = serialize_vector([1.0, 2.0])
        assert isinstance(blob, bytes)

    def test_byte_length_is_four_per_float(self):
        blob = serialize_vector([0.0] * 10)
        assert len(blob) == 40  # 10 * 4 bytes (float32)


# ---------------------------------------------------------------------------
# SearchResult
# ---------------------------------------------------------------------------

class TestSearchResult:
    def _make(self, **kwargs):
        defaults = dict(
            chunk_id="c001",
            score=0.85,
            text="Sample text",
            page_start=1,
            page_end=1,
            heading_path="Chapter 1",
            source_filename="doc.pdf",
            document_id="doc_001",
        )
        defaults.update(kwargs)
        return SearchResult(**defaults)

    def test_as_dict_contains_all_fields(self):
        r = self._make()
        d = r.as_dict()
        assert d["chunk_id"] == "c001"
        assert d["score"] == pytest.approx(0.85)
        assert d["text"] == "Sample text"
        assert d["page_start"] == 1

    def test_as_dict_is_a_copy(self):
        r = self._make()
        d = r.as_dict()
        d["score"] = 0.0
        assert r.score == pytest.approx(0.85)


# ---------------------------------------------------------------------------
# SDXDocument.search — invalid mode
# ---------------------------------------------------------------------------

class TestSDXDocumentSearchValidation:
    def test_invalid_mode_raises_value_error(self, tmp_path):
        from test_convert_search import make_pdf
        from sdx import convert

        pdf = tmp_path / "test.pdf"
        sdx = tmp_path / "test.sdx"
        make_pdf(pdf)
        convert(str(pdf), str(sdx), model="hashing")

        doc = SDXDocument.open(str(sdx))
        try:
            with pytest.raises(ValueError, match="mode must be"):
                doc.search("query", mode="fuzzy")
        finally:
            doc.close()


# ---------------------------------------------------------------------------
# convert() — error paths
# ---------------------------------------------------------------------------

class TestConvertErrors:
    def test_missing_input_raises_file_not_found(self, tmp_path):
        from sdx.convert import convert as sdx_convert

        with pytest.raises(FileNotFoundError):
            sdx_convert(str(tmp_path / "missing.pdf"), str(tmp_path / "out.sdx"))

    def test_unsupported_parser_raises_value_error(self, tmp_path):
        from test_convert_search import make_pdf
        from sdx.convert import convert as sdx_convert

        pdf = tmp_path / "test.pdf"
        make_pdf(pdf)
        with pytest.raises(ValueError, match="parser"):
            sdx_convert(str(pdf), str(tmp_path / "out.sdx"), parser="tika")


# ---------------------------------------------------------------------------
# _str_to_bool (CLI helper)
# ---------------------------------------------------------------------------

class TestStrToBool:
    @pytest.mark.parametrize("value", ["true", "True", "TRUE", "1", "yes", "YES", "y", "on"])
    def test_truthy_values(self, value):
        assert _str_to_bool(value) is True

    @pytest.mark.parametrize("value", ["false", "False", "0", "no", "n", "off", "", "random"])
    def test_falsy_values(self, value):
        assert _str_to_bool(value) is False
