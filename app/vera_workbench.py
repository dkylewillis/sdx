from __future__ import annotations

import tempfile
from pathlib import Path

import streamlit as st

from vera import VeraDocument, convert


st.set_page_config(page_title="VERA Workbench", layout="wide")
st.title("VERA Workbench")
st.caption("Convert once. Search anywhere.")

if "vera_path" not in st.session_state:
    st.session_state.vera_path = ""

with st.sidebar:
    st.header("1. Open or create VERA")
    uploaded_pdf = st.file_uploader("Convert PDF to VERA", type=["pdf"])
    output_name = st.text_input("Output file name", value="document.vera")
    model = st.text_input("Embedding model", value="hashing")
    chunk_size = st.number_input("Chunk size", min_value=50, max_value=2000, value=500, step=50)
    overlap = st.number_input("Overlap", min_value=0, max_value=500, value=75, step=25)

    if uploaded_pdf and st.button("Convert uploaded PDF", type="primary"):
        temp_dir = Path(tempfile.mkdtemp(prefix="vera-workbench-"))
        pdf_path = temp_dir / uploaded_pdf.name
        vera_path = temp_dir / output_name
        pdf_path.write_bytes(uploaded_pdf.getvalue())
        with st.spinner("Converting PDF to VERA..."):
            convert(str(pdf_path), str(vera_path), model=model, chunk_size=int(chunk_size), overlap=int(overlap))
        st.session_state.vera_path = str(vera_path)
        st.success(f"Created {vera_path}")

    st.divider()
    st.session_state.vera_path = st.text_input("Existing .vera path", value=st.session_state.vera_path)

vera_path = st.session_state.vera_path.strip()
if not vera_path:
    st.info("Upload a PDF or enter a path to an existing `.vera` file to begin.")
    st.stop()

path = Path(vera_path)
if not path.exists():
    st.error(f"File does not exist: {path}")
    st.stop()

try:
    doc = VeraDocument.open(str(path))
except Exception as exc:
    st.error(f"Could not open VERA file: {exc}")
    st.stop()

try:
    info = doc.inspect()
    report = doc.validate()

    left, right = st.columns([1, 2])

    with left:
        st.subheader("File")
        st.write(str(path))
        st.subheader("Metadata")
        st.metric("Pages", info.get("pages"))
        st.metric("Chunks", info.get("chunks"))
        st.metric("Embeddings", info.get("embeddings"))
        st.write("**Format:**", f"{info.get('format_name', 'VERA')} v{info.get('format_version')}")
        st.write("**Source:**", info.get("source_file_name") or info.get("source"))
        st.write("**Model:**", info.get("default_embedding_model"))
        st.write("**Parser:**", info.get("parser_name"))

        st.subheader("Validation")
        if report["ok"]:
            st.success("PASS")
        else:
            st.error("FAIL")
        st.json({"counts": report["counts"], "checks": report["checks"]})
        if report["issues"]:
            st.write("**Issues**")
            for issue in report["issues"]:
                st.warning(issue)

    with right:
        st.subheader("Search")
        query = st.text_input("Query", value="restaurant parking requirements")
        mode = st.selectbox("Mode", ["hybrid", "semantic", "keyword"], index=0)
        top_k = st.slider("Top K", min_value=1, max_value=25, value=5)
        if st.button("Search") and query.strip():
            results = doc.search(query, mode=mode, top_k=top_k)
            if not results:
                st.info("No results")
            for idx, result in enumerate(results, start=1):
                with st.expander(
                    f"#{idx} score={result.score:.4f} page={result.page_start} heading={result.heading_path or ''}",
                    expanded=idx == 1,
                ):
                    st.write(result.text)
                    figures = doc.figures_for(result, include_data=True)
                    if figures:
                        st.write(f"**Figures on pages {result.page_start}-{result.page_end}:**")
                        cols = st.columns(min(len(figures), 3))
                        for fig_idx, figure in enumerate(figures):
                            with cols[fig_idx % len(cols)]:
                                caption = figure.get("caption") or f"p.{figure['page_number']} {figure['filename']}"
                                st.image(figure["data"], caption=caption)
                    st.json(result.as_dict())

        st.subheader("Chunks")
        chunk_rows = doc.conn.execute(
            """
            SELECT chunk_id, page_start, page_end, heading_path, token_count, substr(text, 1, 240) AS preview
            FROM chunks ORDER BY sort_order LIMIT 100
            """
        ).fetchall()
        st.dataframe([dict(row) for row in chunk_rows], use_container_width=True)
finally:
    doc.close()
