# sources/adzuna.py
# Fetches jobs from the Adzuna public API (api.adzuna.com/v1).
# Requires ADZUNA_APP_ID and ADZUNA_APP_KEY from environment.
#
# Two-phase fetch:
#   Phase 1: API search per term, collect stubs with title filtering
#   Phase 2: Fetch full content from each job's redirect URL

import logging
import os
import re
import requests
from bs4 import BeautifulSoup

from config import JOB_CONTENT_MAX_CHARS, REQUEST_TIMEOUT_SECS
from sources.filters import explain_filter_result, log_filter_debug

# Read directly from env so this module loads cleanly on configs that don't define these keys.
_APP_ID = os.environ.get("ADZUNA_APP_ID", "")
_APP_KEY = os.environ.get("ADZUNA_APP_KEY", "")

logger = logging.getLogger(__name__.rsplit(".", 1)[-1])

ADZUNA_SEARCH = "https://api.adzuna.com/v1/api/jobs/gb/search"
RESULTS_PER_PAGE = 50
MAX_PAGES_PER_TERM = 4

_CONTENT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}


def fetch_jobs(
    location_filter: str,
    seen_urls: set | None = None,
    *,
    search_terms: frozenset = frozenset(),
    allowlist: frozenset = frozenset(),
    blocklist: frozenset = frozenset(),
) -> list[dict]:
    """
    Fetch jobs from Adzuna for each search term.

    search_terms: keywords to query (one API search per term).
    location_filter: passed as the 'where' param; pass "" to search UK-wide.
    allowlist / blocklist: applied locally after fetching stubs.

    Raises RuntimeError for credential or auth failures so the caller can surface
    them in the run summary. Per-term network errors are logged and skipped.

    Returns list of job dicts: {title, url, company, location, department, content}.
    """
    if not _APP_ID or not _APP_KEY:
        raise RuntimeError("Adzuna: ADZUNA_APP_ID / ADZUNA_APP_KEY not configured")

    if seen_urls is None:
        seen_urls = set()

    terms = search_terms or frozenset([""])

    stub_pairs: list[tuple[dict, str]] = []  # (stub, api_description fallback)
    seen_in_run: set[str] = set()
    debug_fetched: list[str] = []
    debug_blocked: list[tuple[str, str]] = []
    debug_kept: list[str] = []
    seen_count = 0

    for term in terms:
        for page in range(1, MAX_PAGES_PER_TERM + 1):
            params: dict = {
                "app_id": _APP_ID,
                "app_key": _APP_KEY,
                "what": term,
                "results_per_page": RESULTS_PER_PAGE,
                "content-type": "application/json",
            }
            if location_filter:
                params["where"] = location_filter

            try:
                resp = requests.get(
                    f"{ADZUNA_SEARCH}/{page}",
                    params=params,
                    timeout=REQUEST_TIMEOUT_SECS,
                )
                resp.raise_for_status()
            except requests.HTTPError as e:
                if e.response is not None and e.response.status_code in (401, 403):
                    raise RuntimeError(
                        f"Adzuna: auth rejected ({e.response.status_code}) — check ADZUNA_APP_ID/ADZUNA_APP_KEY"
                    ) from e
                logger.error(f"Adzuna: HTTP error page {page} for '{term}': {e}")
                break
            except requests.RequestException as e:
                logger.error(f"Adzuna: network error page {page} for '{term}': {e}")
                break

            page_results = resp.json().get("results", [])
            if not page_results:
                break

            for job in page_results:
                job_id = str(job.get("id", ""))
                if not job_id:
                    continue

                # Use a stable canonical URL derived from the job ID for deduplication.
                # The full redirect_url contains per-request tracking tokens that change.
                canonical_url = f"https://www.adzuna.co.uk/jobs/details/{job_id}"
                redirect_url = job.get("redirect_url", canonical_url)

                title = job.get("title", "").strip()
                if not title:
                    continue

                if canonical_url in seen_in_run:
                    continue
                if canonical_url in seen_urls:
                    seen_count += 1
                    seen_in_run.add(canonical_url)
                    continue

                debug_fetched.append(title)
                reason = explain_filter_result(title, allowlist, blocklist)
                if reason is not None:
                    debug_blocked.append((title, reason))
                    continue

                debug_kept.append(title)
                seen_in_run.add(canonical_url)
                stub_pairs.append((
                    {
                        "title": title,
                        "url": canonical_url,
                        "company": job.get("company", {}).get("display_name", ""),
                        "location": job.get("location", {}).get("display_name", ""),
                        "department": "",
                        "first_published": (job.get("created") or "")[:10] or None,
                        "_redirect_url": redirect_url,
                    },
                    job.get("description", ""),
                ))

            if len(page_results) < RESULTS_PER_PAGE:
                break

    log_filter_debug(
        logger, debug_fetched, debug_blocked, debug_kept,
        total=len(debug_fetched), seen=seen_count, new=len(stub_pairs),
    )

    results = []
    for stub, api_description in stub_pairs:
        redirect_url = stub.pop("_redirect_url")
        stub["content"] = _fetch_content(redirect_url, fallback=api_description)
        results.append(stub)

    return results


def _fetch_content(url: str, fallback: str = "") -> str:
    """Fetch full text from a job detail page. Falls back to the truncated API description."""
    try:
        resp = requests.get(
            url, headers=_CONTENT_HEADERS,
            timeout=REQUEST_TIMEOUT_SECS, allow_redirects=True,
        )
        resp.raise_for_status()
    except requests.RequestException:
        return fallback

    soup = BeautifulSoup(resp.text, "html.parser")
    content_el = (
        soup.find(class_=re.compile(r"job.description|job.details|description|content", re.I))
        or soup.find("main")
        or soup.find("article")
    )
    text = (
        content_el.get_text(separator="\n", strip=True)
        if content_el
        else soup.get_text(separator="\n", strip=True)
    )
    return (text[:JOB_CONTENT_MAX_CHARS] if text.strip() else fallback)
