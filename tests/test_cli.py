import subprocess
import sys

from test_convert_search import make_pdf


def test_cli_convert_inspect_search(tmp_path):
    pdf = tmp_path / "manual.pdf"
    out = tmp_path / "manual.sdx"
    make_pdf(pdf)

    convert_cmd = [sys.executable, "-m", "sdx.cli", "convert", str(pdf), str(out), "--model", "hashing"]
    converted = subprocess.run(convert_cmd, text=True, capture_output=True, check=True)
    assert "Created" in converted.stdout

    inspected = subprocess.run(
        [sys.executable, "-m", "sdx.cli", "inspect", str(out)],
        text=True,
        capture_output=True,
        check=True,
    )
    assert "Format: SDX v0.1" in inspected.stdout
    assert "Chunks:" in inspected.stdout

    searched = subprocess.run(
        [sys.executable, "-m", "sdx.cli", "search", str(out), "restaurant parking", "--mode", "hybrid", "--top-k", "1"],
        text=True,
        capture_output=True,
        check=True,
    )
    assert "Score:" in searched.stdout
    assert "Page: 1" in searched.stdout
    assert "parking" in searched.stdout.lower()
