from __future__ import annotations

import pytest

from tracecite.evidence.page_selection import (
    PageSelectionSyntaxError,
    PageSelectionUnavailableError,
    resolve_page_selection,
)


@pytest.mark.parametrize(
    ("selector", "available_pages", "expected"),
    [
        (None, [1, 2, 3], [1]),
        ("99", [99], [99]),
        ("97-99", [97, 98, 99], [97, 98, 99]),
        ("97-", [97, 98, 99, 100], [97, 98, 99, 100]),
        ("-99", list(range(1, 100)), list(range(1, 100))),
        ("5,12-15,20", [5, 12, 13, 14, 15, 20], [5, 12, 13, 14, 15, 20]),
        ("20,12-15,5", [5, 12, 13, 14, 15, 20], [5, 12, 13, 14, 15, 20]),
        ("12-15,14-20", list(range(12, 21)), list(range(12, 21))),
        ("all", [2, 4, 6], [2, 4, 6]),
    ],
)
def test_resolve_page_selection_supports_full_selector_grammar(selector, available_pages, expected):
    assert resolve_page_selection(selector, available_pages) == expected


@pytest.mark.parametrize("selector, available_pages", [("", [1, 2, 3]), (" ", [1, 2, 3]), ("1--2", [1, 2, 3]), ("1--2", []), ("0", [1, 2, 3]), ("-0", [1, 2, 3]), ("3-2", [1, 2, 3]), ("all,5", [1, 2, 3]), ("5,all", [1, 2, 3])])
def test_resolve_page_selection_rejects_invalid_syntax(selector, available_pages):
    with pytest.raises(PageSelectionSyntaxError):
        resolve_page_selection(selector, available_pages)


@pytest.mark.parametrize("selector, available_pages", [(None, [2, 3]), ("97-99", [97, 99]), ("97-", [97, 99]), ("-99", [1, 2, 4, 5])])
def test_resolve_page_selection_rejects_unavailable_pages(selector, available_pages):
    with pytest.raises(PageSelectionUnavailableError):
        resolve_page_selection(selector, available_pages)
