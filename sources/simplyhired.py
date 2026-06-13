# sources/simplyhired.py
# Scrapes SimplyHired UK (simplyhired.co.uk) for jobs matching specified search terms.
#
# Two-phase fetch:
#   Phase 1: search each term, collect stubs from listing pages (cursor pagination)
#   Phase 2: fetch full content from each new job detail page

import logging
import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote, urljoin

from config import JOB_CONTENT_MAX_CHARS, REQUEST_TIMEOUT_SECS
from sources.filters import explain_filter_result, log_filter_debug

logger = logging.getLogger(__name__.rsplit(".", 1)[-1])

SIMPLYHIRED_BASE = "https://www.simplyhired.co.uk"
SIMPLYHIRED_SEARCH = f"{SIMPLYHIRED_BASE}/search"
MAX_PAGES_PER_TERM = 5

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
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
    Fetch jobs from SimplyHired UK for each search term.

    search_terms: keywords to query (one search per term).
    location_filter: appended as the 'l' parameter; pass "" to search UK-wide.
    allowlist / blocklist: applied locally after fetching stubs.

    Returns list of job dicts: {title, url, company, location, department, content}
    """
    if seen_urls is None:
        seen_urls = set()

    terms = search_terms or frozenset([""])  # at least one empty query if no terms given

    stubs: list[dict] = []
    seen_in_run: set[str] = set()
    debug_fetched: list[str] = []
    debug_blocked: list[tuple[str, str]] = []
    debug_kept: list[str] = []
    seen_count = 0

    for term in terms:
        loc = location_filter or "uk"
        start_url = f"{SIMPLYHIRED_SEARCH}?q={quote(term)}&l={quote(loc)}"
        url: str | None = start_url
        pages = 0

        while url and pages < MAX_PAGES_PER_TERM:
            pages += 1
            try:
                resp = requests.get(url, headers=_HEADERS, timeout=REQUEST_TIMEOUT_SECS)
                resp.raise_for_status()
            except requests.RequestException as e:
                logger.error(f"SimplyHired: failed to fetch {url}: {e}")
                break

            jobs, url = _parse_listing_page(resp.text)

            for title, job_url, company, location in jobs:
                if job_url in seen_in_run:
                    continue
                if job_url in seen_urls:
                    seen_count += 1
                    seen_in_run.add(job_url)
                    continue

                debug_fetched.append(title)
                reason = explain_filter_result(title, allowlist, blocklist)
                if reason is not None:
                    debug_blocked.append((title, reason))
                    continue

                debug_kept.append(title)
                seen_in_run.add(job_url)
                stubs.append({
                    "title": title,
                    "url": job_url,
                    "company": company,
                    "location": location or "UK",
                    "department": "",
                    "first_published": None,
                })

    log_filter_debug(
        logger, debug_fetched, debug_blocked, debug_kept,
        total=len(debug_fetched), seen=seen_count, new=len(stubs),
    )

    results = []
    for stub in stubs:
        stub["content"] = _fetch_content(stub["url"])
        results.append(stub)

    return results


def _parse_listing_page(html: str) -> tuple[list[tuple[str, str, str, str]], str | None]:
    """
    Parse a SimplyHired search results page.
    Returns (list of (title, url, company, location), next_page_url or None).
    """
    soup = BeautifulSoup(html, "html.parser")
    results: list[tuple[str, str, str, str]] = []
    seen_hrefs: set[str] = set()

    # Job links follow /job/[alphanumeric-id] pattern
    job_link_pattern = re.compile(r"^/job/[A-Za-z0-9_\-]+$")

    for link in soup.find_all("a", href=True):
        href: str = link["href"]
        if not job_link_pattern.match(href):
            continue
        if href in seen_hrefs:
            continue
        seen_hrefs.add(href)

        job_url = SIMPLYHIRED_BASE + href
        title = link.get_text(strip=True)
        if not title:
            continue

        # Parent card: look for enclosing article/li/div
        card = link.find_parent(["article", "li", "div"])
        company = ""
        location = ""
        if card:
            company, location = _extract_company_location(card)

        results.append((title, job_url, company, location))

    # Cursor-based pagination: look for a "Next" page link
    next_url: str | None = None
    for a in soup.find_all("a", href=True):
        text = a.get_text(strip=True).lower()
        href = a["href"]
        if "next" in text and "cursor=" in href:
            next_url = urljoin(SIMPLYHIRED_BASE, href)
            break

    return results, next_url


def _extract_company_location(card) -> tuple[str, str]:
    """Heuristically extract company and location from a job card element."""
    # SimplyHired typically puts company then location as adjacent spans/paragraphs
    text_nodes = [
        el.get_text(strip=True)
        for el in card.find_all(["span", "p", "div"], recursive=False)
        if el.get_text(strip=True)
    ]
    # Fallback: get all text nodes from the card
    if not text_nodes:
        text_nodes = [
            t.strip() for t in card.stripped_strings
            if t.strip()
        ]

    company = text_nodes[0] if len(text_nodes) > 0 else ""
    location = text_nodes[1] if len(text_nodes) > 1 else ""
    # Avoid using long text chunks as company/location names
    company = company[:100] if len(company) < 100 else ""
    location = location[:100] if len(location) < 100 else ""
    return company, location


def _fetch_content(url: str) -> str:
    """Fetch and return plain text from a SimplyHired job detail page."""
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=REQUEST_TIMEOUT_SECS)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"SimplyHired: failed to fetch content from {url}: {e}")
        return ""

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
    return text[:JOB_CONTENT_MAX_CHARS]
