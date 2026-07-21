"""Incremental synchronisation lifecycle and invalidation-rule tests
(plan 0006's required-test list, task 0089's implementation)."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from tracecite.evidence import schema, sync as sync_module
from tracecite.evidence.sync import SyncError, SyncOptions

from conftest import build_markdown, build_pdf, build_pdf_with_image_only_page, write_manifest


def test_production_embedding_has_no_test_fake_environment_branch():
    sync_source = Path(sync_module.__file__).read_text(encoding="utf-8")
    assert "TRACECITE_TEST_FAKE_EMBEDDER" not in sync_source


def _touch_future_mtime(path: Path) -> None:
    """Bump mtime without changing bytes, simulating an mtime-only touch."""

    stat = path.stat()
    new_time = stat.st_mtime + 5
    import os

    os.utime(path, (new_time, new_time))


@pytest.fixture
def one_pdf_corpus(corpus_dir, manifest_path):
    pdf_path = build_pdf(
        corpus_dir / "doc.pdf",
        [
            ["Introduction", "This is the first paragraph of the introduction explaining the report purpose."],
            ["Methods", "This section describes the methods used in this synthetic report for testing."],
        ],
    )
    write_manifest(manifest_path, {"doc.pdf": "doc.pdf"})
    return pdf_path


def test_first_time_indexing(one_pdf_corpus, manifest_path, corpus_dir, database_path, make_embedder):
    embedder = make_embedder()
    report = sync_module.sync(corpus_dir, manifest_path, database_path, embedder=embedder)
    assert report.status == "ok"
    assert report.sources_added == ["doc.pdf"]
    assert report.chunks_added == 2
    assert report.embeddings_generated == 2

    conn = schema.connect(database_path)
    try:
        assert conn.execute("SELECT count(*) FROM sources").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM pages").fetchone()[0] == 2
        assert conn.execute("SELECT count(*) FROM chunks").fetchone()[0] == 2
        assert conn.execute("SELECT count(*) FROM embeddings").fetchone()[0] == 2
        assert sync_module.integrity_check(conn) == []
    finally:
        conn.close()


def test_unchanged_file_zero_writes_and_embeddings(
    one_pdf_corpus, manifest_path, corpus_dir, database_path, make_embedder
):
    embedder = make_embedder()
    sync_module.sync(corpus_dir, manifest_path, database_path, embedder=embedder)
    calls_before = len(embedder.calls)

    conn = schema.connect(database_path)
    before_updated = conn.execute("SELECT updated_at_utc FROM kb_config").fetchone()[0]
    conn.close()

    report = sync_module.sync(corpus_dir, manifest_path, database_path, embedder=embedder)
    assert report.sources_unchanged == ["doc.pdf"]
    assert not report.wrote_anything
    assert len(embedder.calls) == calls_before  # zero new embedding calls

    conn = schema.connect(database_path)
    after_updated = conn.execute("SELECT updated_at_utc FROM kb_config").fetchone()[0]
    conn.close()
    assert before_updated == after_updated  # config wasn't touched (nothing committed)


def test_mtime_only_touch_rechecks_hash_but_does_not_reparse(
    one_pdf_corpus, manifest_path, corpus_dir, database_path, make_embedder
):
    embedder = make_embedder()
    sync_module.sync(corpus_dir, manifest_path, database_path, embedder=embedder)
    calls_before = len(embedder.calls)

    _touch_future_mtime(one_pdf_corpus)
    report = sync_module.sync(corpus_dir, manifest_path, database_path, embedder=embedder)

    assert report.sources_reparsed == []
    assert report.sources_added == []
    assert len(embedder.calls) == calls_before


def test_parser_metadata_change_reparses_without_byte_change(
    one_pdf_corpus, manifest_path, corpus_dir, database_path, make_embedder
):
    embedder = make_embedder()
    sync_module.sync(corpus_dir, manifest_path, database_path, embedder=embedder)

    options = SyncOptions(parser_version_pdf="2")
    report = sync_module.sync(
        corpus_dir, manifest_path, database_path, options=options, embedder=embedder
    )
    assert report.sources_reparsed == ["doc.pdf"]

    conn = schema.connect(database_path)
    row = conn.execute("SELECT parser_version FROM sources WHERE path = 'doc.pdf'").fetchone()
    conn.close()
    assert row["parser_version"] == "2"


def test_chunker_only_change_rechunks_without_reopening_pdf(
    one_pdf_corpus, manifest_path, corpus_dir, database_path, make_embedder, monkeypatch
):
    embedder = make_embedder()
    sync_module.sync(corpus_dir, manifest_path, database_path, embedder=embedder)

    from tracecite.evidence.parsers import pdf as pdf_parser

    def _boom(*args, **kwargs):
        raise AssertionError("PDF parser must not be reopened for a chunker-only change")

    monkeypatch.setattr(pdf_parser, "parse", _boom)

    options = SyncOptions(max_chunk_chars=40)  # forces different grouping
    report = sync_module.sync(
        corpus_dir, manifest_path, database_path, options=options, embedder=embedder
    )
    assert report.sources_rechunked == ["doc.pdf"]
    assert report.sources_reparsed == []


def test_page_offset_shift_causes_zero_embedding_calls(
    corpus_dir, manifest_path, database_path, make_embedder
):
    # Two headings (=> two separate chunks) on one page. Editing only the
    # first heading's paragraph shifts the second chunk's page-local byte
    # offsets (its preceding text got longer/shorter) without changing its
    # own normalised semantic content, so it must not be re-embedded.
    build_pdf(
        corpus_dir / "doc.pdf",
        [
            [
                "Alpha",
                "Short alpha text.",
                "Beta",
                "This beta paragraph body must stay byte-for-byte identical across both syncs.",
            ]
        ],
    )
    write_manifest(manifest_path, {"doc.pdf": "doc.pdf"})
    embedder = make_embedder()
    sync_module.sync(corpus_dir, manifest_path, database_path, embedder=embedder)

    conn = schema.connect(database_path)
    before = {
        row["logical_key"]: (row["chunk_id"], row["page_start_offset"], row["semantic_input_hash"])
        for row in conn.execute("SELECT chunks.* FROM chunks JOIN sources USING (source_pk) WHERE sources.path='doc.pdf'").fetchall()
    }
    conn.close()

    # Lengthen Alpha's paragraph considerably; Beta's own text is untouched.
    build_pdf(
        corpus_dir / "doc.pdf",
        [
            [
                "Alpha",
                "This much longer alpha paragraph text pushes every following byte offset forward substantially.",
                "Beta",
                "This beta paragraph body must stay byte-for-byte identical across both syncs.",
            ]
        ],
    )
    calls_before = len(embedder.calls)
    report = sync_module.sync(corpus_dir, manifest_path, database_path, embedder=embedder)
    assert report.sources_reparsed == ["doc.pdf"]
    # Exactly one chunk (Alpha's) changed semantically and was re-embedded.
    assert len(embedder.calls) == calls_before + 1

    conn = schema.connect(database_path)
    after = {
        row["logical_key"]: (row["chunk_id"], row["page_start_offset"], row["semantic_input_hash"])
        for row in conn.execute("SELECT chunks.* FROM chunks JOIN sources USING (source_pk) WHERE sources.path='doc.pdf'").fetchall()
    }
    conn.close()

    # Find Beta's logical key by matching its unchanged semantic hash.
    beta_logical_key = next(
        key for key, (cid, offset, sem_hash) in before.items()
        if key in after and after[key][2] == sem_hash
    )
    assert before[beta_logical_key][2] == after[beta_logical_key][2]  # same semantic hash
    assert before[beta_logical_key][1] != after[beta_logical_key][1]  # offset shifted
    assert before[beta_logical_key][0] == after[beta_logical_key][0]  # same chunk identity preserved


def test_unambiguous_rename_zero_parse_and_embed_calls(
    one_pdf_corpus, manifest_path, corpus_dir, database_path, make_embedder
):
    embedder = make_embedder()
    sync_module.sync(corpus_dir, manifest_path, database_path, embedder=embedder)
    calls_before = len(embedder.calls)

    renamed_path = corpus_dir / "doc-renamed.pdf"
    one_pdf_corpus.rename(renamed_path)
    write_manifest(manifest_path, {"doc-renamed.pdf": "doc-renamed.pdf"})

    from tracecite.evidence.parsers import pdf as pdf_parser
    import tracecite.evidence.sync as sync_mod

    original_parse = pdf_parser.parse
    parse_calls = []

    def _track(*args, **kwargs):
        parse_calls.append(args)
        return original_parse(*args, **kwargs)

    sync_mod.pdf_parser.parse = _track
    try:
        report = sync_module.sync(corpus_dir, manifest_path, database_path, embedder=embedder)
    finally:
        sync_mod.pdf_parser.parse = original_parse

    assert report.sources_renamed == [("doc.pdf", "doc-renamed.pdf")]
    assert parse_calls == []
    assert len(embedder.calls) == calls_before

    conn = schema.connect(database_path)
    row = conn.execute("SELECT * FROM sources WHERE path = 'doc-renamed.pdf'").fetchone()
    assert row is not None
    assert row["path"] == "doc-renamed.pdf"
    chunk_count = conn.execute(
        "SELECT count(*) FROM chunks JOIN sources USING (source_pk) WHERE sources.path = 'doc-renamed.pdf'"
    ).fetchone()[0]
    assert chunk_count == 2
    conn.close()


def test_rename_target_mutation_before_transaction_aborts_without_writes(
    one_pdf_corpus, manifest_path, corpus_dir, database_path, make_embedder
):
    embedder = make_embedder()
    sync_module.sync(corpus_dir, manifest_path, database_path, embedder=embedder)
    renamed_path = corpus_dir / "doc-renamed.pdf"
    one_pdf_corpus.rename(renamed_path)
    write_manifest(manifest_path, {"doc-renamed.pdf": "doc-renamed.pdf"})
    conn = schema.connect(database_path)
    try:
        before_sources = [dict(row) for row in conn.execute("SELECT * FROM sources ORDER BY source_pk").fetchall()]
        before_chunks = [dict(row) for row in conn.execute("SELECT * FROM chunks ORDER BY chunk_id").fetchall()]
        before_wal = (database_path.with_name(database_path.name + "-wal").exists(), database_path.with_name(database_path.name + "-shm").exists())
    finally:
        conn.close()

    def mutate_at_begin(event):
        if event == "begin-immediate":
            build_pdf(renamed_path, [["Changed", "Rename target changed after detection before transaction."]])

    sync_module.ASSET_EVENT_HOOK = mutate_at_begin
    try:
        report = sync_module.sync(corpus_dir, manifest_path, database_path, embedder=embedder)
    finally:
        sync_module.ASSET_EVENT_HOOK = None

    assert report.status == "aborted-source-changed"
    conn = schema.connect(database_path)
    try:
        assert not conn.in_transaction
        assert [dict(row) for row in conn.execute("SELECT * FROM sources ORDER BY source_pk").fetchall()] == before_sources
        assert [dict(row) for row in conn.execute("SELECT * FROM chunks ORDER BY chunk_id").fetchall()] == before_chunks
        after_wal = (database_path.with_name(database_path.name + "-wal").exists(), database_path.with_name(database_path.name + "-shm").exists())
        assert after_wal == before_wal
    finally:
        conn.close()

    repair = sync_module.sync(corpus_dir, manifest_path, database_path, embedder=embedder)
    assert repair.sources_added == ["doc-renamed.pdf"]
    assert repair.indexed_unselected_paths == ["doc.pdf"]


def test_rename_target_mutation_after_final_hash_capture_aborts_without_side_effects(
    one_pdf_corpus, manifest_path, corpus_dir, database_path, make_embedder
):
    embedder = make_embedder()
    sync_module.sync(corpus_dir, manifest_path, database_path, embedder=embedder)
    renamed_path = corpus_dir / "doc-renamed.pdf"
    one_pdf_corpus.rename(renamed_path)
    write_manifest(manifest_path, {"doc-renamed.pdf": "doc-renamed.pdf"})
    conn = schema.connect(database_path)
    try:
        before_sources = [dict(row) for row in conn.execute("SELECT * FROM sources ORDER BY source_pk").fetchall()]
        before_chunks = [dict(row) for row in conn.execute("SELECT * FROM chunks ORDER BY chunk_id").fetchall()]
        before_config = dict(conn.execute("SELECT * FROM kb_config").fetchone())
        before_sidecars = (database_path.with_name(database_path.name + "-wal").exists(), database_path.with_name(database_path.name + "-shm").exists())
    finally:
        conn.close()

    def mutate_after_final_capture(event):
        if event == "rename-final-state-captured":
            build_pdf(renamed_path, [["Changed", "Rename target changed after final hash capture."]])

    sync_module.ASSET_EVENT_HOOK = mutate_after_final_capture
    try:
        report = sync_module.sync(corpus_dir, manifest_path, database_path, embedder=embedder)
    finally:
        sync_module.ASSET_EVENT_HOOK = None

    assert report.status == "aborted-source-changed"
    conn = schema.connect(database_path)
    try:
        assert not conn.in_transaction
        assert [dict(row) for row in conn.execute("SELECT * FROM sources ORDER BY source_pk").fetchall()] == before_sources
        assert [dict(row) for row in conn.execute("SELECT * FROM chunks ORDER BY chunk_id").fetchall()] == before_chunks
        assert dict(conn.execute("SELECT * FROM kb_config").fetchone()) == before_config
        assert (database_path.with_name(database_path.name + "-wal").exists(), database_path.with_name(database_path.name + "-shm").exists()) == before_sidecars
    finally:
        conn.close()

    repair = sync_module.sync(corpus_dir, manifest_path, database_path, embedder=embedder)
    assert repair.sources_added == ["doc-renamed.pdf"]
    assert repair.indexed_unselected_paths == ["doc.pdf"]


def test_ambiguous_same_hash_paths_not_misclassified_as_rename(
    corpus_dir, manifest_path, database_path, make_embedder
):
    # Two byte-identical files under two different IDs; deleting both old IDs
    # and adding two new IDs with the same shared hash must not be merged.
    import shutil

    shared_pages = [["Notice", "This boilerplate notice paragraph is identical across both documents today."]]
    path_a = build_pdf(corpus_dir / "a.pdf", shared_pages)
    path_b = corpus_dir / "b.pdf"
    shutil.copyfile(path_a, path_b)  # byte-identical, not just visually identical
    assert sync_module.hash_file(path_a) == sync_module.hash_file(path_b)

    write_manifest(manifest_path, {"doc.pdf": "a.pdf", "b.pdf": "b.pdf"})
    embedder = make_embedder()
    sync_module.sync(corpus_dir, manifest_path, database_path, embedder=embedder)

    # Now both are "renamed": doc-a -> doc-c (new path), doc-b -> doc-d
    path_a.rename(corpus_dir / "c.pdf")
    path_b.rename(corpus_dir / "d.pdf")
    write_manifest(manifest_path, {"c.pdf": "c.pdf", "d.pdf": "d.pdf"})

    report = sync_module.sync(corpus_dir, manifest_path, database_path, embedder=embedder)
    # Ambiguous: two old ids share the hash with two new ids -> no rename inferred
    assert report.sources_renamed == []
    assert set(report.indexed_unselected_paths) == {"a.pdf", "b.pdf"}
    assert set(report.sources_added) == {"c.pdf", "d.pdf"}

    conn = schema.connect(database_path)
    assert conn.execute("SELECT count(*) FROM sources").fetchone()[0] == 4
    ids = {row["path"] for row in conn.execute("SELECT path FROM sources").fetchall()}
    assert ids == {"a.pdf", "b.pdf", "c.pdf", "d.pdf"}
    conn.close()


def test_changed_content_path_move_retains_old_row_until_prune(corpus_dir, manifest_path, database_path, make_embedder):
    old_path = build_pdf(corpus_dir / "old.pdf", [["Old", "Original content remains indexed until explicit prune."]])
    write_manifest(manifest_path, {"old.pdf": "old.pdf"})
    embedder = make_embedder()
    sync_module.sync(corpus_dir, manifest_path, database_path, embedder=embedder)
    conn = schema.connect(database_path)
    try:
        old_source_pk = conn.execute("SELECT source_pk FROM sources WHERE path = 'old.pdf'").fetchone()["source_pk"]
        old_chunk_ids = {row["chunk_id"] for row in conn.execute("SELECT chunk_id FROM chunks WHERE source_pk = ?", (old_source_pk,)).fetchall()}
        old_embedding_count = conn.execute("SELECT count(*) FROM embeddings").fetchone()[0]
    finally:
        conn.close()

    old_path.unlink()
    build_pdf(corpus_dir / "new.pdf", [["New", "Changed content at moved path must be a new retained source."]])
    write_manifest(manifest_path, {"new.pdf": "new.pdf"})
    report = sync_module.sync(corpus_dir, manifest_path, database_path, embedder=embedder)
    assert report.sources_added == ["new.pdf"]
    assert report.indexed_unselected_paths == ["old.pdf"]
    assert report.sources_renamed == []

    conn = schema.connect(database_path)
    try:
        assert {row["path"] for row in conn.execute("SELECT path FROM sources").fetchall()} == {"old.pdf", "new.pdf"}
        assert {row["chunk_id"] for row in conn.execute("SELECT chunk_id FROM chunks WHERE source_pk = ?", (old_source_pk,)).fetchall()} == old_chunk_ids
        assert conn.execute("SELECT count(*) FROM embeddings").fetchone()[0] == old_embedding_count + 1
        plan = sync_module.plan_prune(conn, selected_paths=["new.pdf"])
        assert plan.paths == ("old.pdf",)
        assert sync_module.apply_prune(conn, database_path, plan) == []
        assert {row["path"] for row in conn.execute("SELECT path FROM sources").fetchall()} == {"new.pdf"}
    finally:
        conn.close()


def test_content_movement_preserves_embeddings(corpus_dir, manifest_path, database_path, make_embedder):
    pdf_path = build_pdf(
        corpus_dir / "doc.pdf",
        [
            ["Alpha", "This alpha section paragraph contains distinctive wording for identification purposes."],
            ["Beta", "This beta section paragraph is also distinctive and easy to identify in tests."],
        ],
    )
    write_manifest(manifest_path, {"doc.pdf": "doc.pdf"})
    embedder = make_embedder()
    sync_module.sync(corpus_dir, manifest_path, database_path, embedder=embedder)

    conn = schema.connect(database_path)
    before = {
        row["logical_key"]: (row["chunk_id"], row["semantic_input_hash"])
        for row in conn.execute("SELECT * FROM chunks").fetchall()
    }
    embedding_count_before = conn.execute("SELECT count(*) FROM embeddings").fetchone()[0]
    conn.close()

    # Swap page order: Beta first, then Alpha -- same content, moved.
    build_pdf(
        corpus_dir / "doc.pdf",
        [
            ["Beta", "This beta section paragraph is also distinctive and easy to identify in tests."],
            ["Alpha", "This alpha section paragraph contains distinctive wording for identification purposes."],
        ],
    )
    calls_before = len(embedder.calls)
    report = sync_module.sync(corpus_dir, manifest_path, database_path, embedder=embedder)
    assert report.sources_reparsed == ["doc.pdf"]
    assert len(embedder.calls) == calls_before  # both semantic hashes reused

    conn = schema.connect(database_path)
    embedding_count_after = conn.execute("SELECT count(*) FROM embeddings").fetchone()[0]
    assert embedding_count_after == embedding_count_before
    after_hashes = {row["semantic_input_hash"] for row in conn.execute("SELECT * FROM chunks").fetchall()}
    before_hashes = {h for _, h in before.values()}
    assert after_hashes == before_hashes
    conn.close()


def test_repeated_identical_text_keeps_distinct_chunk_identities(
    corpus_dir, manifest_path, database_path, make_embedder
):
    duplicate_paragraph = "This exact disclaimer text is repeated verbatim across two pages for this test."
    build_pdf(
        corpus_dir / "doc.pdf",
        [
            ["Front matter", duplicate_paragraph],
            ["Back matter", duplicate_paragraph],
        ],
    )
    write_manifest(manifest_path, {"doc.pdf": "doc.pdf"})
    embedder = make_embedder()
    sync_module.sync(corpus_dir, manifest_path, database_path, embedder=embedder)

    conn = schema.connect(database_path)
    chunk_ids = {row["chunk_id"] for row in conn.execute("SELECT chunk_id FROM chunks").fetchall()}
    assert len(chunk_ids) == 2  # distinct identities despite identical semantic hash
    embedding_count = conn.execute("SELECT count(*) FROM embeddings").fetchone()[0]
    conn.close()
    assert embedding_count < 2 * 2  # the two duplicate-content chunks share one embedding


def test_single_chunk_edit_reembeds_only_that_chunk(
    corpus_dir, manifest_path, database_path, make_embedder
):
    build_pdf(
        corpus_dir / "doc.pdf",
        [
            ["Alpha", "This alpha paragraph has completely unique wording for the first page today."],
            ["Beta", "This beta paragraph has completely unique wording for the second page today."],
        ],
    )
    write_manifest(manifest_path, {"doc.pdf": "doc.pdf"})
    embedder = make_embedder()
    sync_module.sync(corpus_dir, manifest_path, database_path, embedder=embedder)

    build_pdf(
        corpus_dir / "doc.pdf",
        [
            ["Alpha", "This alpha paragraph has been edited with new distinctive wording for this test."],
            ["Beta", "This beta paragraph has completely unique wording for the second page today."],
        ],
    )
    calls_before = len(embedder.calls)
    report = sync_module.sync(corpus_dir, manifest_path, database_path, embedder=embedder)
    assert report.sources_reparsed == ["doc.pdf"]
    assert len(embedder.calls) == calls_before + 1
    assert len(embedder.calls[-1]) == 1  # exactly one chunk re-embedded


def test_changed_content_retains_orphan_embeddings_until_prune(
    corpus_dir, manifest_path, database_path, make_embedder
):
    build_pdf(
        corpus_dir / "doc.pdf",
        [["Alpha", "The original semantic content has one unique embedding row."]],
    )
    write_manifest(manifest_path, {"doc.pdf": "doc.pdf"})
    embedder = make_embedder()
    sync_module.sync(corpus_dir, manifest_path, database_path, embedder=embedder)

    build_pdf(
        corpus_dir / "doc.pdf",
        [["Alpha", "The edited semantic content must create a second embedding row."]],
    )
    sync_module.sync(corpus_dir, manifest_path, database_path, embedder=embedder)

    conn = schema.connect(database_path)
    try:
        assert conn.execute("SELECT count(*) FROM embeddings").fetchone()[0] == 2
        assert conn.execute("SELECT count(*) FROM chunk_embeddings").fetchone()[0] == 1
        plan = sync_module.plan_prune(conn, selected_paths=[])
        sync_module.apply_prune(conn, database_path, plan)
        assert conn.execute("SELECT count(*) FROM embeddings").fetchone()[0] == 0
    finally:
        conn.close()


def test_delete_removes_chunks_fts_vectors_and_assets(
    one_pdf_corpus, manifest_path, corpus_dir, database_path, make_embedder
):
    embedder = make_embedder()
    sync_module.sync(corpus_dir, manifest_path, database_path, embedder=embedder)

    conn = schema.connect(database_path)
    asset_paths = [row["asset_path"] for row in conn.execute("SELECT asset_path FROM assets").fetchall()]
    assert asset_paths
    for path in asset_paths:
        assert schema.resolve_asset_path(database_path, path).is_file()
    conn.close()

    one_pdf_corpus.unlink()
    write_manifest(manifest_path, {})
    report = sync_module.sync(corpus_dir, manifest_path, database_path, embedder=embedder)
    assert report.indexed_unselected_paths == ["doc.pdf"]

    conn = schema.connect(database_path)
    assert conn.execute("SELECT count(*) FROM sources").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM chunks").fetchone()[0] == 2
    assert conn.execute("SELECT count(*) FROM chunks_fts").fetchone()[0] == 2
    assert conn.execute("SELECT count(*) FROM embeddings").fetchone()[0] == 2
    assert conn.execute("SELECT count(*) FROM assets").fetchone()[0] > 0
    conn.close()
    for path in asset_paths:
        assert schema.resolve_asset_path(database_path, path).exists()


def test_embedding_failure_leaves_database_unchanged(
    one_pdf_corpus, manifest_path, corpus_dir, database_path, make_embedder
):
    class BoomEmbedder:
        calls: list = []

        def embed(self, texts):
            raise RuntimeError("simulated embedding backend failure")

    with pytest.raises(RuntimeError, match="simulated embedding backend failure"):
        sync_module.sync(corpus_dir, manifest_path, database_path, embedder=BoomEmbedder())

    # An empty schema may already exist (created on first connect), but no
    # application data (sources/chunks/embeddings) may have been written.
    conn = schema.connect(database_path)
    try:
        assert conn.execute("SELECT count(*) FROM sources").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM chunks").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM embeddings").fetchone()[0] == 0
    finally:
        conn.close()


def test_source_changes_mid_embedding_aborts(
    one_pdf_corpus, manifest_path, corpus_dir, database_path, make_embedder
):
    embedder = make_embedder()

    class MutatingEmbedder:
        def __init__(self, inner):
            self.inner = inner
            self.calls = inner.calls

        def embed(self, texts):
            vectors = self.inner.embed(texts)
            # Simulate a concurrent writer modifying the source mid-sync.
            build_pdf(
                one_pdf_corpus,
                [["Changed", "This file changed after parsing began, so the whole sync must abort safely."]],
            )
            return vectors

    report = sync_module.sync(
        corpus_dir, manifest_path, database_path, embedder=MutatingEmbedder(embedder)
    )
    assert report.status == "aborted-source-changed"

    conn = schema.connect(database_path)
    assert conn.execute("SELECT count(*) FROM sources").fetchone()[0] == 0
    conn.close()


def test_embedding_model_change_invalidates_only_relevant_cache(
    one_pdf_corpus, manifest_path, corpus_dir, database_path, make_embedder
):
    embedder = make_embedder()
    sync_module.sync(corpus_dir, manifest_path, database_path, embedder=embedder)

    conn = schema.connect(database_path)
    original_model_id = schema.embedding_model_id()
    original_embedding_count = conn.execute(
        "SELECT count(*) FROM embeddings WHERE model_id = ?", (original_model_id,)
    ).fetchone()[0]
    conn.close()
    assert original_embedding_count == 2

    other_options = SyncOptions(embedding_model=schema.EMBEDDING_MODEL, embedding_revision="fake-revision-2")
    # Reuse the same warm underlying model (revision differs only in label
    # for this test) so no network access is required.
    new_embedder = make_embedder()
    report = sync_module.sync(
        corpus_dir, manifest_path, database_path, options=other_options, embedder=new_embedder
    )
    # Nothing about the source, parse, or chunks changed -- only the active
    # embedding model's cache coverage -- so no reparse/rechunk is recorded.
    assert report.sources_reparsed == []
    assert report.sources_rechunked == []
    assert report.embeddings_generated == 2

    conn = schema.connect(database_path)
    old_count = conn.execute(
        "SELECT count(*) FROM embeddings WHERE model_id = ?", (original_model_id,)
    ).fetchone()[0]
    new_count = conn.execute(
        "SELECT count(*) FROM embeddings WHERE model_id = ?", (other_options.model_id,)
    ).fetchone()[0]
    conn.close()
    assert old_count == 2  # untouched, not deleted
    assert new_count == 2  # generated fresh for the new model


def test_bad_embedding_dimension_rejected_before_database_writes(one_pdf_corpus, manifest_path, corpus_dir, database_path):
    class BadDimensionEmbedder:
        calls: list[list[str]] = []

        def embed(self, texts):
            self.calls.append(list(texts))
            return [[1.0, 2.0, 3.0] for _ in texts]

    with pytest.raises(SyncError, match="embedding dimension"):
        sync_module.sync(corpus_dir, manifest_path, database_path, embedder=BadDimensionEmbedder())
    conn = schema.connect(database_path)
    try:
        assert conn.execute("SELECT count(*) FROM sources").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM embeddings").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM embedding_vectors").fetchone()[0] == 0
    finally:
        conn.close()


def test_embedding_dimension_change_rejected_before_vector_mutation(
    one_pdf_corpus, manifest_path, corpus_dir, database_path, make_embedder, monkeypatch
):
    sync_module.sync(corpus_dir, manifest_path, database_path, embedder=make_embedder())
    conn = schema.connect(database_path)
    try:
        before_config = dict(conn.execute("SELECT * FROM kb_config").fetchone())
        before_vectors = conn.execute("SELECT count(*) FROM embedding_vectors").fetchone()[0]
    finally:
        conn.close()


def test_cached_model_reactivation_commits_even_without_vector_work(
    one_pdf_corpus, manifest_path, corpus_dir, database_path, make_embedder
):
    sync_module.sync(corpus_dir, manifest_path, database_path, embedder=make_embedder())
    original_id = schema.embedding_model_id()
    b_options = SyncOptions(embedding_revision="revision-b")
    sync_module.sync(corpus_dir, manifest_path, database_path, options=b_options, embedder=make_embedder())
    conn = schema.connect(database_path)
    try:
        assert schema.load_config(conn).embedding_model_id == b_options.model_id
        original_count = conn.execute("SELECT count(*) FROM embeddings WHERE model_id = ?", (original_id,)).fetchone()[0]
    finally:
        conn.close()
    assert original_count > 0

    report = sync_module.sync(corpus_dir, manifest_path, database_path, embedder=make_embedder())
    assert report.embeddings_generated == 0
    conn = schema.connect(database_path)
    try:
        assert schema.load_config(conn).embedding_model_id == original_id
    finally:
        conn.close()


def test_activation_failure_rolls_back_new_vectors_and_keeps_old_config(
    one_pdf_corpus, manifest_path, corpus_dir, database_path, make_embedder, monkeypatch
):
    sync_module.sync(corpus_dir, manifest_path, database_path, embedder=make_embedder())
    conn = schema.connect(database_path)
    try:
        before_config = dict(conn.execute("SELECT * FROM kb_config").fetchone())
        before_embeddings = [dict(row) for row in conn.execute("SELECT * FROM embeddings ORDER BY embedding_id").fetchall()]
        before_vectors = conn.execute("SELECT count(*) FROM embedding_vectors").fetchone()[0]
    finally:
        conn.close()

    def fail_activation(*args, **kwargs):
        raise RuntimeError("activation failed after vectors")

    monkeypatch.setattr(sync_module.schema, "activate_embedding_config", fail_activation)
    with pytest.raises(RuntimeError, match="activation failed"):
        sync_module.sync(
            corpus_dir,
            manifest_path,
            database_path,
            options=SyncOptions(embedding_revision="failed-revision"),
            embedder=make_embedder(),
        )

    conn = schema.connect(database_path)
    try:
        assert dict(conn.execute("SELECT * FROM kb_config").fetchone()) == before_config
        assert [dict(row) for row in conn.execute("SELECT * FROM embeddings ORDER BY embedding_id").fetchall()] == before_embeddings
        assert conn.execute("SELECT count(*) FROM embedding_vectors").fetchone()[0] == before_vectors
    finally:
        conn.close()

    def fail_if_called(*args, **kwargs):
        raise AssertionError("vector backend must not be mutated for incompatible dimensions")

    monkeypatch.setattr(sync_module.vector_backend.SqliteVecBackend, "upsert", fail_if_called)
    options = SyncOptions(embedding_revision="new-revision", embedding_dimensions=3)
    with pytest.raises(SyncError, match="embedding dimensions"):
        sync_module.sync(corpus_dir, manifest_path, database_path, options=options, embedder=make_embedder())

    conn = schema.connect(database_path)
    try:
        assert dict(conn.execute("SELECT * FROM kb_config").fetchone()) == before_config
        assert conn.execute("SELECT count(*) FROM embedding_vectors").fetchone()[0] == before_vectors
    finally:
        conn.close()


def test_manifest_discovery_does_not_traverse_unmatched_noisy_dirs(corpus_dir, manifest_path, database_path, make_embedder):
    build_pdf(corpus_dir / "doc.pdf", [["X", "Only this explicit file should be inspected."]])
    noisy = corpus_dir / "node_modules" / "bad.pdf"
    noisy.parent.mkdir()
    noisy.write_bytes(b"not a real pdf and must not be parsed")
    write_manifest(manifest_path, {"doc.pdf": "doc.pdf"})
    report = sync_module.sync(corpus_dir, manifest_path, database_path, embedder=make_embedder())
    assert report.sources_added == ["doc.pdf"]


def test_sync_reports_never_indexed_missing_explicit_and_unmatched_glob(corpus_dir, manifest_path, database_path, make_embedder):
    manifest_path.write_text(
        'schema_version = 1\n[[source]]\npath = "missing.pdf"\n[[include]]\nglob = "reports/*.md"\n',
        encoding="utf-8",
    )
    report = sync_module.sync(corpus_dir, manifest_path, database_path, embedder=make_embedder())
    assert report.selected_missing_paths == ["missing.pdf"]
    assert report.unmatched_globs == ["reports/*.md"]
    assert report.indexed_unselected_paths == []


def test_sync_reports_indexed_vanished_glob_path_as_selected_missing_not_prunable(corpus_dir, manifest_path, database_path, make_embedder):
    build_markdown(corpus_dir / "reports" / "keep.md", "# Keep\n\nThis source is initially indexed.\n")
    manifest_path.write_text('schema_version = 1\n[[include]]\nglob = "reports/*.md"\n', encoding="utf-8")
    sync_module.sync(corpus_dir, manifest_path, database_path, embedder=make_embedder())
    (corpus_dir / "reports" / "keep.md").unlink()

    report = sync_module.sync(corpus_dir, manifest_path, database_path, embedder=make_embedder())

    assert report.selected_missing_paths == ["reports/keep.md"]
    assert report.indexed_unselected_paths == []
    conn = schema.connect(database_path)
    try:
        assert sync_module.plan_prune(conn, selected_paths=["reports/keep.md"]).paths == ()
    finally:
        conn.close()


def test_sync_local_exclusion_makes_indexed_path_unselected(corpus_dir, manifest_path, database_path, make_embedder, tmp_path):
    build_markdown(corpus_dir / "docs" / "excluded.md", "# Excluded\n\nThis source becomes locally excluded.\n")
    tracked = tmp_path / "tracked.toml"
    local = tmp_path / "local.toml"
    tracked.write_text('schema_version = 1\n[[include]]\nglob = "docs/*.md"\n', encoding="utf-8")
    local.write_text('schema_version = 1\n[[exclude]]\nglob = "docs/excluded.md"\n', encoding="utf-8")
    sync_module.sync(corpus_dir, tracked, database_path, embedder=make_embedder())

    report = sync_module.sync(corpus_dir, [tracked, local], database_path, embedder=make_embedder())

    assert report.selected_missing_paths == []
    assert report.indexed_unselected_paths == ["docs/excluded.md"]


def test_markdown_source_indexes_and_chunks(corpus_dir, manifest_path, database_path, make_embedder):
    build_markdown(
        corpus_dir / "report.md",
        "# Title\n\n## Intro\nThis introductory paragraph explains the synthetic report scope for tests.\n\n"
        "## Conclusion\nThis concluding paragraph wraps up the synthetic report for testing purposes.\n",
    )
    write_manifest(manifest_path, {"report.md": "report.md"})
    embedder = make_embedder()
    report = sync_module.sync(corpus_dir, manifest_path, database_path, embedder=embedder)
    assert report.sources_added == ["report.md"]

    conn = schema.connect(database_path)
    row = conn.execute("SELECT source_type FROM sources WHERE path='report.md'").fetchone()
    assert row["source_type"] == "markdown"
    chunk_rows = conn.execute("SELECT line_start, line_end FROM chunks").fetchall()
    assert all(row["line_start"] is not None for row in chunk_rows)
    conn.close()


def test_sync_ocr_fallback_populates_pages_and_chunks(corpus_dir, manifest_path, database_path, make_embedder):
    """A source with a genuinely no-text-layer page (task 0090 item 1) must
    still get real text into the ``pages``/``chunks`` tables through the
    normal sync path, via the two-stage OCR fallback -- while an ordinary
    text-layer page in the same document is completely unaffected."""

    build_pdf_with_image_only_page(
        corpus_dir / "scan.pdf",
        leading_pages=[["Intro", "This is a normal text page used only as a non-OCR control."]],
    )
    write_manifest(manifest_path, {"scan.pdf": "scan.pdf"})
    embedder = make_embedder()
    report = sync_module.sync(corpus_dir, manifest_path, database_path, embedder=embedder)
    assert report.sources_added == ["scan.pdf"]

    conn = schema.connect(database_path)
    try:
        page_rows = conn.execute(
            "SELECT physical_page, text, extraction_method FROM pages "
            "JOIN sources USING (source_pk) WHERE sources.path = 'scan.pdf' ORDER BY physical_page"
        ).fetchall()
        assert len(page_rows) == 2
        text_page, scanned_page = page_rows
        assert text_page["extraction_method"] == "pdf-pymupdf"
        assert scanned_page["extraction_method"].startswith("pdf-pymupdf-ocr-")
        assert "text layer" in scanned_page["text"].lower()

        chunk_rows = conn.execute(
            "SELECT body FROM chunks JOIN sources USING (source_pk) WHERE sources.path = 'scan.pdf' AND physical_page = 2"
        ).fetchall()
        assert chunk_rows
        assert any("text layer" in row["body"].lower() for row in chunk_rows)
        assert sync_module.integrity_check(conn) == []
    finally:
        conn.close()


def test_sync_ocr_lang_option_threaded_into_parser_config(
    corpus_dir, manifest_path, database_path, make_embedder
):
    """``SyncOptions.ocr_lang`` (the ``--ocr-lang`` CLI flag's backing
    option) must reach the PDF parser's config for PDF sources, and must
    not be attached to non-PDF sources at all."""

    build_pdf_with_image_only_page(corpus_dir / "scan.pdf")
    build_markdown(corpus_dir / "report.md", "# Title\n\nSome markdown body text for this test.\n")
    write_manifest(manifest_path, {"scan.pdf": "scan.pdf", "report.md": "report.md"})
    embedder = make_embedder()
    options = sync_module.SyncOptions(ocr_lang="eng")
    report = sync_module.sync(
        corpus_dir, manifest_path, database_path, embedder=embedder, options=options
    )
    assert set(report.sources_added) == {"scan.pdf", "report.md"}

    conn = schema.connect(database_path)
    try:
        pdf_config = json.loads(
            conn.execute(
                "SELECT parser_config FROM sources WHERE path = 'scan.pdf'"
            ).fetchone()["parser_config"]
        )
        assert pdf_config == {"ocr_lang": "eng"}

        markdown_config = json.loads(
            conn.execute(
                "SELECT parser_config FROM sources WHERE path = 'report.md'"
            ).fetchone()["parser_config"]
        )
        assert markdown_config == {}
    finally:
        conn.close()


def test_sync_figure_crop_nearby_text_lands_in_assets_table(
    corpus_dir, manifest_path, database_path, make_embedder
):
    """A figure crop with a caption directly above it must get that caption
    threaded into the ``assets.nearby_text`` column through the normal sync
    path (task 0090 item 2), while ``ocr_text``/``visual_description`` stay
    ``NULL`` (out of scope)."""

    import fitz

    helper = fitz.open()
    try:
        helper_page = helper.new_page(width=300, height=150)
        helper_page.insert_text((10, 80), "A simple figure", fontsize=18)
        image_bytes = helper_page.get_pixmap(dpi=150).tobytes("png")
    finally:
        helper.close()

    document = fitz.open()
    try:
        page = document.new_page()
        page.insert_text((72, 90), "Figure 1: Illustrative capacity chart shown below.", fontsize=11)
        page.insert_image(fitz.Rect(72, 110, 372, 260), stream=image_bytes)
        pdf_path = corpus_dir / "figure.pdf"
        document.save(pdf_path)
    finally:
        document.close()

    write_manifest(manifest_path, {"figure.pdf": "figure.pdf"})
    embedder = make_embedder()
    report = sync_module.sync(corpus_dir, manifest_path, database_path, embedder=embedder)
    assert report.sources_added == ["figure.pdf"]

    conn = schema.connect(database_path)
    try:
        rows = conn.execute(
            "SELECT asset_type, nearby_text, ocr_text, visual_description FROM assets "
            "JOIN sources USING (source_pk) WHERE sources.path = 'figure.pdf' AND asset_type = 'figure-crop'"
        ).fetchall()
        assert rows
        assert rows[0]["nearby_text"] is not None
        assert "Figure 1" in rows[0]["nearby_text"]
        assert rows[0]["ocr_text"] is None
        assert rows[0]["visual_description"] is None
    finally:
        conn.close()


def test_add_mutation_after_begin_with_restored_metadata_aborts_and_repairs(
    corpus_dir, manifest_path, database_path, make_embedder
):
    import os

    source = corpus_dir / "a.md"
    original = "# Heading\n\nEvidence alpha 1111.\n"
    replacement = "# Heading\n\nEvidence bravo 2222.\n"
    assert len(original.encode()) == len(replacement.encode())
    source.write_text(original, encoding="utf-8")
    write_manifest(manifest_path, {"a.md": "a.md"})

    def mutate_at_begin(event):
        if event == "begin-immediate":
            info = source.stat()
            source.write_text(replacement, encoding="utf-8")
            os.utime(source, ns=(info.st_atime_ns, info.st_mtime_ns))

    sync_module.ASSET_EVENT_HOOK = mutate_at_begin
    try:
        report = sync_module.sync(
            corpus_dir, manifest_path, database_path, embedder=make_embedder()
        )
    finally:
        sync_module.ASSET_EVENT_HOOK = None

    assert report.status == "aborted-source-changed"
    conn = schema.connect(database_path)
    try:
        assert conn.execute("SELECT count(*) FROM sources").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM chunks").fetchone()[0] == 0
    finally:
        conn.close()

    repair = sync_module.sync(
        corpus_dir, manifest_path, database_path, embedder=make_embedder()
    )
    assert repair.sources_added == ["a.md"]
    conn = schema.connect(database_path)
    try:
        body = "\n".join(row["body"] for row in conn.execute("SELECT body FROM chunks"))
        assert "Evidence bravo 2222." in body
    finally:
        conn.close()


def test_rename_mutation_after_final_capture_with_restored_metadata_aborts(
    corpus_dir, manifest_path, database_path, make_embedder
):
    import os

    old_path = corpus_dir / "old.md"
    original = "# Heading\n\nEvidence alpha 1111.\n"
    replacement = "# Heading\n\nEvidence bravo 2222.\n"
    assert len(original.encode()) == len(replacement.encode())
    old_path.write_text(original, encoding="utf-8")
    write_manifest(manifest_path, {"old.md": "old.md"})
    sync_module.sync(corpus_dir, manifest_path, database_path, embedder=make_embedder())

    new_path = corpus_dir / "new.md"
    old_path.rename(new_path)
    write_manifest(manifest_path, {"new.md": "new.md"})

    def mutate_after_capture(event):
        if event == "rename-final-state-captured":
            info = new_path.stat()
            new_path.write_text(replacement, encoding="utf-8")
            os.utime(new_path, ns=(info.st_atime_ns, info.st_mtime_ns))

    sync_module.ASSET_EVENT_HOOK = mutate_after_capture
    try:
        report = sync_module.sync(
            corpus_dir, manifest_path, database_path, embedder=make_embedder()
        )
    finally:
        sync_module.ASSET_EVENT_HOOK = None

    assert report.status == "aborted-source-changed"
    conn = schema.connect(database_path)
    try:
        assert [row["path"] for row in conn.execute("SELECT path FROM sources")] == ["old.md"]
        body = "\n".join(row["body"] for row in conn.execute("SELECT body FROM chunks"))
        assert "Evidence alpha 1111." in body
    finally:
        conn.close()


def test_reparse_mutation_at_precommit_rolls_back_and_repairs(
    corpus_dir, manifest_path, database_path, make_embedder
):
    import os

    source = corpus_dir / "a.md"
    initial = "# Heading\n\nEvidence alpha 1111.\n"
    planned = "# Heading\n\nEvidence bravo 2222.\n"
    replacement = "# Heading\n\nEvidence delta 3333.\n"
    assert len(initial.encode()) == len(planned.encode()) == len(replacement.encode())
    source.write_text(initial, encoding="utf-8")
    write_manifest(manifest_path, {"a.md": "a.md"})
    sync_module.sync(corpus_dir, manifest_path, database_path, embedder=make_embedder())
    source.write_text(planned, encoding="utf-8")

    def mutate_before_final_check(event):
        if event == "pre-commit-source-check":
            info = source.stat()
            source.write_text(replacement, encoding="utf-8")
            os.utime(source, ns=(info.st_atime_ns, info.st_mtime_ns))

    sync_module.ASSET_EVENT_HOOK = mutate_before_final_check
    try:
        report = sync_module.sync(
            corpus_dir, manifest_path, database_path, embedder=make_embedder()
        )
    finally:
        sync_module.ASSET_EVENT_HOOK = None

    assert report.status == "aborted-source-changed"
    conn = schema.connect(database_path)
    try:
        body = "\n".join(row["body"] for row in conn.execute("SELECT body FROM chunks"))
        assert "Evidence alpha 1111." in body
        assert "Evidence bravo 2222." not in body
    finally:
        conn.close()

    repair = sync_module.sync(
        corpus_dir, manifest_path, database_path, embedder=make_embedder()
    )
    assert repair.sources_reparsed == ["a.md"]
    conn = schema.connect(database_path)
    try:
        body = "\n".join(row["body"] for row in conn.execute("SELECT body FROM chunks"))
        assert "Evidence delta 3333." in body
    finally:
        conn.close()


def test_same_size_same_mtime_content_change_is_not_fast_unchanged(
    corpus_dir, manifest_path, database_path, make_embedder
):
    import hashlib
    import os

    source = corpus_dir / "a.md"
    original = "# Heading\n\nEvidence alpha 1111.\n"
    replacement = "# Heading\n\nEvidence bravo 2222.\n"
    assert len(original.encode()) == len(replacement.encode())
    source.write_text(original, encoding="utf-8")
    write_manifest(manifest_path, {"a.md": "a.md"})
    sync_module.sync(corpus_dir, manifest_path, database_path, embedder=make_embedder())

    info = source.stat()
    source.write_text(replacement, encoding="utf-8")
    os.utime(source, ns=(info.st_atime_ns, info.st_mtime_ns))

    report = sync_module.sync(
        corpus_dir, manifest_path, database_path, embedder=make_embedder()
    )
    assert report.sources_reparsed == ["a.md"]
    assert report.sources_unchanged == []

    conn = schema.connect(database_path)
    try:
        row = conn.execute("SELECT sha256 FROM sources WHERE path = 'a.md'").fetchone()
        assert row["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
        body = "\n".join(item["body"] for item in conn.execute("SELECT body FROM chunks"))
        assert "Evidence bravo 2222." in body
    finally:
        conn.close()
