# sources/eightfold.py
# Fetches jobs from an Eightfold AI job board.
# No authentication required. Two-phase: list endpoint for stubs, per-job
# detail endpoint for descriptions.

import html as html_lib
import requests
from bs4 import BeautifulSoup
from config import JOB_CONTENT_MAX_CHARS, REQUEST_TIMEOUT_SECS
from sources.filters import is_relevant_title


def fetch_jobs(domain: str, location_filter: str, seen_urls: set | None = None) -> list[dict]:
    """
    Fetch new jobs from an Eightfold board, filtered by location.

    Phase 1: paginate the list endpoint to collect all matching stubs.
    Phase 2: fetch the description for each job not already in seen_urls.

    Args:
        domain:          Eightfold domain e.g. "mlp.com"
        location_filter: Location string passed to Eightfold e.g. "London"
        seen_urls:       URLs already recorded; descriptions skipped for these

    Returns:
        List of job dicts with keys: title, url, location, department, content
    """
    if seen_urls is None:
        seen_urls = set()

    subdomain = domain.split(".")[0]
    base_url = f"https://{subdomain}.eightfold.ai/api/apply/v2/jobs"
    detail_base = f"https://{subdomain}.eightfold.ai/api/apply/v2/jobs"

    # Phase 1: paginate stubs
    stubs = _fetch_stubs(base_url, domain, location_filter)

    # Phase 2: fetch descriptions for new jobs only
    results = []
    for stub in stubs:
        if stub["url"] in seen_urls:
            continue
        if not is_relevant_title(stub["title"]):
            continue
        content = _fetch_content(detail_base, domain, stub.pop("id"))
        stub["content"] = content
        results.append(stub)

    return results


def _fetch_stubs(base_url: str, domain: str, location_filter: str) -> list[dict]:
    """Paginate the Eightfold list endpoint and return all matching job stubs."""
    stubs = []
    limit = 100
    start = 0

    while True:
        params = {
            "domain":   domain,
            "location": location_filter,
            "limit":    limit,
            "start":    start,
        }
        try:
            response = requests.get(base_url, params=params, timeout=REQUEST_TIMEOUT_SECS)
            response.raise_for_status()
        except requests.RequestException as e:
            print(f"[eightfold] Failed to fetch stubs (start={start}): {e}")
            break

        data = response.json()
        positions = data.get("positions", [])

        for job in positions:
            stubs.append({
                "id":         job["id"],
                "title":      job.get("name", ""),
                "url":        job.get("canonicalPositionUrl", ""),
                "location":   job.get("location", ""),
                "department": job.get("department", ""),
            })

        total = data.get("count", 0)
        start += len(positions)
        if start >= total or not positions:
            break

    return stubs


def _fetch_content(detail_base: str, domain: str, job_id: int) -> str:
    """Fetch and clean the description for a single Eightfold job."""
    url = f"{detail_base}/{job_id}"
    try:
        response = requests.get(url, params={"domain": domain}, timeout=REQUEST_TIMEOUT_SECS)
        response.raise_for_status()
        raw = response.json().get("job_description", "") or ""
        return _strip_html(raw)[:JOB_CONTENT_MAX_CHARS]
    except requests.RequestException as e:
        print(f"[eightfold] Failed to fetch content for job {job_id}: {e}")
        return ""


def _strip_html(html: str) -> str:
    """Strip HTML tags and return clean text, handling entity-encoded HTML."""
    if not html:
        return ""
    return BeautifulSoup(html_lib.unescape(html), "html.parser").get_text(separator="\n", strip=True)
