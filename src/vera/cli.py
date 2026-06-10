from __future__ import annotations

import argparse
import json
import sys

from .convert import convert
from .document import VeraDocument


def _str_to_bool(value: str) -> bool:
    return str(value).lower() in {"1", "true", "yes", "y", "on"}


def cmd_convert(args) -> int:
    path = convert(
        args.input,
        args.output,
        model=args.model,
        parser=args.parser,
        chunk_size=args.chunk_size,
        overlap=args.overlap,
        store_original=_str_to_bool(args.store_original),
    )
    if args.json:
        print(json.dumps({"ok": True, "output": str(path)}))
    else:
        print(f"Created {path}")
    return 0


def cmd_inspect(args) -> int:
    doc = VeraDocument.open(args.file)
    try:
        info = doc.inspect()
        if args.json:
            print(json.dumps({"file": args.file, **info}))
            return 0
        print(f"File: {args.file}")
        print(f"Format: {info.get('format_name', 'VERA')} v{info.get('format_version')}")
        print(f"Source: {info.get('source_file_name') or info.get('source')}")
        print(f"Pages: {info.get('pages')}")
        print(f"Chunks: {info.get('chunks')}")
        print(f"Embedding model: {info.get('default_embedding_model')}")
        print(f"Embedding dimensions: {info.get('default_embedding_dimension')}")
        print(f"Parser: {info.get('parser_name')}")
        print(f"Created: {info.get('created_at')}")
    finally:
        doc.close()
    return 0


def cmd_search(args) -> int:
    doc = VeraDocument.open(args.file)
    try:
        results = doc.search(args.query, mode=args.mode, top_k=args.top_k)
        if args.json:
            payload = []
            for result in results:
                entry = result.as_dict()
                if args.figures:
                    entry["figures"] = doc.figures_for(result)  # metadata + captions, no bytes
                payload.append(entry)
            print(json.dumps({"query": args.query, "mode": args.mode, "results": payload}))
            return 0
        for result in results:
            print(f"Score: {result.score:.4f}")
            print(f"Source: {result.source_filename}")
            page = result.page_start if result.page_start == result.page_end else f"{result.page_start}-{result.page_end}"
            print(f"Page: {page}")
            print(f"Heading: {result.heading_path or ''}")
            print()
            print(result.text)
            print("-" * 72)
    finally:
        doc.close()
    return 0


def cmd_validate(args) -> int:
    doc = VeraDocument.open(args.file)
    try:
        report = doc.validate()
    finally:
        doc.close()

    if args.json:
        print(json.dumps({"file": args.file, **report}))
        return 0 if report["ok"] else 1
    print(f"VERA validation: {'PASS' if report['ok'] else 'FAIL'}")
    print(f"File: {args.file}")
    counts = report["counts"]
    print(f"Documents: {counts['documents']}")
    print(f"Pages: {counts['pages']}")
    print(f"Chunks: {counts['chunks']}")
    print(f"Embeddings: {counts['embeddings']}")
    print(f"FTS rows: {counts['fts_rows']}")
    print(f"Original document: {'present' if report['checks']['original_document_present'] else 'missing'}")
    print(f"Issues: {len(report['issues'])}")
    for issue in report["issues"]:
        print(f"- {issue}")
    return 0 if report["ok"] else 1


def cmd_workbench(args) -> int:
    import subprocess

    command = [sys.executable, "-m", "streamlit", "run", "app/vera_workbench.py"]
    raise SystemExit(subprocess.call(command))


def cmd_mcp(args) -> int:
    from .mcp_server import main as mcp_main

    return mcp_main()


def cmd_eval(args) -> int:
    from .evaluate import evaluate

    summary = evaluate(args.file, args.queries, mode=args.mode, top_k=args.top_k)
    all_ok = all(report["hits"] == report["total"] for report in summary["reports"])
    if args.json:
        print(json.dumps(summary))
        return 0 if all_ok else 1
    print(f"File: {summary['file']}")
    print(f"Queries: {summary['queries_file']}")
    for report in summary["reports"]:
        print()
        print(f"Mode: {report['mode']}  (top_k={report['top_k']})")
        for entry in report["queries"]:
            status = f"HIT rank={entry['rank']}" if entry["hit"] else "MISS"
            note = f"  # {entry['note']}" if entry["note"] else ""
            print(f"  [{status:>10}] {entry['query']}{note}")
        print(f"  Hits: {report['hits']}/{report['total']} ({report['hit_rate']:.0%})  MRR: {report['mrr']:.3f}")
    return 0 if all_ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vera", description="Vector-Embedded Retrieval Archive CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    convert_p = sub.add_parser("convert", help="Convert a PDF to a VERA file")
    convert_p.add_argument("input")
    convert_p.add_argument("output")
    convert_p.add_argument("--model", default="hashing")
    convert_p.add_argument("--parser", default="pymupdf")
    convert_p.add_argument("--chunk-size", type=int, default=500)
    convert_p.add_argument("--overlap", type=int, default=75)
    convert_p.add_argument("--store-original", default="true")
    convert_p.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    convert_p.set_defaults(func=cmd_convert)

    inspect_p = sub.add_parser("inspect", help="Inspect a VERA file")
    inspect_p.add_argument("file")
    inspect_p.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    inspect_p.set_defaults(func=cmd_inspect)

    search_p = sub.add_parser("search", help="Search a VERA file")
    search_p.add_argument("file")
    search_p.add_argument("query")
    search_p.add_argument("--mode", choices=["semantic", "keyword", "hybrid"], default="hybrid")
    search_p.add_argument("--top-k", type=int, default=10)
    search_p.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    search_p.add_argument("--figures", action="store_true", help="Include figure metadata/captions in --json output")
    search_p.set_defaults(func=cmd_search)

    validate_p = sub.add_parser("validate", help="Validate a VERA file")
    validate_p.add_argument("file")
    validate_p.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    validate_p.set_defaults(func=cmd_validate)

    workbench_p = sub.add_parser("workbench", help="Launch the optional Streamlit VERA Workbench")
    workbench_p.set_defaults(func=cmd_workbench)

    mcp_p = sub.add_parser("mcp", help="Run the MCP server (stdio) exposing VERA tools to AI agents")
    mcp_p.set_defaults(func=cmd_mcp)

    eval_p = sub.add_parser("eval", help="Evaluate retrieval quality against a query file")
    eval_p.add_argument("file")
    eval_p.add_argument("queries", help="JSON or YAML file with query cases")
    eval_p.add_argument("--mode", choices=["semantic", "keyword", "hybrid", "all"], default="all")
    eval_p.add_argument("--top-k", type=int, default=5)
    eval_p.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    eval_p.set_defaults(func=cmd_eval)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
