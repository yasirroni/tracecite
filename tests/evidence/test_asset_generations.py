from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest

from tracecite.evidence import schema, sync as sync_module
from conftest import build_pdf, write_manifest


def _asset_state(database_path: Path):
    conn = schema.connect(database_path)
    try:
        rows = conn.execute("SELECT asset_path, sha256 FROM assets ORDER BY asset_path").fetchall()
        return [
            (
                row["asset_path"],
                row["sha256"],
                hashlib.sha256(schema.resolve_asset_path(database_path, row["asset_path"]).read_bytes()).hexdigest(),
            )
            for row in rows
        ]
    finally:
        conn.close()


def _source_paths(database_path: Path) -> list[str]:
    conn = schema.connect(database_path)
    try:
        return [row["path"] for row in conn.execute("SELECT path FROM sources ORDER BY path").fetchall()]
    finally:
        conn.close()


def _asset_rows(database_path: Path) -> list[tuple[str, int, str]]:
    conn = schema.connect(database_path)
    try:
        rows = conn.execute(
            "SELECT sources.path, assets.source_pk, assets.asset_path "
            "FROM assets JOIN sources USING (source_pk) ORDER BY sources.path, assets.asset_path"
        ).fetchall()
        return [(row["path"], row["source_pk"], row["asset_path"]) for row in rows]
    finally:
        conn.close()


def test_assets_are_written_to_generation_paths_and_hash_checked(corpus_dir, manifest_path, database_path, make_embedder):
    build_pdf(corpus_dir / "doc.pdf", [["Title", "Asset generation page text."]])
    write_manifest(manifest_path, {"doc.pdf": "doc.pdf"})
    sync_module.sync(corpus_dir, manifest_path, database_path, embedder=make_embedder())
    state = _asset_state(database_path)
    assert state
    assert all(path.startswith("imgs/generations/") for path, _, _ in state)
    assert all(not Path(path).is_absolute() for path, _, _ in state)
    assert all(
        schema.resolve_asset_path(database_path, path).is_relative_to(schema.imgs_dir(database_path) / "generations")
        for path, _, _ in state
    )
    assert all(stored == actual for _, stored, actual in state)
    schema.resolve_asset_path(database_path, state[0][0]).write_bytes(b"corrupt")
    conn = schema.connect(database_path)
    try:
        assert any("hash mismatch" in issue for issue in sync_module.integrity_check(conn))
    finally:
        conn.close()


def test_relative_asset_storage_relocates_with_database_and_imgs(corpus_dir, manifest_path, database_path, make_embedder, tmp_path):
    build_pdf(corpus_dir / "doc.pdf", [["Title", "Relocatable asset storage."]])
    write_manifest(manifest_path, {"doc.pdf": "doc.pdf"})
    sync_module.sync(corpus_dir, manifest_path, database_path, embedder=make_embedder())
    relocated = tmp_path / "relocated"
    relocated.mkdir()
    relocated_db = relocated / "tracecite.sqlite"
    shutil.copy2(database_path, relocated_db)
    shutil.copytree(schema.imgs_dir(database_path), relocated / "imgs")

    conn = schema.connect(relocated_db)
    try:
        rows = conn.execute("SELECT asset_path FROM assets").fetchall()
        assert rows
        assert all(row["asset_path"].startswith("imgs/generations/") for row in rows)
        assert sync_module.integrity_check(conn) == []
    finally:
        conn.close()


def test_schema_v3_rejects_existing_absolute_asset_paths(corpus_dir, manifest_path, database_path, make_embedder):
    build_pdf(corpus_dir / "doc.pdf", [["Title", "Absolute asset path compatibility check."]])
    write_manifest(manifest_path, {"doc.pdf": "doc.pdf"})
    sync_module.sync(corpus_dir, manifest_path, database_path, embedder=make_embedder())
    conn = schema.connect(database_path)
    try:
        stored = conn.execute("SELECT asset_path FROM assets LIMIT 1").fetchone()["asset_path"]
        absolute = schema.resolve_asset_path(database_path, stored)
        conn.execute("UPDATE assets SET asset_path = ?", (str(absolute),))
        conn.commit()
        with pytest.raises(schema.IncompatibleDatabaseError, match="absolute asset"):
            schema.ensure_schema(conn)
    finally:
        conn.close()


