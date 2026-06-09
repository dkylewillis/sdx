from __future__ import annotations

import argparse
import sys

from .convert import convert
from .document import SDXDocument


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
    print(f"Created {path}")
    return 0


def cmd_inspect(args) -> int:
    doc = SDXDocument.open(args.file)
    try:
        info = doc.inspect()
        print(f"File: {args.file}")
        print(f"Format: {info.get('format_name', 'SDX')} v{info.get('format_version')}")
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
    doc = SDXDocument.open(args.file)
    try:
        for result in doc.search(args.query, mode=args.mode, top_k=args.top_k):
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sdx", description="Semantic Document eXchange CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    convert_p = sub.add_parser("convert", help="Convert a PDF to an SDX file")
    convert_p.add_argument("input")
    convert_p.add_argument("output")
    convert_p.add_argument("--model", default="hashing")
    convert_p.add_argument("--parser", default="pymupdf")
    convert_p.add_argument("--chunk-size", type=int, default=500)
    convert_p.add_argument("--overlap", type=int, default=75)
    convert_p.add_argument("--store-original", default="true")
    convert_p.set_defaults(func=cmd_convert)

    inspect_p = sub.add_parser("inspect", help="Inspect an SDX file")
    inspect_p.add_argument("file")
    inspect_p.set_defaults(func=cmd_inspect)

    search_p = sub.add_parser("search", help="Search an SDX file")
    search_p.add_argument("file")
    search_p.add_argument("query")
    search_p.add_argument("--mode", choices=["semantic", "keyword", "hybrid"], default="hybrid")
    search_p.add_argument("--top-k", type=int, default=10)
    search_p.set_defaults(func=cmd_search)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
