"""MCP (Model Context Protocol) server exposing VERA files to AI agents.

Run with:

    vera mcp

or configure in an MCP client (e.g. VS Code .vscode/mcp.json):

    {
      "servers": {
        "vera": {"command": "uv", "args": ["run", "--extra", "mcp", "vera", "mcp"]}
      }
    }

Requires the optional dependency: pip install vera[mcp]
"""

from __future__ import annotations

from typing import Any

from .corpus import VeraCorpus
from .document import VeraDocument


def _open(file: str) -> VeraDocument:
    return VeraDocument.open(file)


def build_server():
    """Create the FastMCP server with VERA tools registered."""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "The MCP server requires the optional 'mcp' dependency: pip install vera[mcp]"
        ) from exc

    server = FastMCP(
        "vera",
        instructions=(
            "Search VERA (Vector-Embedded Retrieval Archive) files. An .vera file is a portable "
            "SQLite container holding a document plus chunks, embeddings, a keyword index, "
            "figures, and citation metadata. Use vera_search to retrieve citation-ready "
            "context (text + page + heading path) from a document. Results include page "
            "numbers and heading paths that should be cited when answering."
        ),
    )

    @server.tool()
    def vera_search(
        file: str,
        query: str,
        mode: str = "hybrid",
        top_k: int = 5,
        include_figures: bool = False,
        include_regions: bool = False,
        context_chunks: int = 0,
    ) -> dict[str, Any]:
        """Search a VERA file and return citation-ready chunks.

        Args:
            file: Path to the .vera file.
            query: Natural-language or keyword query.
            mode: "hybrid" (default, recommended), "semantic", or "keyword".
            top_k: Number of results to return.
            include_figures: Also return figure metadata and captions located on
                each result's pages (no image bytes).
            include_regions: Also return highlight regions for each result —
                the page numbers and bounding boxes ([x0, y0, x1, y1] in page
                points, origin top-left) of the blocks the chunk came from,
                for visual grounding in a PDF viewer.
            context_chunks: Include this many chunks before and after each result.
        """
        doc = _open(file)
        try:
            results = []
            for result in doc.search(query, mode=mode, top_k=top_k, context_chunks=context_chunks):
                entry = result.as_dict()
                if include_figures:
                    entry["figures"] = doc.figures_for(result)
                if include_regions:
                    entry["regions"] = doc.regions_for(result)
                results.append(entry)
            return {"query": query, "mode": mode, "results": results}
        finally:
            doc.close()

    @server.tool()
    def vera_corpus_search(
        directory: str,
        query: str,
        mode: str = "hybrid",
        top_k: int = 5,
        include_regions: bool = False,
        context_chunks: int = 0,
    ) -> dict[str, Any]:
        """Search every .vera file in a directory as one corpus and return the
        fused top results. Each result includes the .vera file it came from
        ("file") plus the usual citation fields (source filename, pages,
        heading path).

        Args:
            directory: Folder containing .vera files.
            query: Natural-language or keyword query.
            mode: "hybrid" (default, recommended), "semantic", or "keyword".
            top_k: Number of fused results to return across all files.
            include_regions: Also return highlight regions (page + bbox) per result.
            context_chunks: Include this many chunks before and after each result.
        """
        corpus = VeraCorpus.open(directory)
        try:
            results = []
            for result in corpus.search(query, mode=mode, top_k=top_k, context_chunks=context_chunks):
                entry = result.as_dict()
                if include_regions:
                    entry["regions"] = corpus.regions_for(result)
                results.append(entry)
            return {"directory": directory, "query": query, "mode": mode, "results": results}
        finally:
            corpus.close()

    @server.tool()
    def vera_inspect(file: str) -> dict[str, Any]:
        """Get metadata for a VERA file: source document, page/chunk counts,
        embedding model, parser, and creation info."""
        doc = _open(file)
        try:
            return doc.inspect()
        finally:
            doc.close()

    @server.tool()
    def vera_validate(file: str) -> dict[str, Any]:
        """Validate a VERA file: schema, row counts, index consistency, and
        original-document presence. Returns ok=true/false plus issues."""
        doc = _open(file)
        try:
            return doc.validate()
        finally:
            doc.close()

    @server.tool()
    def vera_figures(
        file: str,
        page_start: int | None = None,
        page_end: int | None = None,
    ) -> list[dict[str, Any]]:
        """List figures (extracted images) in a VERA file with captions and page
        locations. Optionally filter to a page range. Image bytes are not
        returned; use the asset_id with the VERA Python API to fetch them."""
        doc = _open(file)
        try:
            return doc.figures(page_start=page_start, page_end=page_end)
        finally:
            doc.close()

    @server.tool()
    def vera_get_page(file: str, page_number: int) -> dict[str, Any]:
        """Get the full text of a single page, for reading the context around a
        search hit. Pages are 1-based."""
        doc = _open(file)
        try:
            page = doc.get_page(page_number)
            if page is None:
                return {"error": f"Page {page_number} not found"}
            return page
        finally:
            doc.close()

    @server.tool()
    def vera_get_chunk_regions(file: str, chunk_id: str) -> list[dict[str, Any]]:
        """Get the highlight regions for a chunk: the page numbers and bounding
        boxes ([x0, y0, x1, y1] in page points, origin top-left) of the blocks
        the chunk's text came from, plus page dimensions for scaling. Use this
        to visually ground a citation in the source PDF."""
        doc = _open(file)
        try:
            return doc.get_chunk_regions(chunk_id)
        finally:
            doc.close()

    return server


def main() -> int:
    """Entry point for `vera mcp`: run the server over stdio."""
    build_server().run()
    return 0
