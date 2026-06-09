import json
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


def test_cli_json_output_for_agents(tmp_path):
    """Every command supports --json so agents can consume structured output."""
    pdf = tmp_path / "manual.pdf"
    out = tmp_path / "manual.sdx"
    make_pdf(pdf)

    def run(*argv):
        proc = subprocess.run(
            [sys.executable, "-m", "sdx.cli", *argv],
            text=True,
            capture_output=True,
            check=True,
        )
        return json.loads(proc.stdout)

    converted = run("convert", str(pdf), str(out), "--model", "hashing", "--json")
    assert converted["ok"] is True
    assert converted["output"].endswith("manual.sdx")

    info = run("inspect", str(out), "--json")
    assert info["format_version"] == "0.1"
    assert info["pages"] == 2

    report = run("validate", str(out), "--json")
    assert report["ok"] is True
    assert report["counts"]["chunks"] >= 2

    payload = run("search", str(out), "restaurant parking", "--mode", "hybrid", "--top-k", "2", "--json", "--figures")
    assert payload["query"] == "restaurant parking"
    assert payload["results"]
    first = payload["results"][0]
    assert {"chunk_id", "score", "text", "page_start", "heading_path", "figures"} <= set(first)
    assert "parking" in first["text"].lower()