def test_new_source_assets_finalize_from_staging_to_source_pk_directory(corpus_dir, manifest_path, database_path, make_embedder):
    build_pdf(corpus_dir / "doc.pdf", [["Title", "New source assets start in staging and finish under source_pk."]])
    write_manifest(manifest_path, {"doc.pdf": "doc.pdf"})
    sync_module.sync(corpus_dir, manifest_path, database_path, embedder=make_embedder())

    conn = schema.connect(database_path)
    try:
        source_pk = conn.execute("SELECT source_pk FROM sources WHERE path = 'doc.pdf'").fetchone()["source_pk"]
        asset_paths = [schema.resolve_asset_path(database_path, row["asset_path"]) for row in conn.execute("SELECT asset_path FROM assets").fetchall()]
    finally:
        conn.close()
    assert asset_paths
    assert all(path.parent.name == str(source_pk) for path in asset_paths)
    generation_root = asset_paths[0].parents[1]
    assert not list(generation_root.glob(".staging-*"))


def test_asset_render_failure_discards_candidate_generation_and_keeps_old_assets(corpus_dir, manifest_path, database_path, make_embedder, monkeypatch):
    build_pdf(corpus_dir / "doc.pdf", [["Title", "Original asset bytes."]])
    write_manifest(manifest_path, {"doc.pdf": "doc.pdf"})
    sync_module.sync(corpus_dir, manifest_path, database_path, embedder=make_embedder())
    before = _asset_state(database_path)
    build_pdf(corpus_dir / "doc.pdf", [["Title", "Changed text that triggers reparse."]])
    def boom(*args, **kwargs):
        raise RuntimeError("render failed")
    monkeypatch.setattr(sync_module.pdf_parser, "render_page", boom)
    with pytest.raises(RuntimeError, match="render failed"):
        sync_module.sync(corpus_dir, manifest_path, database_path, embedder=make_embedder())
    assert _asset_state(database_path) == before
    generations = list((database_path.parent / "imgs" / "generations").glob("*"))
    assert len(generations) == 1


def test_new_source_staging_rename_failure_rolls_back_and_discards_generation(corpus_dir, manifest_path, database_path, make_embedder, monkeypatch):
    build_pdf(corpus_dir / "doc.pdf", [["Title", "Rename failure must not adopt candidate assets."]])
    write_manifest(manifest_path, {"doc.pdf": "doc.pdf"})

    original = sync_module.AssetGeneration.finalize_new_source

    def fail_finalize(self, source_pk: int):
        raise RuntimeError("rename failed")

    monkeypatch.setattr(sync_module.AssetGeneration, "finalize_new_source", fail_finalize)
    with pytest.raises(RuntimeError, match="rename failed"):
        sync_module.sync(corpus_dir, manifest_path, database_path, embedder=make_embedder())
    monkeypatch.setattr(sync_module.AssetGeneration, "finalize_new_source", original)

    conn = schema.connect(database_path)
    try:
        assert conn.execute("SELECT count(*) FROM sources").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM assets").fetchone()[0] == 0
    finally:
        conn.close()
    generations_root = database_path.parent / "imgs" / "generations"
    assert not generations_root.exists() or not list(generations_root.iterdir())


def test_asset_sql_commit_failure_keeps_prior_assets_and_discards_candidate_generation(corpus_dir, manifest_path, database_path, make_embedder, monkeypatch):
    build_pdf(corpus_dir / "doc.pdf", [["Title", "Original asset bytes."]])
    write_manifest(manifest_path, {"doc.pdf": "doc.pdf"})
    sync_module.sync(corpus_dir, manifest_path, database_path, embedder=make_embedder())
    before = _asset_state(database_path)
    before_generations = sorted(path.name for path in (database_path.parent / "imgs" / "generations").iterdir())

    build_pdf(corpus_dir / "doc.pdf", [["Title", "Changed content creates candidate assets before commit failure."]])

    def fail_touch_config(conn):
        raise RuntimeError("commit step failed")

    monkeypatch.setattr(sync_module.schema, "touch_config", fail_touch_config)
    with pytest.raises(RuntimeError, match="commit step failed"):
        sync_module.sync(corpus_dir, manifest_path, database_path, embedder=make_embedder())

    assert _asset_state(database_path) == before
    after_generations = sorted(path.name for path in (database_path.parent / "imgs" / "generations").iterdir())
    assert after_generations == before_generations


