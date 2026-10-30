from pathlib import Path

import tracecite
from tracecite.cli import main


def test_skills_install_replaces_copies_in_agents_skills(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    stale = tmp_path / ".agents" / "skills" / "using-tracecite" / "stale.md"
    stale.parent.mkdir(parents=True)
    stale.write_text("old copy", encoding="utf-8")

    assert main(["skills", "install"]) == 0

    bundled = Path(tracecite.__file__).parent / "skills"
    for name in ("using-tracecite", "writing-evidence-backed-reports", "routing-documentation-source-links"):
        installed = tmp_path / ".agents" / "skills" / name / "SKILL.md"
        assert installed.read_text(encoding="utf-8") == (bundled / name / "SKILL.md").read_text(encoding="utf-8")
    assert not stale.exists()
