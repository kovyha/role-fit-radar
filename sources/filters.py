from config import TITLE_TERMS, TITLE_BLOCKLIST


def passes_local_filter(title: str, allowlist: frozenset, blocklist: frozenset) -> bool:
    """Return True if title passes the allowlist (empty = skip check) and blocklist.

    Glob-wrapped terms (e.g. '*ai*') use embedded-only matching in the blocklist:
    blocks when the term appears inside a larger word ('financial', 'html') but
    not when it stands alone ('AI Engineer', 'ML Quant').
    Plain terms match as substrings. Title is padded with spaces to support both.
    """
    t = f" {title.lower()} "

    def is_blocked(term: str) -> bool:
        if term[0] == "*" and term[-1] == "*":
            bare = term[1:-1]
            return bare in t and f" {bare} " not in t
        return term in t

    return (
        (not allowlist or any(term in t for term in allowlist))
        and not any(is_blocked(term) for term in blocklist)
    )


def is_relevant_title(title: str) -> bool:
    return passes_local_filter(title, TITLE_TERMS, TITLE_BLOCKLIST)
