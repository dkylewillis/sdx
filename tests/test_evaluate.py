import json

import pytest

from vera import convert
from vera.evaluate import QueryCase, evaluate, load_queries
from test_convert_search import make_pdf


@pytest.fixture
def vera_file(tmp_path):
    pdf = tmp_path / "doc.pdf"
    out = tmp_path / "doc.vera"
    make_pdf(pdf)
    convert(str(pdf), str(out), model="hashing", chunk_size=40, overlap=5)
    return out


def write_queries(tmp_path, cases):
    path = tmp_path / "queries.json"
    path.write_text(json.dumps(cases), encoding="utf-8")
    return path


def test_load_queries_normalizes_expected_page(tmp_path):
    path = write_queries(tmp_path, [{"query": "parking", "expected_page": 1}])
    cases = load_queries(str(path))
    assert cases[0].expected_pages == [1]


def test_load_queries_rejects_empty_list(tmp_path):
    path = write_queries(tmp_path, [])
    with pytest.raises(ValueError):
        load_queries(str(path))


def test_load_queries_rejects_case_without_expectations(tmp_path):
    path = write_queries(tmp_path, [{"query": "parking"}])
    with pytest.raises(ValueError):
        load_queries(str(path))


def test_load_queries_missing_file():
    with pytest.raises(FileNotFoundError):
        load_queries("does-not-exist.json")


def test_query_case_requires_query_text():
    with pytest.raises(ValueError):
        QueryCase(query="", expected_pages=[1])


def test_evaluate_hits_and_mrr(tmp_path, vera_file):
    queries = write_queries(
        tmp_path,
        [
            {"query": "restaurant parking", "expected_page": 1, "expected_terms": ["parking"]},
            {"query": "detention impervious area", "expected_page": 2, "expected_terms": ["detention"]},
        ],
    )
    summary = evaluate(str(vera_file), str(queries), mode="hybrid", top_k=3)
    report = summary["reports"][0]
    assert report["mode"] == "hybrid"
    assert report["hits"] == 2
    assert report["hit_rate"] == 1.0
    assert report["mrr"] > 0.0
    assert all(q["hit"] for q in report["queries"])


def test_evaluate_all_modes(tmp_path, vera_file):
    queries = write_queries(tmp_path, [{"query": "stormwater detention", "expected_page": 2}])
    summary = evaluate(str(vera_file), str(queries), mode="all", top_k=5)
    modes = [r["mode"] for r in summary["reports"]]
    assert modes == ["semantic", "keyword", "hybrid"]


def test_evaluate_records_miss(tmp_path, vera_file):
    queries = write_queries(tmp_path, [{"query": "restaurant parking", "expected_page": 99}])
    summary = evaluate(str(vera_file), str(queries), mode="keyword", top_k=3)
    report = summary["reports"][0]
    assert report["hits"] == 0
    assert report["mrr"] == 0.0
    assert report["queries"][0]["rank"] is None


def test_evaluate_invalid_mode(tmp_path, vera_file):
    queries = write_queries(tmp_path, [{"query": "parking", "expected_page": 1}])
    with pytest.raises(ValueError, match="mode must be"):
        evaluate(str(vera_file), str(queries), mode="fuzzy")


def test_cli_eval(tmp_path, vera_file):
    import subprocess
    import sys

    queries = write_queries(tmp_path, [{"query": "restaurant parking", "expected_page": 1}])
    proc = subprocess.run(
        [sys.executable, "-m", "vera.cli", "eval", str(vera_file), str(queries), "--mode", "hybrid", "--top-k", "3"],
        text=True,
        capture_output=True,
    )
    assert proc.returncode == 0
    assert "HIT" in proc.stdout
    assert "Hits: 1/1" in proc.stdout


def test_cli_eval_exit_code_on_miss(tmp_path, vera_file):
    import subprocess
    import sys

    queries = write_queries(tmp_path, [{"query": "restaurant parking", "expected_page": 99}])
    proc = subprocess.run(
        [sys.executable, "-m", "vera.cli", "eval", str(vera_file), str(queries), "--mode", "keyword"],
        text=True,
        capture_output=True,
    )
    assert proc.returncode == 1
    assert "MISS" in proc.stdout
