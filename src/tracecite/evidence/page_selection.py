from __future__ import annotations

from collections.abc import Sequence


class PageSelectionError(ValueError):
    pass


class PageSelectionSyntaxError(PageSelectionError):
    pass


class PageSelectionUnavailableError(PageSelectionError):
    def __init__(self, page: int, message: str | None = None) -> None:
        self.page = page
        super().__init__(message or f"page {page} is unavailable")


def _validate_positive_page(text: str, *, selector: str) -> int:
    if not text.isdigit() or text.startswith("0"):
        raise PageSelectionSyntaxError(f"invalid page selector: {selector}")
    return int(text)


def _expand_closed_range(
    start: int, end: int, *, available_set: set[int], selector: str
) -> list[int]:
    if start > end:
        raise PageSelectionSyntaxError(f"invalid page selector: {selector}")
    pages = list(range(start, end + 1))
    missing = next((page for page in pages if page not in available_set), None)
    if missing is not None:
        raise PageSelectionUnavailableError(missing)
    return pages


def resolve_page_selection(
    selector: str | None,
    available_pages: Sequence[int],
    *,
    default_page: int = 1,
) -> list[int]:
    available = sorted({int(page) for page in available_pages})
    available_set = set(available)
    if selector is None:
        if default_page not in available_set:
            raise PageSelectionUnavailableError(default_page)
        return [default_page]

    selector = selector.strip()
    if not selector:
        raise PageSelectionSyntaxError("invalid page selector: empty selector")

    terms = [term.strip() for term in selector.split(",")]
    if any(term == "" for term in terms):
        raise PageSelectionSyntaxError(f"invalid page selector: {selector}")

    if len(terms) == 1 and terms[0] == "all":
        if not available:
            raise PageSelectionUnavailableError(default_page)
        return available
    if any(term == "all" for term in terms):
        raise PageSelectionSyntaxError(f"invalid page selector: {selector}")

    resolved: set[int] = set()
    for term in terms:
        # "N" is one page, "A-B" a closed range, "-N" pages 1 to N, and "N-"
        # page N to the last page.
        start_text, dash, end_text = term.partition("-")
        if dash and not start_text and not end_text:
            raise PageSelectionSyntaxError(f"invalid page selector: {selector}")
        start = (
            _validate_positive_page(start_text, selector=selector) if start_text else 1
        )
        end = _validate_positive_page(end_text, selector=selector) if end_text else None
        if not dash:
            end = start
        if not available:
            raise PageSelectionUnavailableError(default_page)
        if end is None:
            end = available[-1]
            if start > end:
                raise PageSelectionUnavailableError(start)
        resolved.update(
            _expand_closed_range(
                start, end, available_set=available_set, selector=selector
            )
        )

    return sorted(resolved)
