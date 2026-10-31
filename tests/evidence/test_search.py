"""FTS population/integrity and hybrid lexical+semantic search tests."""

from __future__ import annotations

import sqlite3
from contextlib import closing

from conftest import build_markdown, build_pdf, write_manifest

from tracecite.evidence import schema
from tracecite.evidence import sync as sync_module
from tracecite.evidence.commands import _fts_rows, active_embedding_model, hybrid_search


def _sync_corpus(corpus_dir, manifest_path, database_path, embedder):
    build_pdf(
        corpus_dir / "doc.pdf",
        [
            [
                "Retirement",
                "Coal plant retirement dates were pushed later in this planning cycle report.",
            ],
            [
                "Storage",
                "Battery storage capacity grew substantially according to this synthetic report.",
            ],
        ],
    )
    write_manifest(manifest_path, {"doc.pdf": "doc.pdf"})
    return sync_module.sync(corpus_dir, manifest_path, database_path, embedder=embedder)


def _sync_mixed_type_corpus(corpus_dir, manifest_path, database_path, embedder):
    build_pdf(
        corpus_dir / "doc.pdf",
        [
            [
                "Retirement",
                "Coal plant retirement dates were pushed later in this planning cycle report.",
            ]
        ],
    )
    build_markdown(
        corpus_dir / "doc.md",
        "# Retirement\n\nCoal plant retirement dates were pushed later in this planning cycle note.\n",
    )
    write_manifest(manifest_path, {"doc.pdf": "doc.pdf", "doc.md": "doc.md"})
    return sync_module.sync(corpus_dir, manifest_path, database_path, embedder=embedder)


def test_search_source_type_filter_restricts_lexical_and_vector_results(
    corpus_dir, manifest_path, database_path, make_embedder
):
    _sync_mixed_type_corpus(corpus_dir, manifest_path, database_path, make_embedder())
    with closing(schema.connect(database_path)) as conn:
        unfiltered = hybrid_search(
            conn, "coal plant retirement", 5, 50, 50, make_embedder()
        )
        assert {result["source_type"] for result in unfiltered} == {"pdf", "markdown"}

        pdf_only = hybrid_search(
            conn,
            "coal plant retirement",
            5,
            50,
            50,
            make_embedder(),
            source_types=["pdf"],
        )
        assert pdf_only
        assert {result["source_type"] for result in pdf_only} == {"pdf"}

        markdown_only = hybrid_search(
            conn,
            "coal plant retirement",
            5,
            50,
            50,
            make_embedder(),
            source_types=["markdown"],
        )
        assert markdown_only
        assert {result["source_type"] for result in markdown_only} == {"markdown"}


def test_fts_initial_population_and_integrity(
    corpus_dir, manifest_path, database_path, make_embedder
):
    _sync_corpus(corpus_dir, manifest_path, database_path, make_embedder())
    with closing(schema.connect(database_path)) as conn:
        chunk_count = conn.execute("SELECT count(*) FROM chunks").fetchone()[0]
        fts_count = conn.execute("SELECT count(*) FROM chunks_fts").fetchone()[0]
        assert chunk_count == fts_count > 0
        assert sync_module.integrity_check(conn) == []


def test_exact_lexical_search_finds_specific_terms(
    corpus_dir, manifest_path, database_path, make_embedder
):
    _sync_corpus(corpus_dir, manifest_path, database_path, make_embedder())
    with closing(schema.connect(database_path)) as conn:
        rows = conn.execute(
            """
            SELECT chunks.chunk_id FROM chunks_fts
            JOIN chunks ON chunks.rowid = chunks_fts.rowid
            WHERE chunks_fts MATCH 'retirement'
            """
        ).fetchall()
        assert len(rows) == 1


def test_search_preserves_raw_fts_phrase_and_prefix_expressions(
    corpus_dir, manifest_path, database_path, make_embedder
):
    _sync_corpus(corpus_dir, manifest_path, database_path, make_embedder())
    with closing(schema.connect(database_path)) as conn:
        phrase_results = hybrid_search(conn, '"coal plant"', 5, 50, 50, make_embedder())
        prefix_results = hybrid_search(conn, "retire*", 5, 50, 50, make_embedder())
        assert any("Retirement" in result["heading_path"] for result in phrase_results)
        assert any("Retirement" in result["heading_path"] for result in prefix_results)


def test_search_percentage_text_falls_back_without_changing_vector_query(
    corpus_dir, manifest_path, database_path, make_embedder, capsys
):
    embedder = make_embedder()
    _sync_corpus(corpus_dir, manifest_path, database_path, embedder)
    query = "10%, 50%, and 90%"
    with closing(schema.connect(database_path)) as conn:
        results = hybrid_search(conn, query, 5, 50, 50, embedder)
    assert results
    assert "original query" in capsys.readouterr().err


def test_fts_fallback_does_not_swallow_unrelated_sqlite_errors():
    class BrokenConnection:
        def execute(self, statement, parameters):
            raise sqlite3.OperationalError("no such table: chunks_fts")

    try:
        _fts_rows(BrokenConnection(), "query", 50)
    except sqlite3.OperationalError as exc:
        assert str(exc) == "no such table: chunks_fts"
    else:
        raise AssertionError("unrelated SQLite error was swallowed")


def test_semantic_search_finds_paraphrase(
    corpus_dir, manifest_path, database_path, make_embedder
):
    embedder = make_embedder()
    _sync_corpus(corpus_dir, manifest_path, database_path, embedder)
    with closing(schema.connect(database_path)) as conn:
        results = hybrid_search(
            conn, "when will coal power stations shut down", 5, 50, 50, embedder
        )
        assert results
        assert any("Retirement" in r["heading_path"] for r in results)