def test_actual_commit_failure_rolls_back_or_recovers_without_candidate_adoption(corpus_dir, manifest_path, database_path, make_embedder, monkeypatch):
    build_pdf(corpus_dir / "doc.pdf", [["Title", "Original asset bytes."]])
    write_manifest(manifest_path, {"doc.pdf": "doc.pdf"})
    sync_module.sync(corpus_dir, manifest_path, database_path, embedder=make_embedder())
    before = _asset_state(database_path)

    real_connect = sync_module.schema.connect
    failed = {"done": False}

    class CommitFailConnection:
        def __init__(self, inner):
            self.inner = inner

        def execute(self, sql, *args, **kwargs):
            if str(sql).strip().upper() == "COMMIT" and not failed["done"]:
                failed["done"] = True
                raise RuntimeError("actual COMMIT failed")
            return self.inner.execute(sql, *args, **kwargs)

        def __getattr__(self, name):
            return getattr(self.inner, name)

    def connect_proxy(path):
        return CommitFailConnection(real_connect(path))

    build_pdf(corpus_dir / "doc.pdf", [["Title", "Changed content reaches actual COMMIT."]])
    monkeypatch.setattr(sync_module.schema, "connect", connect_proxy)
    with pytest.raises(RuntimeError, match="actual COMMIT failed"):
        sync_module.sync(corpus_dir, manifest_path, database_path, embedder=make_embedder())
    monkeypatch.setattr(sync_module.schema, "connect", real_connect)

    assert _asset_state(database_path) == before
    conn = schema.connect(database_path)
    try:
        assert sync_module.integrity_check(conn) == []
    finally:
        conn.close()


def test_asset_hashing_completes_before_write_transaction(corpus_dir, manifest_path, database_path, make_embedder, monkeypatch):
    build_pdf(corpus_dir / "doc.pdf", [["Title", "Hashing must finish before BEGIN IMMEDIATE."]])
    write_manifest(manifest_path, {"doc.pdf": "doc.pdf"})
    events: list[str] = []
    monkeypatch.setattr(sync_module, "ASSET_EVENT_HOOK", events.append)
    sync_module.sync(corpus_dir, manifest_path, database_path, embedder=make_embedder())
    assert "asset-hash" in events
    assert "begin-immediate" in events
    assert max(index for index, event in enumerate(events) if event == "asset-hash") < events.index("begin-immediate")


def test_prune_apply_removes_only_pruned_physical_asset_directory_from_shared_generation(corpus_dir, manifest_path, database_path, make_embedder):
    build_pdf(corpus_dir / "keep.pdf", [["Keep", "Retained source asset bytes."]])
    build_pdf(corpus_dir / "remove.pdf", [["Remove", "Pruned source asset bytes."]])
    write_manifest(manifest_path, {"keep.pdf": "keep.pdf", "remove.pdf": "remove.pdf"})
    sync_module.sync(corpus_dir, manifest_path, database_path, embedder=make_embedder())
    conn = schema.connect(database_path)
    try:
        rows = conn.execute("SELECT sources.path, sources.source_pk, assets.asset_path FROM assets JOIN sources USING (source_pk)").fetchall()
        by_source = {row["path"]: (row["source_pk"], schema.resolve_asset_path(database_path, row["asset_path"])) for row in rows}
        keep_dir = by_source["keep.pdf"][1].parent
        remove_dir = by_source["remove.pdf"][1].parent
        assert keep_dir.parent == remove_dir.parent
        preview = sync_module.plan_prune(conn, selected_paths=["keep.pdf"])
        assert remove_dir.exists()
        leaks = sync_module.apply_prune(conn, database_path, preview)
        assert leaks == []
    finally:
        conn.close()
    assert keep_dir.exists()
    assert not remove_dir.exists()
    assert keep_dir.parent.exists()


