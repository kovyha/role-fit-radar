# sources/greenhouse.py
# Fetches jobs from the Greenhouse public API for a given company board.
# No authentication required — this is a public endpoint.
#
# Two-phase approach:
#   Phase 1: GET /jobs          — all job stubs (title, location, url, id)
#   Phase 2: GET /jobs/{id}?content=true — description for each new job only
#
# Using ?content=true on the /jobs list endpoint silently truncates results
# for boards like QRT that don't publish all roles to the public board widget.

import html as html_lib
import logging
import requests
from bs4 import BeautifulSoup
from config import JOB_CONTENT_MAX_CHARS, REQUEST_TIMEOUT_SECS, TITLE_TERMS, TITLE_BLOCKLIST
from sources.filters import passes_local_filter, explain_filter_result, log_filter_debug

logger = logging.getLogger(__name__.rsplit(".", 1)[-1])


GREENHOUSE_JOBS_API = "https://boards-api.greenhouse.io/v1/boards/{board}/jobs"
GREENHOUSE_JOB_DETAIL_API = "https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{job_id}?content=true"


def fetch_jobs(board: str, location_filter: str, seen_urls: set | None = None, *, allowlist: frozenset = TITLE_TERMS, blocklist: frozenset = TITLE_BLOCKLIST) -> list[dict]:
    """
    Fetch new jobs from a Greenhouse board, filtered by location.

    Phase 1 fetches all stubs in one request. Phase 2 fetches the description
    for each job not already in seen_urls, avoiding redundant API calls.

    Args:
        board:           Greenhouse board slug e.g. "anthropic"
        location_filter: String to match against job location e.g. "London"
        seen_urls:       URLs already recorded; descriptions skipped for these

    Returns:
        List of job dicts with keys: title, url, location, department, content
    """
    if seen_urls is None:
        seen_urls = set()

    # Phase 1: fetch all job stubs
    stubs_url = GREENHOUSE_JOBS_API.format(board=board)
    try:
        response = requests.get(stubs_url, timeout=REQUEST_TIMEOUT_SECS)
        response.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"Failed to fetch {stubs_url}: {e}")
        return []

    data = response.json()
    stubs = data.get("jobs", [])

    # Filter by location, title relevance, and skip already-seen URLs
    candidates = []
    debug_fetched: list[str] = []
    debug_blocked: list[tuple[str, str]] = []
    debug_kept: list[str] = []
    seen_count = 0
    for job in stubs:
        location = job.get("location", {}).get("name", "")
        if location_filter.lower() not in location.lower():
            continue
        title = job.get("title", "")
        debug_fetched.append(title)
        if not passes_local_filter(title, allowlist, blocklist):
            debug_blocked.append((title, explain_filter_result(title, allowlist, blocklist)))
            continue
        debug_kept.append(title)
        job_url = job.get("absolute_url", "")
        if job_url in seen_urls:
            seen_count += 1
            continue
        departments = job.get("departments", [])
        department = departments[0].get("name", "Unknown") if departments else "Unknown"
        candidates.append({
            "id":             job["id"],
            "title":          title,
            "url":            job_url,
            "location":       location,
            "department":     department,
            "first_published": (job.get("first_published") or "")[:10] or None,
        })

    # Phase 2: fetch description for each new job
    results = []
    for job in candidates:
        content = _fetch_content(board, job.pop("id"))
        job["content"] = content
        results.append(job)

    log_filter_debug(logger, debug_fetched, debug_blocked, debug_kept,
                     total=len(debug_fetched), seen=seen_count, new=len(results))
    return results


def _fetch_content(board: str, job_id: int) -> str:
    """Fetch and clean the description for a single job."""
    url = GREENHOUSE_JOB_DETAIL_API.format(board=board, job_id=job_id)
    try:
        response = requests.get(url, timeout=REQUEST_TIMEOUT_SECS)
        response.raise_for_status()
        raw_content = response.json().get("content", "")
        return _strip_html(raw_content)[:JOB_CONTENT_MAX_CHARS]
    except requests.RequestException as e:
        logger.error(f"Failed to fetch content for job {job_id}: {e}")
        return ""


def _strip_html(html: str) -> str:
    """Strip HTML tags and return clean text."""
    if not html:
        return ""
    # Some boards (e.g. QRT) return HTML-entity-encoded HTML; unescape first so
    # BeautifulSoup sees real tags rather than entity text like &lt;p&gt;.
    return BeautifulSoup(html_lib.unescape(html), "html.parser").get_text(separator="\n", strip=True)
