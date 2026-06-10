import sqlite3

from vera import VeraDocument, convert


def make_pdf(path):
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Chapter 110 Zoning\nRestaurants require one parking space per 100 square feet.")
    page2 = doc.new_page()
    page2.insert_text((72, 72), "Stormwater Manual\nDetention is required when impervious area increases.")
    doc.save(path)
    doc.close()


def test_convert_pdf_populates_vera_and_searches(tmp_path):
    pdf = tmp_path / "ordinance.pdf"
    out = tmp_path / "ordinance.vera"
    make_pdf(pdf)

    convert(str(pdf), str(out), model="hashing", chunk_size=40, overlap=5)

    conn = sqlite3.connect(out)
    assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] >= 2
    assert conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0] >= 2
    assert conn.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0] >= 2
    assert conn.execute("SELECT COUNT(*) FROM assets WHERE asset_type='original_document'").fetchone()[0] == 1

    doc = VeraDocument.open(str(out))
    info = doc.inspect()
    assert info["format_version"] == "0.1"
    assert info["pages"] == 2

    keyword = doc.search("restaurant parking", mode="keyword", top_k=1)[0]
    assert "parking" in keyword.text.lower()
    assert keyword.page_start == 1

    semantic = doc.search("detention impervious area", mode="semantic", top_k=1)[0]
    assert "detention" in semantic.text.lower()
    assert semantic.page_start == 2

    hybrid = doc.search("streamwater detention required", mode="hybrid", top_k=2)
    assert hybrid
    assert hybrid[0].score >= hybrid[-1].score
    doc.close()


def test_hybrid_keeps_chunk_that_tops_both_modes(tmp_path):
    """Regression: a chunk ranked #1 by both semantic and keyword search must
    rank #1 in hybrid. The old fusion buried dual-mode winners behind chunks
    that merely appeared in both candidate pools."""
    pdf = tmp_path / "ordinance.pdf"
    out = tmp_path / "ordinance.vera"
    make_pdf(pdf)
    convert(str(pdf), str(out), model="hashing", chunk_size=40, overlap=5)

    doc = VeraDocument.open(str(out))
    query = "restaurant parking space requirements"
    top_sem = doc.search(query, mode="semantic", top_k=1)[0]
    top_key = doc.search(query, mode="keyword", top_k=1)[0]
    if top_sem.chunk_id == top_key.chunk_id:
        top_hybrid = doc.search(query, mode="hybrid", top_k=1)[0]
        assert top_hybrid.chunk_id == top_sem.chunk_id
    doc.close()