def test_prune_cleanup_failure_reports_leak_and_preserves_database(corpus_dir, manifest_path, database_path, make_embedder, monkeypatch):
    build_pdf(corpus_dir / "remove.pdf", [["Remove", "Cleanup failure must be reported."]])
    write_manifest(manifest_path, {"remove.pdf": "remove.pdf"})
    sync_module.sync(corpus_dir, manifest_path, database_path, embedder=make_embedder())
    conn = schema.connect(database_path)
    try:
        plan = sync_module.plan_prune(conn, selected_paths=[])
        monkeypatch.setattr(sync_module, "_rmtree_dir_at", lambda *a, **k: (_ for _ in ()).throw(OSError("cleanup denied")))
        leaks = sync_module.apply_prune(conn, database_path, plan)
        assert any("cleanup denied" in leak for leak in leaks)
        assert conn.execute("SELECT count(*) FROM sources").fetchone()[0] == 0
        assert sync_module.integrity_check(conn) == []
    finally:
        conn.close()


def test_successful_sync_reports_post_commit_generation_cleanup_leak(corpus_dir, manifest_path, database_path, make_embedder, monkeypatch):
    build_pdf(corpus_dir / "doc.pdf", [["Title", "First generation."]])
    write_manifest(manifest_path, {"doc.pdf": "doc.pdf"})
    sync_module.sync(corpus_dir, manifest_path, database_path, embedder=make_embedder())
    build_pdf(corpus_dir / "doc.pdf", [["Title", "Second generation leaves first unreferenced."]])

    def fail_rmtree(path, *args, **kwargs):
        raise OSError("gc denied")

    monkeypatch.setattr(sync_module, "_rmtree_dir_at", fail_rmtree)
    report = sync_module.sync(corpus_dir, manifest_path, database_path, embedder=make_embedder())
    assert any("gc denied" in warning for warning in report.cleanup_warnings)
    conn = schema.connect(database_path)
    try:
        assert sync_module.integrity_check(conn) == []
    finally:
        conn.close()


def test_sync_can_defer_generation_cleanup_until_explicit_validation_step(corpus_dir, manifest_path, database_path, make_embedder):
    build_pdf(corpus_dir / "doc.pdf", [["Title", "First generation remains while bootstrap backup is live."]])
    write_manifest(manifest_path, {"doc.pdf": "doc.pdf"})
    sync_module.sync(corpus_dir, manifest_path, database_path, embedder=make_embedder())
    first_generation = next((database_path.parent / "imgs" / "generations").iterdir())

    build_pdf(corpus_dir / "doc.pdf", [["Title", "Second generation is current after validation."]])
    options = sync_module.SyncOptions(cleanup_asset_generations=False)
    report = sync_module.sync(corpus_dir, manifest_path, database_path, options=options, embedder=make_embedder())
    assert report.cleanup_warnings == []
    generations_root = database_path.parent / "imgs" / "generations"
    generations = {path for path in generations_root.iterdir() if path.is_dir()}
    assert first_generation in generations
    assert len(generations) == 2

    conn = schema.connect(database_path)
    try:
        referenced = sync_module.referenced_asset_generations(conn)
        assert first_generation not in referenced
        warnings = sync_module.cleanup_asset_generations(conn, database_path)
        assert warnings == []
    finally:
        conn.close()
    generations_after = {path for path in generations_root.iterdir() if path.is_dir()}
    assert first_generation not in generations_after
    assert generations_after == referenced


def test_explicit_asset_generation_cleanup_reports_leaks_without_corrupting_db(corpus_dir, manifest_path, database_path, make_embedder, monkeypatch):
    build_pdf(corpus_dir / "doc.pdf", [["Title", "First generation."]])
    write_manifest(manifest_path, {"doc.pdf": "doc.pdf"})
    sync_module.sync(corpus_dir, manifest_path, database_path, embedder=make_embedder())
    build_pdf(corpus_dir / "doc.pdf", [["Title", "Second generation leaves first unreferenced."]])
    sync_module.sync(corpus_dir, manifest_path, database_path, options=sync_module.SyncOptions(cleanup_asset_generations=False), embedder=make_embedder())
    monkeypatch.setattr(sync_module, "_rmtree_dir_at", lambda *a, **k: (_ for _ in ()).throw(OSError("cleanup denied")))
    conn = schema.connect(database_path)
    try:
        warnings = sync_module.cleanup_asset_generations(conn, database_path)
        assert any("cleanup denied" in warning for warning in warnings)
        assert sync_module.integrity_check(conn) == []
    finally:
        conn.close()


