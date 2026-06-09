import sqlite3

from sdx import SDXDocument, convert


def make_pdf(path):
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Chapter 110 Zoning\nRestaurants require one parking space per 100 square feet.")
    page2 = doc.new_page()
    page2.insert_text((72, 72), "Stormwater Manual\nDetention is required when impervious area increases.")
    doc.save(path)
    doc.close()


def test_convert_pdf_populates_sdx_and_searches(tmp_path):
    pdf = tmp_path / "ordinance.pdf"
    out = tmp_path / "ordinance.sdx"
    make_pdf(pdf)

    convert(str(pdf), str(out), model="hashing", chunk_size=40, overlap=5)

    conn = sqlite3.connect(out)
    assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] >= 2
    assert conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0] >= 2
    assert conn.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0] >= 2
    assert conn.execute("SELECT COUNT(*) FROM assets WHERE asset_type='original_document'").fetchone()[0] == 1

    doc = SDXDocument.open(str(out))
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
