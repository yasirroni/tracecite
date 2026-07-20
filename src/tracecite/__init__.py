"""TraceCite: source-linked normalisation for executable knowledge documents."""

from .tables import (
    NORMALISER_VERSION,
    NormalisedTable,
    TableContext,
    TableDiagnostic,
    TableNormalisationError,
    augment_document_with_embedding_text,
    export_embedding_site,
    html_table_to_markdown,
    knowledge_table,
    normalise_document_tables,
    normalise_html_table,
    normalise_pandoc_table,
)

__version__ = "0.4.0"

__all__ = [
    "NORMALISER_VERSION",
    "NormalisedTable",
    "TableContext",
    "TableDiagnostic",
    "TableNormalisationError",
    "augment_document_with_embedding_text",
    "export_embedding_site",
    "html_table_to_markdown",
    "knowledge_table",
    "normalise_document_tables",
    "normalise_html_table",
    "normalise_pandoc_table",
]