def test_cleanup_asset_generations_removes_stale_generation_with_descriptor_cleanup(corpus_dir, manifest_path, database_path, make_embedder):
    build_pdf(corpus_dir / "doc.pdf", [["Title", "First generation."]])
    write_manifest(manifest_path, {"doc.pdf": "doc.pdf"})
    sync_module.sync(corpus_dir, manifest_path, database_path, embedder=make_embedder())
    first_generation = next((database_path.parent / "imgs" / "generations").iterdir())
    build_pdf(corpus_dir / "doc.pdf", [["Title", "Second generation leaves first unreferenced."]])
    sync_module.sync(
        corpus_dir,
        manifest_path,
        database_path,
        options=sync_module.SyncOptions(cleanup_asset_generations=False),
        embedder=make_embedder(),
    )

    conn = schema.connect(database_path)
    try:
        warnings = sync_module.cleanup_asset_generations(conn, database_path)
        assert warnings == []
        assert not first_generation.exists()
        assert sync_module.integrity_check(conn) == []
    finally:
        conn.close()


def test_cleanup_asset_generations_unsupported_dirfd_warns_and_retains_all_assets(corpus_dir, manifest_path, database_path, make_embedder, monkeypatch):
    build_pdf(corpus_dir / "keep.pdf", [["Keep", "First generation keep."]])
    build_pdf(corpus_dir / "remove.pdf", [["Remove", "First generation remove."]])
    write_manifest(manifest_path, {"keep.pdf": "keep.pdf", "remove.pdf": "remove.pdf"})
    sync_module.sync(corpus_dir, manifest_path, database_path, embedder=make_embedder())
    first_generation = next((database_path.parent / "imgs" / "generations").iterdir())
    build_pdf(corpus_dir / "keep.pdf", [["Keep", "Second generation keep."]])
    sync_module.sync(
        corpus_dir,
        manifest_path,
        database_path,
        options=sync_module.SyncOptions(cleanup_asset_generations=False),
        embedder=make_embedder(),
    )
    before_paths = sorted(path.relative_to(database_path.parent).as_posix() for path in (database_path.parent / "imgs").rglob("*") if path.is_file())

    def unsupported():
        raise OSError("dir_fd unavailable")

    monkeypatch.setattr(sync_module, "_require_dirfd_primitives", unsupported)
    conn = schema.connect(database_path)
    try:
        plan = sync_module.plan_prune(conn, selected_paths=["keep.pdf"])
        warnings = sync_module.apply_prune(conn, database_path, plan)
        assert any("dir_fd unavailable" in warning for warning in warnings)
        assert first_generation.exists()
        after_paths = sorted(path.relative_to(database_path.parent).as_posix() for path in (database_path.parent / "imgs").rglob("*") if path.is_file())
        assert after_paths == before_paths
    finally:
        conn.close()


def test_cleanup_asset_generations_unlinks_replaced_generation_symlink_without_traversal(corpus_dir, manifest_path, database_path, make_embedder, monkeypatch, tmp_path):
    build_pdf(corpus_dir / "doc.pdf", [["Title", "First generation."]])
    write_manifest(manifest_path, {"doc.pdf": "doc.pdf"})
    sync_module.sync(corpus_dir, manifest_path, database_path, embedder=make_embedder())
    first_generation = next((database_path.parent / "imgs" / "generations").iterdir())
    build_pdf(corpus_dir / "doc.pdf", [["Title", "Second generation leaves first unreferenced."]])
    sync_module.sync(
        corpus_dir,
        manifest_path,
        database_path,
        options=sync_module.SyncOptions(cleanup_asset_generations=False),
        embedder=make_embedder(),
    )
    outside = tmp_path / "outside-stale-generation"
    outside.mkdir()
    sentinel = outside / "sentinel.txt"
    sentinel.write_text("do not delete", encoding="utf-8")
    real_referenced = sync_module.referenced_asset_generations

    def replace_after_reference_scan(conn, database):
        referenced = real_referenced(conn, database)
        shutil.rmtree(first_generation)
        first_generation.symlink_to(outside, target_is_directory=True)
        return referenced

    monkeypatch.setattr(sync_module, "referenced_asset_generations", replace_after_reference_scan)
    conn = schema.connect(database_path)
    try:
        warnings = sync_module.cleanup_asset_generations(conn, database_path)
        assert warnings == []
        assert sentinel.read_text(encoding="utf-8") == "do not delete"
        assert not first_generation.exists()
        assert not first_generation.is_symlink()
    finally:
        conn.close()


