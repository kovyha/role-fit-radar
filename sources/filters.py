from config import TITLE_TERMS, TITLE_BLOCKLIST


def is_relevant_title(title: str) -> bool:
    """Return True if title matches at least one term and no blocklist entries."""
    t = title.lower()
    return (
        any(term in t for term in TITLE_TERMS)
        and not any(term in t for term in TITLE_BLOCKLIST)
    )
