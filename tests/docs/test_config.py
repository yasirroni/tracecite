from __future__ import annotations

from pathlib import Path

import pytest

from tracecite.docs.config import load_docs_contract


def _write_valid(root: Path, *, extra: str = "") -> Path:
    (root / "docs/authored").mkdir(parents=True)
    (root / "docs/retained").mkdir(parents=True)
    (root / "docs/source-links.toml").write_text("schema_version = 3\n", encoding="utf-8")
    path = root / "docs/tracecite.toml"
    path.write_text(
        'schema_version = 1\n[docs]\n'
        'authored_root = "docs/authored"\n'
        'retained_root = "docs/retained"\n'
        'staged_root = "docs/.tracecite-stage"\n'
        'source_links = "docs/source-links.toml"\n'
        'index_output = ".tracecite/docs/tracecite.sqlite"\n'
        'publication_exclude = ["data/", ".tracecite/", "docs/.tracecite-stage/"]\n'
        + extra,
        encoding="utf-8",
    )
    return path


def test_loads_schema_v1_and_repository_relative_paths(tmp_path: Path) -> None:
    contract = load_docs_contract(_write_valid(tmp_path), repo_root=tmp_path)
    assert contract.authored_root == (tmp_path / "docs/authored").resolve()
    assert contract.retained_root == (tmp_path / "docs/retained").resolve()
    assert contract.host_render_command is None


@pytest.mark.parametrize("field", ["authored_root", "retained_root", "staged_root", "source_links", "index_output"])
def test_rejects_absolute_and_parent_escape_paths(tmp_path: Path, field: str) -> None:
    path = _write_valid(tmp_path)
    text = path.read_text(encoding="utf-8")
    text = text.replace(f'{field} = "docs/', f'{field} = "/tmp/') if field != "index_output" else text.replace('index_output = ".tracecite/', 'index_output = "../')
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match="(absolute|outside|relative|escape)"):
        load_docs_contract(path, repo_root=tmp_path)


def test_rejects_retained_staged_overlap(tmp_path: Path) -> None:
    path = _write_valid(tmp_path).read_text(encoding="utf-8").replace(
        'staged_root = "docs/.tracecite-stage"', 'staged_root = "docs/retained/stage"'
    )
    config = tmp_path / "docs.toml"
    config.write_text(path, encoding="utf-8")
    with pytest.raises(ValueError, match="overlap|contain"):
        load_docs_contract(config, repo_root=tmp_path)


def test_rejects_symlink_escape(tmp_path: Path) -> None:
    path = _write_valid(tmp_path)
    outside = tmp_path.parent / "outside-docs"
    outside.mkdir()
    (tmp_path / "docs" / "escape").symlink_to(outside, target_is_directory=True)
    path.write_text(path.read_text(encoding="utf-8").replace(
        'authored_root = "docs/authored"', 'authored_root = "docs/escape"'
    ), encoding="utf-8")
    with pytest.raises(ValueError, match="outside"):
        load_docs_contract(path, repo_root=tmp_path)


def test_validates_optional_argument_array(tmp_path: Path) -> None:
    config = _write_valid(tmp_path, extra='host_render_command = ["julia", "docs/render.jl"]\n')
    assert load_docs_contract(config, repo_root=tmp_path).host_render_command == ("julia", "docs/render.jl")

    config.write_text(config.read_text(encoding="utf-8").replace(
        'host_render_command = ["julia", "docs/render.jl"]', 'host_render_command = "julia docs/render.jl"'
    ), encoding="utf-8")
    with pytest.raises(ValueError, match="argument array"):
        load_docs_contract(config, repo_root=tmp_path)


@pytest.mark.parametrize("command", ["[]", '["julia", 7]', '["", "docs/render.jl"]'])
def test_rejects_invalid_argument_array_items(tmp_path: Path, command: str) -> None:
    config = _write_valid(tmp_path, extra=f"host_render_command = {command}\n")
    with pytest.raises(ValueError, match="argument array"):
        load_docs_contract(config, repo_root=tmp_path)