def test_prune_rejects_absolute_traversal_sibling_and_symlink_targets_atomically(tmp_path, make_embedder):
    for stored_asset_path in (
        str(tmp_path / "outside" / "absolute.png"),
        "imgs/generations/good/1/../../escape.png",
        "imgs/generations-good/1/page.png",
        "imgs\\generations\\good\\1\\page.png",
        "C:/foreign/generations/1/page.png",
        "imgs/generations/link/1/page.png",
        "imgs/generations/replaced/1/page.png",
    ):
        root = tmp_path / stored_asset_path.replace("/", "_").replace("\\", "_").replace(":", "")
        if root.exists():
            shutil.rmtree(root)
        corpus = root / "corpus"
        manifest = root / "manifest.toml"
        database = root / "tracecite.sqlite"
        corpus.mkdir(parents=True)
        build_pdf(corpus / "keep.pdf", [["Keep", "Retained asset."]])
        build_pdf(corpus / "remove.pdf", [["Remove", "Pruned asset."]])
        write_manifest(manifest, {"keep.pdf": "keep.pdf", "remove.pdf": "remove.pdf"})
        sync_module.sync(corpus, manifest, database, embedder=make_embedder())
        img_root = database.parent / "imgs"
        (img_root / "generations").mkdir(parents=True, exist_ok=True)
        (img_root / "generations" / "link").symlink_to(tmp_path, target_is_directory=True)
        (img_root / "generations" / "replaced").mkdir(parents=True, exist_ok=True)
        before_sources = _source_paths(database)
        before_assets = _asset_state(database)
        outside = tmp_path / "outside"
        outside.mkdir(exist_ok=True)
        (outside / "absolute.png").write_text("outside", encoding="utf-8")

        conn = schema.connect(database)
        try:
            remove_pk = conn.execute("SELECT source_pk FROM sources WHERE path = 'remove.pdf'").fetchone()["source_pk"]
            conn.execute("UPDATE assets SET asset_path = ? WHERE source_pk = ?", (stored_asset_path, remove_pk))
            conn.commit()
            plan = sync_module.plan_prune(conn, selected_paths=["keep.pdf"])
            if stored_asset_path == "imgs/generations/replaced/1/page.png":
                shutil.rmtree(img_root / "generations" / "replaced")
                (img_root / "generations" / "replaced").symlink_to(tmp_path, target_is_directory=True)
            with pytest.raises(ValueError):
                sync_module.apply_prune(conn, database, plan)
            assert [row["path"] for row in conn.execute("SELECT path FROM sources ORDER BY path")] == before_sources
        finally:
            conn.close()
        # The valid keep asset remains and the external sentinel was not deleted.
        assert all(schema.resolve_asset_path(database, path).exists() for path, _, _ in before_assets if "keep.pdf" not in path)
        assert (outside / "absolute.png").exists()


def test_prune_rejects_mixed_valid_and_invalid_candidate_before_db_or_fs_mutation(tmp_path, make_embedder):
    corpus = tmp_path / "corpus"
    manifest = tmp_path / "manifest.toml"
    database = tmp_path / "tracecite.sqlite"
    corpus.mkdir()
    build_pdf(corpus / "keep.pdf", [["Keep", "Retained asset."]])
    build_pdf(corpus / "remove-ok.pdf", [["Remove OK", "Valid pruned asset."]])
    build_pdf(corpus / "remove-bad.pdf", [["Remove bad", "Invalid pruned asset."]])
    write_manifest(manifest, {"keep.pdf": "keep.pdf", "remove-ok.pdf": "remove-ok.pdf", "remove-bad.pdf": "remove-bad.pdf"})
    sync_module.sync(corpus, manifest, database, embedder=make_embedder())
    before_sources = _source_paths(database)
    before_assets = _asset_rows(database)
    remove_ok_dir = schema.resolve_asset_path(
        database,
        next(path for source, _, path in before_assets if source == "remove-ok.pdf"),
    ).parent

    conn = schema.connect(database)
    try:
        bad_pk = conn.execute("SELECT source_pk FROM sources WHERE path = 'remove-bad.pdf'").fetchone()["source_pk"]
        conn.execute("UPDATE assets SET asset_path = 'imgs/generations/page.png' WHERE source_pk = ?", (bad_pk,))
        conn.commit()
        before_assets = _asset_rows(database)
        plan = sync_module.plan_prune(conn, selected_paths=["keep.pdf"])
        with pytest.raises(ValueError, match="asset identifier"):
            sync_module.apply_prune(conn, database, plan)
        assert _source_paths(database) == before_sources
        assert _asset_rows(database) == before_assets
        assert remove_ok_dir.exists()
    finally:
        conn.close()


