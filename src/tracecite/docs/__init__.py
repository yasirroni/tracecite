"""Reusable documentation build and evidence-contract APIs."""

from . import build as _build
from .build import (
    BuildSelection,
    BuildVariant,
    DocsBuildResult,
    Language,
    changed_retained_markdown,
    classify_render_inputs,
    discover_render_inputs,
    select_build_variant,
    snapshot_retained_markdown,
    stage_retained_markdown,
)
from .contract import DocsEvidenceContract
from .config import load_docs_contract

# Keep module attributes used by existing callers and tests while the
# implementation moves from ``tracecite.docs`` to ``tracecite.docs.build``.
shutil = _build.shutil
subprocess = _build.subprocess
export_embedding_site = _build.export_embedding_site


def build_docs(*args, **kwargs):
    """Compatibility wrapper preserving patchable module-level collaborators."""
    original = _build.export_embedding_site
    _build.export_embedding_site = export_embedding_site
    try:
        return _build.build_docs(*args, **kwargs)
    finally:
        _build.export_embedding_site = original

__all__ = [
    "BuildSelection",
    "BuildVariant",
    "DocsBuildResult",
    "DocsEvidenceContract",
    "Language",
    "build_docs",
    "changed_retained_markdown",
    "classify_render_inputs",
    "discover_render_inputs",
    "load_docs_contract",
    "select_build_variant",
    "snapshot_retained_markdown",
    "stage_retained_markdown",
]
