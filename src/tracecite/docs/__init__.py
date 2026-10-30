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
from .contract import DocsEvidenceContract
from .config import load_docs_contract
from .stage import DocsStageResult, stage_docs
from .modes import DocsModeResult, author_docs, check_docs
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
    "DocsStageResult",
    "DocsModeResult",
    "Language",
    "build_docs",
    "changed_retained_markdown",
    "classify_render_inputs",
    "discover_render_inputs",
    "load_docs_contract",
    "select_build_variant",
    "stage_docs",
    "snapshot_retained_markdown",
    "stage_retained_markdown",
    "author_docs",
    "check_docs",
    "DocsIndexProfile",
    "DocsIndexResult",
    "doctor_docs_index",
    "prepare_docs_index_input",
    "resolve_docs_index_profile",
    "search_docs_index",
    "sync_docs_index",
]
