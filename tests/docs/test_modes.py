from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import pytest

from tracecite.docs import author_docs, check_docs, load_docs_contract, sync_docs_index
import tracecite.docs.modes as modes
from tracecite.evidence import schema


class FakeEmbedder:
    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            seed = sum((index + 1) * ord(char) for index, char in enumerate(text))
            vector = [0.0] * schema.EMBEDDING_DIMENSIONS
            vector[seed % schema.EMBEDDING_DIMENSIONS] = 1.0
            vectors.append(vector)
        return vectors


def _fixture(tmp_path: Path, *, hook: list[str] | None = None) -> tuple[Path, Path]:
    (tmp_path / "docs/authored").mkdir(parents=True)
    retained = tmp_path / "docs/retained"
    retained.mkdir()
    (retained / "index.md").write_text("# docs\n", encoding="utf-8")
    (retained / "nested").mkdir()
    (retained / "nested/page.md").write_text("# nested\n", encoding="utf-8")
    (tmp_path / "docs/source-links.toml").write_text("schema_version = 2\nsource = []\n", encoding="utf-8")
    command = "\nhost_render_command = [\"render\", \"--exact\"]" if hook else ""
    config = tmp_path / "docs/tracecite.toml"
    config.write_text(
        f"""schema_version = 1
[docs]
authored_root = "docs/authored"
retained_root = "docs/retained"
staged_root = "docs/.tracecite-stage"
source_links = "docs/source-links.toml"
index_output = ".tracecite/docs.sqlite"
publication_exclude = []{command}
""",
        encoding="utf-8",
    )
    return config, tmp_path


def _ready(tmp_path: Path):
    config, root = _fixture(tmp_path)
    contract = load_docs_contract(config, repo_root=root)
    author_docs(contract, config_path=config, repo_root=root)
    return config, root, contract


def _ready_indexed(tmp_path: Path):
    config, root, contract = _ready(tmp_path)
    sync_docs_index(contract, repo_root=root, embedder=FakeEmbedder())
    return config, root, contract


def _snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_author_and_check_are_public_modes(tmp_path: Path) -> None:
    config, root = _fixture(tmp_path)
    contract = load_docs_contract(config, repo_root=root)
    assert author_docs(contract, config_path=config, repo_root=root).mode == "author"
    result = check_docs(contract, config_path=config, repo_root=root)
    assert result.mode == "check"
    assert not result.ok
    assert any("documentation index database is missing" in issue for issue in result.diagnostics)


def test_author_hook_exact_once_and_check_never_runs_it(tmp_path: Path) -> None:
    config, root = _fixture(tmp_path, hook=True)
    contract = load_docs_contract(config, repo_root=root)
    with patch.object(modes.subprocess, "run") as run:
        author_docs(contract, config_path=config, repo_root=root)
        run.assert_called_once_with(["render", "--exact"], cwd=root.resolve(), check=True)
    with patch.object(modes.subprocess, "run", side_effect=AssertionError("check ran hook")):
        check_docs(contract, config_path=config, repo_root=root)


