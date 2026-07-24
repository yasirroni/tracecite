"""Repository-neutral author and freshness-check documentation modes."""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from .contract import DocsEvidenceContract
from .stage import stage_docs
from .vectorize import docs_index_freshness_diagnostics


@dataclass(frozen=True, slots=True)
class DocsModeResult:
    mode: str
    ok: bool
    manifest_path: Path
    diagnostics: tuple[str, ...] = ()


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _repo_files(root: Path, repo_root: Path, *, exclude: Path | None = None) -> dict[str, str]:
    if not root.exists():
        return {}
    return {path.relative_to(repo_root).as_posix(): _sha(path) for path in sorted(root.rglob("*")) if path.is_file() and path != exclude}


def _staged_files(source: Path, destination: Path, repo_root: Path) -> dict[str, str]:
    if not source.exists():
        return {}
    return {(destination / path.relative_to(source)).relative_to(repo_root).as_posix(): _sha(path) for path in sorted(source.rglob("*")) if path.is_file()}


def _manifest(contract: DocsEvidenceContract, config_path: Path, repo_root: Path, public_root: Path) -> dict[str, object]:
    manifest_path = contract.retained_root / ".tracecite-manifest.json"
    return {
        "schema_version": 1,
        "contract_sha256": _sha(config_path),
        "retained": _repo_files(contract.retained_root, repo_root, exclude=manifest_path),
        "public": _staged_files(public_root, contract.staged_root / "public", repo_root),
    }


def _dump(data: dict[str, object], path: Path) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def author_docs(contract: DocsEvidenceContract, *, config_path: str | Path, repo_root: str | Path) -> DocsModeResult:
    root = Path(repo_root).resolve()
    config = Path(config_path).resolve()
    if contract.host_render_command is not None:
        subprocess.run(list(contract.host_render_command), cwd=root, check=True)
    parent = contract.staged_root.parent
    parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".tracecite-author-", dir=parent))
    try:
        staged_retained = temporary / "retained"
        shutil.copytree(contract.retained_root, staged_retained, ignore=shutil.ignore_patterns(".tracecite-manifest.json"))
        staged = replace(contract, retained_root=staged_retained, staged_root=temporary / "stage")
        canonical_retained = contract.retained_root
        stage_docs(staged, target="local", repo_root=root, link_markdown_root=canonical_retained)
        stage_docs(staged, target="public", repo_root=root, link_markdown_root=canonical_retained)
        manifest = _manifest(contract, config, root, staged.staged_root / "public")
        manifest_tmp = temporary / "manifest.json"
        _dump(manifest, manifest_tmp)
        targets = [(contract.staged_root / "local", staged.staged_root / "local"), (contract.staged_root / "public", staged.staged_root / "public"), (contract.retained_root / ".tracecite-manifest.json", manifest_tmp)]
        backups: list[tuple[Path, Path]] = []
        promoted: list[Path] = []
        try:
            for destination, source in targets:
                backup = destination.with_name(destination.name + ".tracecite-previous")
                if backup.exists():
                    shutil.rmtree(backup) if backup.is_dir() else backup.unlink()
                if destination.exists():
                    os.replace(destination, backup)
                    backups.append((destination, backup))
            for destination, source in targets:
                destination.parent.mkdir(parents=True, exist_ok=True)
                os.replace(source, destination)
                promoted.append(destination)
            for _, backup in backups:
                if backup.exists():
                    shutil.rmtree(backup) if backup.is_dir() else backup.unlink()
        except Exception:
            for destination in promoted:
                if destination.exists():
                    shutil.rmtree(destination) if destination.is_dir() else destination.unlink()
            for destination, backup in reversed(backups):
                if backup.exists():
                    os.replace(backup, destination)
            raise
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return DocsModeResult("author", True, contract.retained_root / ".tracecite-manifest.json")


def check_docs(contract: DocsEvidenceContract, *, config_path: str | Path, repo_root: str | Path) -> DocsModeResult:
    root = Path(repo_root).resolve()
    manifest_path = contract.retained_root / ".tracecite-manifest.json"
    diagnostics: list[str] = []
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
            raise ValueError("invalid schema")
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        return DocsModeResult("check", False, manifest_path, (f"invalid manifest: {exc}",))
    if manifest.get("contract_sha256") != _sha(Path(config_path).resolve()):
        diagnostics.append("contract hash mismatch")
    try:
        temporary = Path(tempfile.mkdtemp(prefix=".tracecite-check-", dir=contract.staged_root.parent))
    except OSError as exc:
        return DocsModeResult("check", False, manifest_path, (f"temporary staging setup failed: {exc}",))
    try:
        expected_retained = temporary / "retained"
        shutil.copytree(contract.retained_root, expected_retained, ignore=shutil.ignore_patterns(".tracecite-manifest.json"))
        expected = replace(contract, retained_root=expected_retained, staged_root=temporary / "stage")
        canonical_retained = contract.retained_root
        stage_docs(expected, target="local", repo_root=root, link_markdown_root=canonical_retained)
        stage_docs(expected, target="public", repo_root=root, link_markdown_root=canonical_retained)
        expected_local = _staged_files(expected.staged_root / "local", contract.staged_root / "local", root)
        expected_public = _staged_files(expected.staged_root / "public", contract.staged_root / "public", root)
        actual_local = _staged_files(contract.staged_root / "local", contract.staged_root / "local", root)
        actual_public = _staged_files(contract.staged_root / "public", contract.staged_root / "public", root)
        retained = _repo_files(contract.retained_root, root, exclude=manifest_path)
        manifest_retained = manifest.get("retained", {})
        for label, actual, wanted in (("retained", retained, manifest_retained), ("local staged", actual_local, expected_local), ("public staged", actual_public, expected_public)):
            if actual != wanted:
                for path in sorted(set(actual) - set(wanted)):
                    diagnostics.append(f"{label} extra: {path}")
                for path in sorted(set(wanted) - set(actual)):
                    diagnostics.append(f"{label} missing: {path}")
                for path in sorted(set(actual) & set(wanted)):
                    if actual[path] != wanted[path]:
                        diagnostics.append(f"{label} hash mismatch: {path}")
        recorded_public = manifest.get("public", {})
        if recorded_public != expected_public:
            diagnostics.append("public staged manifest is stale")
        diagnostics.extend(
            docs_index_freshness_diagnostics(contract, repo_root=root)
        )
    except Exception as exc:
        diagnostics.append(f"staging expectation failed: {exc}")
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return DocsModeResult("check", not diagnostics, manifest_path, tuple(diagnostics))
