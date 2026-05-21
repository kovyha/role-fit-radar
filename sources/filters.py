import logging

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


def explain_filter_result(title: str, allowlist: frozenset | None, blocklist: frozenset) -> str | None:
    """Return None if the title passes, or a human-readable reason string if blocked.

    Checks blocklist before allowlist so the more specific reason surfaces when both fail.
    """
    t = f" {title.lower()} "

    for term in (blocklist or frozenset()):
        if term[0] == "*" and term[-1] == "*":
            bare = term[1:-1]
            if bare in t and f" {bare} " not in t:
                embedding = next((w for w in title.lower().split() if bare in w and w != bare), bare)
                return f"blocklist: {term} in '{embedding}'"
        else:
            if term in t:
                return f"blocklist: {term}"

    if allowlist and not any(term in t for term in allowlist):
        return "not in allowlist"

    return None


def log_filter_debug(
    logger: logging.Logger,
    fetched: list[str],
    blocked: list[tuple[str, str]],
    kept: list[str],
) -> None:
    """Emit a three-line DEBUG breakdown of a filtering pass."""
    if fetched:
        logger.debug(f"  fetched({len(fetched)}): {' | '.join(fetched)}")
    if blocked:
        logger.debug(f"  blocked({len(blocked)}): {' | '.join(f'{t} ({r})' for t, r in blocked)}")
    if kept:
        logger.debug(f"    kept({len(kept)}): {' | '.join(kept)}")


def is_relevant_title(title: str) -> bool:
    return passes_local_filter(title, TITLE_TERMS, TITLE_BLOCKLIST)
