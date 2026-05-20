from config import TITLE_TERMS, TITLE_BLOCKLIST


def passes_local_filter(title: str, allowlist: frozenset, blocklist: frozenset) -> bool:
    """Return True if title passes the allowlist (empty = skip check) and blocklist."""
    t = title.lower()
    return (
        (not allowlist or any(term in t for term in allowlist))
        and not any(term in t for term in blocklist)
    )


def is_relevant_title(title: str) -> bool:
    return passes_local_filter(title, TITLE_TERMS, TITLE_BLOCKLIST)
