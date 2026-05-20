# sources/ashby.py
# Fetches jobs from the Ashby public job board API.
# No authentication required. One request returns all jobs with descriptions inline.

import requests
from config import JOB_CONTENT_MAX_CHARS, REQUEST_TIMEOUT_SECS, TITLE_TERMS, TITLE_BLOCKLIST
from sources.filters import passes_local_filter


ASHBY_API = "https://api.ashbyhq.com/posting-api/job-board/{org}"


def fetch_jobs(org: str, location_filter: str, seen_urls: set | None = None, *, allowlist: frozenset = TITLE_TERMS, blocklist: frozenset = TITLE_BLOCKLIST) -> list[dict]:
    """
    Fetch new jobs from an Ashby job board, filtered by location.

    Ashby returns all jobs with plain-text descriptions in a single request —
    no second API call needed. Location is checked against both the primary
    location and any secondaryLocations entries.

    Args:
        org:             Ashby organisation slug e.g. "openai"
        location_filter: String to match against job location e.g. "London"
        seen_urls:       URLs already recorded; these are skipped

    Returns:
        List of job dicts with keys: title, url, location, department, content
    """
    if seen_urls is None:
        seen_urls = set()

    url = ASHBY_API.format(org=org)
    try:
        response = requests.get(url, timeout=REQUEST_TIMEOUT_SECS)
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"[ashby] Failed to fetch {url}: {e}")
        return []

    jobs = response.json().get("jobs", [])

    results = []
    for job in jobs:
        if not _matches_location(job, location_filter):
            continue
        if not passes_local_filter(job.get("title", ""), allowlist, blocklist):
            continue

        job_url = job.get("jobUrl", "")
        if job_url in seen_urls:
            continue

        content = job.get("descriptionPlain", "") or ""

        results.append({
            "title":      job.get("title", ""),
            "url":        job_url,
            "location":   job.get("location", ""),
            "department": job.get("department", ""),
            "content":    content[:JOB_CONTENT_MAX_CHARS],
        })

    return results


def _matches_location(job: dict, location_filter: str) -> bool:
    """Return True if location_filter appears in the primary or any secondary location."""
    needle = location_filter.lower()
    locations = [job.get("location", "")] + [
        s.get("location", "") for s in job.get("secondaryLocations", [])
    ]
    return any(needle in loc.lower() for loc in locations)
