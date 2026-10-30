"""Reusable documentation build and evidence-contract APIs."""

from .build import (
    BuildSelection,
    BuildVariant,
    DocsBuildResult,
    Language,
    build_docs,
    changed_retained_markdown,
    classify_render_inputs,
    discover_render_inputs,
    select_build_variant,
    snapshot_retained_markdown,
    stage_retained_markdown,
)
from .config import load_docs_contract
from .contract import DocsEvidenceContract
from .modes import DocsModeResult, author_docs, check_docs
from .stage import DocsStageResult, stage_docs
from .vectorize import (
    DocsIndexProfile,
    DocsIndexResult,
    doctor_docs_index,
    prepare_docs_index_input,
    resolve_docs_index_profile,
    search_docs_index,
    sync_docs_index,
)

__all__ = [
    "BuildSelection",
    "BuildVariant",
    "DocsBuildResult",
    "DocsEvidenceContract",
    "DocsIndexProfile",
    "DocsIndexResult",
    "DocsModeResult",
    "DocsStageResult",
    "Language",
    "author_docs",
    "build_docs",
    "changed_retained_markdown",
    "check_docs",
    "classify_render_inputs",
    "discover_render_inputs",
    "doctor_docs_index",
    "load_docs_contract",
    "prepare_docs_index_input",
    "resolve_docs_index_profile",
    "search_docs_index",
    "select_build_variant",
    "snapshot_retained_markdown",
    "stage_docs",
    "stage_retained_markdown",
    "sync_docs_index",
]
