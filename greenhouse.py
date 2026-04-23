# sources/greenhouse.py
# Fetches jobs from the Greenhouse public API for a given company board.
# No authentication required — this is a public endpoint.

import requests
from bs4 import BeautifulSoup


GREENHOUSE_API = "https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true"


def fetch_jobs(board: str, location_filter: str) -> list[dict]:
    """
    Fetch all jobs from a Greenhouse board, filtered by location.

    Args:
        board:           Greenhouse board slug e.g. "anthropic"
        location_filter: String to match against job location e.g. "London"

    Returns:
        List of job dicts with keys: title, url, location, department, content
    """
    url = GREENHOUSE_API.format(board=board)

    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"[greenhouse] Failed to fetch {url}: {e}")
        return []

    data = response.json()
    jobs = data.get("jobs", [])

    results = []
    for job in jobs:
        location = job.get("location", {}).get("name", "")

        # Filter by location — case-insensitive contains check
        if location_filter.lower() not in location.lower():
            continue

        # Department — Greenhouse returns a list, take first
        departments = job.get("departments", [])
        department = departments[0].get("name", "Unknown") if departments else "Unknown"

        # Strip HTML from job content for cleaner LLM input
        raw_content = job.get("content", "")
        clean_content = _strip_html(raw_content)

        results.append({
            "title":      job.get("title", ""),
            "url":        job.get("absolute_url", ""),
            "location":   location,
            "department": department,
            "content":    clean_content[:6000]  # cap at 6k chars to stay within token budget
        })

    return results


def _strip_html(html: str) -> str:
    """Strip HTML tags and return clean text."""
    if not html:
        return ""
    return BeautifulSoup(html, "html.parser").get_text(separator="\n", strip=True)
