from __future__ import annotations

from collections.abc import Iterable, Sequence


class PageSelectionError(ValueError):
    pass


class PageSelectionSyntaxError(PageSelectionError):
    pass


class PageSelectionUnavailableError(PageSelectionError):
    def __init__(self, page: int, message: str | None = None) -> None:
        self.page = page
        super().__init__(message or f"page {page} is unavailable")


def _sorted_available_pages(available_pages: Iterable[int]) -> list[int]:
    return sorted({int(page) for page in available_pages})


def _validate_positive_page(text: str, *, selector: str) -> int:
    if not text.isdigit() or text.startswith("0"):
        raise PageSelectionSyntaxError(f"invalid page selector: {selector}")
    page = int(text)
    if page <= 0:
        raise PageSelectionSyntaxError(f"invalid page selector: {selector}")
    return page


def _expand_closed_range(start: int, end: int, *, available_set: set[int], selector: str) -> list[int]:
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
    available = _sorted_available_pages(available_pages)
    available_set = set(available)
    if selector is None:
        if default_page not in available_set:
            raise PageSelectionUnavailableError(default_page)
        return [default_page]

    selector = selector.strip()
    if not selector:
        raise PageSelectionSyntaxError("invalid page selector: empty selector")
    if selector == "--all-pages":
        raise PageSelectionSyntaxError("invalid page selector: --all-pages")

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
    max_available = available[-1] if available else None
    for term in terms:
        if term.endswith("-") and term != "-":
            start = _validate_positive_page(term[:-1], selector=selector)
            if not available:
                raise PageSelectionUnavailableError(default_page)
            assert max_available is not None
            if start > max_available:
                raise PageSelectionUnavailableError(start)
            resolved.update(_expand_closed_range(start, max_available, available_set=available_set, selector=selector))
            continue
        if term.startswith("-") and term != "-":
            end = _validate_positive_page(term[1:], selector=selector)
            if not available:
                raise PageSelectionUnavailableError(default_page)
            resolved.update(_expand_closed_range(1, end, available_set=available_set, selector=selector))
            continue
        if "-" in term:
            start_text, end_text = term.split("-", 1)
            if not start_text or not end_text:
                raise PageSelectionSyntaxError(f"invalid page selector: {selector}")
            start = _validate_positive_page(start_text, selector=selector)
            end = _validate_positive_page(end_text, selector=selector)
            if not available:
                raise PageSelectionUnavailableError(default_page)
            resolved.update(_expand_closed_range(start, end, available_set=available_set, selector=selector))
            continue
        page = _validate_positive_page(term, selector=selector)
        if not available:
            raise PageSelectionUnavailableError(default_page)
        if page not in available_set:
            raise PageSelectionUnavailableError(page)
        resolved.add(page)

    return sorted(resolved)