def test_manifest_is_deterministic_sorted_and_excludes_itself(tmp_path: Path) -> None:
    config, root, contract = _ready(tmp_path)
    manifest_path = contract.retained_root / ".tracecite-manifest.json"
    first = manifest_path.read_bytes()
    data = json.loads(first)
    assert data["schema_version"] == 1
    assert data["contract_sha256"] == hashlib.sha256(config.read_bytes()).hexdigest()
    assert list(data["retained"]) == sorted(data["retained"])
    assert list(data["public"]) == sorted(data["public"])
    assert all("tracecite-manifest" not in path for path in data["retained"])
    assert first.endswith(b"\n")
    assert first == (json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    author_docs(contract, config_path=config, repo_root=root)
    assert manifest_path.read_bytes() == first


@pytest.mark.parametrize(
    ("category", "mutation", "needle"),
    [
        ("retained", "missing", "retained missing: docs/retained/index.md"),
        ("retained", "extra", "retained extra: docs/retained/extra.md"),
        ("retained", "hash", "retained hash mismatch: docs/retained/index.md"),
        ("local staged", "missing", "local staged missing: docs/.tracecite-stage/local/index.md"),
        ("local staged", "extra", "local staged extra: docs/.tracecite-stage/local/extra.md"),
        ("local staged", "hash", "local staged hash mismatch: docs/.tracecite-stage/local/index.md"),
        ("public staged", "missing", "public staged missing: docs/.tracecite-stage/public/index.md"),
        ("public staged", "extra", "public staged extra: docs/.tracecite-stage/public/extra.md"),
        ("public staged", "hash", "public staged hash mismatch: docs/.tracecite-stage/public/index.md"),
    ],
)
def test_check_reports_each_stale_category(tmp_path: Path, category: str, mutation: str, needle: str) -> None:
    config, root, contract = _ready(tmp_path)
    if category == "retained":
        path = contract.retained_root / ("extra.md" if mutation == "extra" else "index.md")
    else:
        path = contract.staged_root / category.split()[0] / ("extra.md" if mutation == "extra" else "index.md")
    if mutation == "missing":
        path.unlink()
    elif mutation == "extra":
        path.write_text("extra\n", encoding="utf-8")
    else:
        path.write_text("changed\n", encoding="utf-8")
    result = check_docs(contract, config_path=config, repo_root=root)
    assert not result.ok
    assert needle in result.diagnostics


@pytest.mark.parametrize("payload", [None, "{}", '{"schema_version": 2}'])
def test_check_rejects_missing_malformed_or_wrong_schema_manifest(tmp_path: Path, payload: str | None) -> None:
    config, root, contract = _ready(tmp_path)
    manifest = contract.retained_root / ".tracecite-manifest.json"
    if payload is None:
        manifest.unlink()
    else:
        manifest.write_text(payload, encoding="utf-8")
    result = check_docs(contract, config_path=config, repo_root=root)
    assert not result.ok and "manifest" in result.diagnostics[0]


def test_check_reports_contract_hash_mismatch_and_is_read_only(tmp_path: Path) -> None:
    config, root, contract = _ready(tmp_path)
    before = _snapshot(root)
    config.write_text(config.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    result = check_docs(contract, config_path=config, repo_root=root)
    assert not result.ok and "contract hash mismatch" in result.diagnostics
    after = _snapshot(root)
    assert before.keys() == after.keys()
    assert all(before[key] == after[key] for key in before if key != "docs/tracecite.toml")


def test_check_reports_temporary_setup_failure(tmp_path: Path) -> None:
    config, root, contract = _ready(tmp_path)
    with patch.object(modes.tempfile, "mkdtemp", side_effect=OSError("cannot stage")):
        result = check_docs(contract, config_path=config, repo_root=root)
    assert not result.ok
    assert result.diagnostics == ("temporary staging setup failed: cannot stage",)


def test_check_success_and_failure_clean_temporary_trees_and_preserve_sibling(tmp_path: Path) -> None:
    config, root, contract = _ready_indexed(tmp_path)
    sibling = contract.staged_root / "unrelated"
    sibling.mkdir()
    (sibling / "keep.txt").write_text("keep", encoding="utf-8")
    before = _snapshot(root)
    assert check_docs(contract, config_path=config, repo_root=root).ok
    assert _snapshot(root) == before
    (contract.staged_root / "local/index.md").write_text("stale", encoding="utf-8")
    failed_before = _snapshot(root)
    assert not check_docs(contract, config_path=config, repo_root=root).ok
    assert _snapshot(root) == failed_before
    assert (sibling / "keep.txt").read_text(encoding="utf-8") == "keep"
    assert not list(root.glob("docs/.tracecite-check-*"))


def test_check_reports_index_freshness_diagnostics_when_never_indexed(tmp_path: Path) -> None:
    config, root, contract = _ready(tmp_path)
    result = check_docs(contract, config_path=config, repo_root=root)
    assert not result.ok
    assert any("index-input mirror is missing" in issue for issue in result.diagnostics)
    assert any("documentation index database is missing" in issue for issue in result.diagnostics)


def test_check_reports_index_freshness_diagnostics_when_indexed(tmp_path: Path) -> None:
    config, root, contract = _ready_indexed(tmp_path)
    result = check_docs(contract, config_path=config, repo_root=root)
    assert result.ok
    assert not any("documentation index database is missing" in issue for issue in result.diagnostics)


def test_hook_failure_preserves_outputs_and_sibling(tmp_path: Path) -> None:
    config, root, contract = _ready(tmp_path)
    sibling = contract.staged_root / "unrelated"
    sibling.mkdir()
    (sibling / "keep.txt").write_bytes(b"keep")
    before = _snapshot(root)
    failing = replace(contract, host_render_command=("render",))
    with patch.object(modes.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "render")):
        with pytest.raises(subprocess.CalledProcessError):
            author_docs(failing, config_path=config, repo_root=root)
    assert _snapshot(root) == before


def test_staging_failure_before_promotion_preserves_outputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config, root, contract = _ready(tmp_path)
    sibling = contract.staged_root / "unrelated"
    sibling.mkdir()
    (sibling / "keep").write_bytes(b"keep")
    before = _snapshot(root)
    monkeypatch.setattr(modes, "stage_docs", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("stage failed")))
    with pytest.raises(RuntimeError, match="stage failed"):
        author_docs(contract, config_path=config, repo_root=root)
    assert _snapshot(root) == before
    assert not list(root.glob("docs/.tracecite-author-*"))


