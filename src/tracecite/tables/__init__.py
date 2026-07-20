"""Public table-normalisation API."""

from .document import (
    DocumentTransform,
    augment_document_with_embedding_text,
    normalise_document_tables,
)
from .html import html_table_to_markdown, normalise_html_table
from .models import (
    NORMALISER_VERSION,
    NormalisedTable,
    TableContext,
    TableDiagnostic,
    TableNormalisationError,
)
from .normalise import normalise_pandoc_table
from .publish import computed_first_row_summary, knowledge_table, table_metadata_comment
from .render import render_debug_markdown, render_embedding_block
from .site import SiteExportResult, export_embedding_site, render_embedding_site

__all__ = [
    "DocumentTransform",
    "NORMALISER_VERSION",
    "NormalisedTable",
    "SiteExportResult",
    "TableContext",
    "TableDiagnostic",
    "TableNormalisationError",
    "augment_document_with_embedding_text",
    "computed_first_row_summary",
    "export_embedding_site",
    "html_table_to_markdown",
    "knowledge_table",
    "normalise_document_tables",
    "normalise_html_table",
    "normalise_pandoc_table",
    "render_debug_markdown",
    "render_embedding_block",
    "render_embedding_site",
    "table_metadata_comment",
]
