import sqlite3

from vera.schema import create_schema, REQUIRED_METADATA_KEYS


def test_create_schema_creates_required_tables_and_fts(tmp_path):
    path = tmp_path / "empty.vera"
    conn = sqlite3.connect(path)
    create_schema(conn)

    names = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','virtual table')"
        )
    }

    assert {
        "vera_metadata",
        "documents",
        "pages",
        "blocks",
        "chunks",
        "chunk_blocks",
        "embeddings",
        "assets",
        "chunks_fts",
    }.issubset(names)
    assert "format_version" in REQUIRED_METADATA_KEYS


def test_embedding_blob_round_trip_float32():
    from vera.embeddings import deserialize_vector, serialize_vector

    blob = serialize_vector([0.25, -0.5, 1.0])
    assert deserialize_vector(blob).tolist() == [0.25, -0.5, 1.0]