def test_hybrid_rank_fusion_combines_lexical_and_vector_provenance(
    corpus_dir, manifest_path, database_path, make_embedder
):
    embedder = make_embedder()
    _sync_corpus(corpus_dir, manifest_path, database_path, embedder)
    with closing(schema.connect(database_path)) as conn:
        results = hybrid_search(
            conn, "coal plant retirement dates", 5, 50, 50, embedder
        )
        assert results
        top = results[0]
        assert "lexical" in top["provenance"] or "vector" in top["provenance"]
        assert top["pdf_link"].endswith("#page=1")


def test_search_respects_configurable_limits(
    corpus_dir, manifest_path, database_path, make_embedder
):
    embedder = make_embedder()
    _sync_corpus(corpus_dir, manifest_path, database_path, embedder)
    with closing(schema.connect(database_path)) as conn:
        results = hybrid_search(conn, "report", 1, 50, 50, embedder)
        assert len(results) <= 1


def test_search_contract_for_pdf_result_omits_internal_keys_and_exposes_page_range(
    corpus_dir, manifest_path, database_path, make_embedder
):
    embedder = make_embedder()
    _sync_corpus(corpus_dir, manifest_path, database_path, embedder)
    with closing(schema.connect(database_path)) as conn:
        results = hybrid_search(conn, "retirement dates", 1, 50, 50, embedder)
        assert results
        result = results[0]
        assert "chunk_id" not in result
        assert "source_pk" not in result
        assert result["source_path"] == "doc.pdf"
        assert result["page_range"] == {"start": 1, "end": 1}
        assert result["page_offsets"]["start"] is not None
        assert result["page_offsets"]["end"] is not None
        assert result["pdf_link"] == "doc.pdf#page=1"


def test_search_contract_for_markdown_result_exposes_line_locator(
    corpus_dir, manifest_path, database_path, make_embedder
):
    build_markdown(
        corpus_dir / "note.md",
        "# Heading\n\nThis markdown passage mentions hydrogen storage and line locators.\n",
    )
    write_manifest(manifest_path, {"note.md": "note.md"})
    embedder = make_embedder()
    sync_module.sync(corpus_dir, manifest_path, database_path, embedder=embedder)
    with closing(schema.connect(database_path)) as conn:
        results = hybrid_search(conn, "hydrogen storage", 1, 50, 50, embedder)
        assert results
        result = results[0]
        assert "chunk_id" not in result
        assert result["source_path"] == "note.md"
        assert result["line_range"]["start"] is not None
        assert result["line_range"]["end"] is not None
        assert "pdf_link" not in result


def test_search_uses_atomically_activated_embedding_model_ids(
    corpus_dir, manifest_path, database_path, make_embedder, monkeypatch
):
    embedder = make_embedder()
    _sync_corpus(corpus_dir, manifest_path, database_path, embedder)
    options = sync_module.SyncOptions(embedding_revision="activated-revision")
    sync_module.sync(
        corpus_dir,
        manifest_path,
        database_path,
        options=options,
        embedder=make_embedder(),
    )

    with closing(schema.connect(database_path)) as conn:
        config = schema.load_config(conn)
        assert config.embedding_revision == "activated-revision"
        new_ids = [
            row["embedding_id"]
            for row in conn.execute(
                "SELECT embedding_id FROM embeddings WHERE model_id = ? ORDER BY embedding_id",
                (options.model_id,),
            ).fetchall()
        ]
        old_ids = [
            row["embedding_id"]
            for row in conn.execute(
                "SELECT embedding_id FROM embeddings WHERE model_id = ? ORDER BY embedding_id",
                (schema.embedding_model_id(),),
            ).fetchall()
        ]
        assert new_ids and old_ids and set(new_ids).isdisjoint(old_ids)
        captured = {}

        class CapturingBackend:
            def search(self, conn, query_vector, top_k, allowed_embedding_ids=None):
                captured["allowed"] = list(allowed_embedding_ids or [])
                return []

        monkeypatch.setattr(
            sync_module.vector_backend, "SqliteVecBackend", CapturingBackend
        )
        hybrid_search(conn, "retirement dates", 1, 50, 50, embedder)
        assert captured["allowed"] == new_ids


def test_search_constructs_active_model_and_returns_results_after_cached_reactivation(
    corpus_dir, manifest_path, database_path, make_embedder, monkeypatch, tmp_path
):
    _sync_corpus(corpus_dir, manifest_path, database_path, make_embedder())
    b_options = sync_module.SyncOptions(embedding_revision="revision-b")
    sync_module.sync(
        corpus_dir,
        manifest_path,
        database_path,
        options=b_options,
        embedder=make_embedder(),
    )
    sync_module.sync(corpus_dir, manifest_path, database_path, embedder=make_embedder())

    constructed = []

    class FakeEmbeddingModel:
        def __init__(self, model, revision, cache_dir):
            constructed.append((model, revision, cache_dir))
            self.inner = make_embedder()

        def embed(self, texts):
            return self.inner.embed(texts)

    monkeypatch.setattr(sync_module, "EmbeddingModel", FakeEmbeddingModel)
    with closing(schema.connect(database_path)) as conn:
        results = hybrid_search(
            conn,
            "coal plant retirement dates",
            3,
            50,
            50,
            active_embedding_model(conn, tmp_path / "cache"),
        )
        assert results
        assert any("Retirement" in result["heading_path"] for result in results)
        assert constructed == [
            (schema.EMBEDDING_MODEL, schema.EMBEDDING_REVISION, tmp_path / "cache")
        ]
