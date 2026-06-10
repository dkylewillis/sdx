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
    ) -> dict[str, Any]:
        """Search a VERA file and return citation-ready chunks.

        Args:
            file: Path to the .vera file.
            query: Natural-language or keyword query.
            mode: "hybrid" (default, recommended), "semantic", or "keyword".
            top_k: Number of results to return.
            include_figures: Also return figure metadata and captions located on
                each result's pages (no image bytes).
        """
        doc = _open(file)
        try:
            results = []
            for result in doc.search(query, mode=mode, top_k=top_k):
                entry = result.as_dict()
                if include_figures:
                    entry["figures"] = doc.figures_for(result)
                results.append(entry)
            return {"query": query, "mode": mode, "results": results}
        finally:
            doc.close()

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
            row = doc.conn.execute(
                "SELECT page_number, width, height, text FROM pages WHERE page_number = ?",
                (page_number,),
            ).fetchone()
            if row is None:
                return {"error": f"Page {page_number} not found"}
            return dict(row)
        finally:
            doc.close()

    return server


def main() -> int:
    """Entry point for `vera mcp`: run the server over stdio."""
    build_server().run()
    return 0
