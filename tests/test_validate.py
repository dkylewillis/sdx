import sqlite3
import subprocess
import sys

from vera import VeraDocument, convert
from test_convert_search import make_pdf


def test_validate_passes_for_converted_vera(tmp_path):
    pdf = tmp_path / "ordinance.pdf"
    out = tmp_path / "ordinance.vera"
    make_pdf(pdf)
    convert(str(pdf), str(out), model="hashing", chunk_size=40, overlap=5)

    doc = VeraDocument.open(str(out))
    report = doc.validate()
    doc.close()

    assert report["ok"] is True
    assert report["issues"] == []
    assert report["counts"]["chunks"] >= 1
    assert report["counts"]["embeddings"] == report["counts"]["chunks"]
    assert report["checks"]["original_document_present"] is True


def test_validate_reports_missing_required_metadata(tmp_path):
    pdf = tmp_path / "ordinance.pdf"
    out = tmp_path / "ordinance.vera"
    make_pdf(pdf)
    convert(str(pdf), str(out), model="hashing")
    conn = sqlite3.connect(out)
    conn.execute("DELETE FROM vera_metadata WHERE key='format_version'")
    conn.commit()
    conn.close()

    doc = VeraDocument.open(str(out))
    report = doc.validate()
    doc.close()

    assert report["ok"] is False
    assert any("Missing required metadata key: format_version" in issue for issue in report["issues"])


def test_validate_reports_bad_embedding_dimension(tmp_path):
    pdf = tmp_path / "ordinance.pdf"
    out = tmp_path / "ordinance.vera"
    make_pdf(pdf)
    convert(str(pdf), str(out), model="hashing")
    conn = sqlite3.connect(out)
    conn.execute("UPDATE embeddings SET vector = ? WHERE embedding_id = 'emb_000001'", (b"bad",))
    conn.commit()
    conn.close()

    doc = VeraDocument.open(str(out))
    report = doc.validate()
    doc.close()

    assert report["ok"] is False
    assert any("Invalid embedding blob" in issue for issue in report["issues"])


def test_cli_validate_outputs_pass(tmp_path):
    pdf = tmp_path / "manual.pdf"
    out = tmp_path / "manual.vera"
    make_pdf(pdf)
    convert(str(pdf), str(out), model="hashing")

    result = subprocess.run(
        [sys.executable, "-m", "vera.cli", "validate", str(out)],
        text=True,
        capture_output=True,
        check=True,
    )

    assert "VERA validation: PASS" in result.stdout
    assert "Issues: 0" in result.stdout