def test_prune_rejects_shallow_identifier_before_db_mutation(tmp_path, make_embedder):
    corpus = tmp_path / "corpus"
    manifest = tmp_path / "manifest.toml"
    database = tmp_path / "tracecite.sqlite"
    corpus.mkdir()
    build_pdf(corpus / "keep.pdf", [["Keep", "Retained asset."]])
    build_pdf(corpus / "remove.pdf", [["Remove", "Shallow asset path."]])
    write_manifest(manifest, {"keep.pdf": "keep.pdf", "remove.pdf": "remove.pdf"})
    sync_module.sync(corpus, manifest, database, embedder=make_embedder())
    before_sources = _source_paths(database)

    conn = schema.connect(database)
    try:
        remove_pk = conn.execute("SELECT source_pk FROM sources WHERE path = 'remove.pdf'").fetchone()["source_pk"]
        conn.execute("UPDATE assets SET asset_path = 'imgs/generations/page.png' WHERE source_pk = ?", (remove_pk,))
        conn.commit()
        before_assets = _asset_rows(database)
        plan = sync_module.plan_prune(conn, selected_paths=["keep.pdf"])
        with pytest.raises(ValueError, match="asset identifier"):
            sync_module.apply_prune(conn, database, plan)
        assert _source_paths(database) == before_sources
        assert _asset_rows(database) == before_assets
    finally:
        conn.close()


def test_prune_cleanup_revalidates_after_touch_config_symlink_replacement(tmp_path, make_embedder, monkeypatch):
    corpus = tmp_path / "corpus"
    manifest = tmp_path / "manifest.toml"
    database = tmp_path / "tracecite.sqlite"
    corpus.mkdir()
    build_pdf(corpus / "keep.pdf", [["Keep", "Retained asset."]])
    build_pdf(corpus / "remove.pdf", [["Remove", "Replacement probe asset."]])
    write_manifest(manifest, {"keep.pdf": "keep.pdf", "remove.pdf": "remove.pdf"})
    sync_module.sync(corpus, manifest, database, embedder=make_embedder())
    conn = schema.connect(database)
    try:
        remove_asset = conn.execute(
            "SELECT asset_path FROM assets JOIN sources USING (source_pk) WHERE sources.path = 'remove.pdf'"
        ).fetchone()["asset_path"]
        remove_dir = schema.resolve_asset_path(database, remove_asset).parent
        outside = tmp_path / "outside"
        outside.mkdir()
        sentinel = outside / "sentinel.txt"
        sentinel.write_text("do not delete", encoding="utf-8")
        real_touch_config = sync_module.schema.touch_config

        def replace_pruned_dir_after_touch_config(inner_conn):
            real_touch_config(inner_conn)
            shutil.rmtree(remove_dir)
            remove_dir.symlink_to(outside, target_is_directory=True)

        monkeypatch.setattr(sync_module.schema, "touch_config", replace_pruned_dir_after_touch_config)
        plan = sync_module.plan_prune(conn, selected_paths=["keep.pdf"])
        leaks = sync_module.apply_prune(conn, database, plan)
        assert leaks == []
        assert sentinel.read_text(encoding="utf-8") == "do not delete"
        assert not remove_dir.exists()
        assert not remove_dir.is_symlink()
        assert _source_paths(database) == ["keep.pdf"]
    finally:
        conn.close()