@pytest.mark.parametrize("failure_target", ["local", "public", "manifest"])
def test_author_rollback_after_each_promotion_preserves_all_outputs(tmp_path: Path, failure_target: str, monkeypatch: pytest.MonkeyPatch) -> None:
    config, root, contract = _ready(tmp_path)
    sibling = contract.staged_root / "unrelated"
    sibling.mkdir()
    (sibling / "keep").write_bytes(b"keep")
    before = _snapshot(root)
    original = modes.os.replace
    target = {"local": contract.staged_root / "local", "public": contract.staged_root / "public", "manifest": contract.retained_root / ".tracecite-manifest.json"}[failure_target]
    def failing(source: str | Path, destination: str | Path) -> None:
        if Path(destination) == target and Path(source).name != target.name + ".tracecite-previous":
            raise OSError("injected promotion failure")
        original(source, destination)
    monkeypatch.setattr(modes.os, "replace", failing)
    with pytest.raises(OSError):
        author_docs(contract, config_path=config, repo_root=root)
    assert _snapshot(root) == before
    assert not list(root.rglob("*.tracecite-previous"))
    assert not list(root.glob("docs/.tracecite-author-*"))


def test_successful_author_replaces_all_outputs_and_preserves_sibling(tmp_path: Path) -> None:
    config, root, contract = _ready(tmp_path)
    old = (contract.staged_root / "local/index.md").read_bytes()
    (contract.retained_root / "index.md").write_text("new\n", encoding="utf-8")
    sibling = contract.staged_root / "unrelated"
    sibling.mkdir()
    (sibling / "keep").write_bytes(b"keep")
    author_docs(contract, config_path=config, repo_root=root)
    assert (contract.staged_root / "local/index.md").read_bytes() != old
    assert (contract.staged_root / "public/index.md").is_file()
    assert (contract.retained_root / ".tracecite-manifest.json").is_file()
    assert (sibling / "keep").read_bytes() == b"keep"


def test_publish_only_fixture_is_stdlib_static_and_isolated(tmp_path: Path) -> None:
    fixture = Path(__file__).parents[1] / "fixtures/publish-only"
    output = tmp_path / "published"
    subprocess.run([sys.executable, "-S", str(fixture / "build.py"), str(output)], check=True)
    assert (output / "index.md").read_bytes() == (fixture / "index.md").read_bytes()
    assert (output / "figure.svg").read_bytes() == (fixture / "figure.svg").read_bytes()
    source = "\n".join(path.read_text(encoding="utf-8") for path in fixture.glob("*.py"))
    assert "tracecite" not in source.lower()
    forbidden = {".pdf", ".sqlite", ".db", ".faiss", ".pt", ".pkl"}
    assert all(path.suffix.lower() not in forbidden for path in fixture.rglob("*"))
    assert not any(path.name in {"_generated", "__pycache__"} for path in fixture.rglob("*"))