def test_prune_cleanup_revalidates_generation_ancestor_symlink_replacement(tmp_path, make_embedder, monkeypatch):
    corpus = tmp_path / "corpus"
    manifest = tmp_path / "manifest.toml"
    database = tmp_path / "tracecite.sqlite"
    corpus.mkdir()
    build_pdf(corpus / "keep.pdf", [["Keep", "Retained asset."]])
    build_pdf(corpus / "remove.pdf", [["Remove", "Generation replacement probe asset."]])
    write_manifest(manifest, {"keep.pdf": "keep.pdf", "remove.pdf": "remove.pdf"})
    sync_module.sync(corpus, manifest, database, embedder=make_embedder())
    conn = schema.connect(database)
    try:
        remove_asset = conn.execute(
            "SELECT asset_path FROM assets JOIN sources USING (source_pk) WHERE sources.path = 'remove.pdf'"
        ).fetchone()["asset_path"]
        remove_dir = schema.resolve_asset_path(database, remove_asset).parent
        generation_dir = remove_dir.parent
        outside = tmp_path / "outside-generation-target"
        outside.mkdir()
        sentinel = outside / "sentinel.txt"
        sentinel.write_text("do not delete", encoding="utf-8")
        real_touch_config = sync_module.schema.touch_config

        def replace_generation_after_touch_config(inner_conn):
            real_touch_config(inner_conn)
            shutil.rmtree(generation_dir)
            generation_dir.symlink_to(outside, target_is_directory=True)

        monkeypatch.setattr(sync_module.schema, "touch_config", replace_generation_after_touch_config)
        plan = sync_module.plan_prune(conn, selected_paths=["keep.pdf"])
        leaks = sync_module.apply_prune(conn, database, plan)
        assert leaks == []
        assert sentinel.read_text(encoding="utf-8") == "do not delete"
        assert not generation_dir.exists()
        assert not generation_dir.is_symlink()
        assert _source_paths(database) == ["keep.pdf"]
    finally:
        conn.close()


def test_trusted_asset_resolver_accepts_relative_identifier_under_imgs(tmp_path):
    database_path = tmp_path / "tracecite.sqlite"
    asset = schema.imgs_dir(database_path) / "generations" / "generation" / "1" / "page.png"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"asset")

    assert schema.resolve_asset_path(database_path, "imgs/generations/generation/1/page.png") == asset


@pytest.mark.parametrize(
    "identifier",
    [
        "",
        ".",
        "imgs/generations",
        "imgs//generations/1/page.png",
        "imgs/generations/./1/page.png",
        "imgs/generations/../1/page.png",
        "imgs\\generations\\1\\page.png",
        "C:/outside/page.png",
        "C:\\outside\\page.png",
        "//server/share/page.png",
        "/tmp/outside.png",
        "../outside.png",
        "imgs/generations/../../outside.png",
    ],
)
def test_trusted_asset_resolver_rejects_absolute_traversal_and_sibling_prefix(tmp_path, identifier):
    with pytest.raises(ValueError):
        schema.resolve_asset_path(tmp_path / "tracecite.sqlite", identifier)


def test_trusted_asset_resolver_rejects_sibling_prefix(tmp_path):
    database_path = tmp_path / "tracecite.sqlite"
    sibling = str(database_path.resolve().parent / "imgs2") + "/generations/1/page.png"
    with pytest.raises(ValueError):
        schema.resolve_asset_path(database_path, sibling)


def test_trusted_asset_resolver_rejects_symlink_escape_and_replacement(tmp_path):
    database_path = tmp_path / "tracecite.sqlite"
    root = schema.imgs_dir(database_path)
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "page.png").write_bytes(b"outside")
    generations = root / "generations"
    generations.mkdir()
    checked = generations / "checked"
    checked.mkdir()
    identifier = "imgs/generations/checked/page.png"

    stale_path = schema.resolve_asset_path(database_path, identifier)
    assert stale_path == checked / "page.png"
    checked.rename(generations / "real")
    (generations / "checked").symlink_to(outside, target_is_directory=True)

    # A resolver result is only a validation snapshot; it must be revalidated
    # immediately before use after a component can be replaced.
    assert stale_path.resolve() == outside / "page.png"
    with pytest.raises(ValueError):
        schema.resolve_asset_path(database_path, identifier)

    (generations / "escape").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        schema.resolve_asset_path(database_path, "imgs/generations/escape/page.png")
