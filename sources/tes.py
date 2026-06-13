# sources/tes.py
# Scrapes TES Jobs (tes.com/jobs) for teaching and admin roles.
# Searches for each term in search_terms with optional part_time contract filter.
#
# Two-phase fetch:
#   Phase 1: search each term, collect stubs via page-based pagination
#   Phase 2: fetch full content from each new job detail page

import logging
import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote, urljoin

from config import JOB_CONTENT_MAX_CHARS, REQUEST_TIMEOUT_SECS
from sources.filters import explain_filter_result, log_filter_debug

logger = logging.getLogger(__name__.rsplit(".", 1)[-1])

TES_BASE = "https://www.tes.com"
TES_SEARCH = f"{TES_BASE}/jobs/search"
MAX_PAGES_PER_TERM = 5

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# TES contract type filter for part-time roles
_CONTRACT_PART_TIME = "part_time"


def fetch_jobs(
    location_filter: str,
    seen_urls: set | None = None,
    *,
    search_terms: frozenset = frozenset(),
    allowlist: frozenset = frozenset(),
    blocklist: frozenset = frozenset(),
) -> list[dict]:
    """
    Fetch teaching and admin jobs from TES Jobs for each search term.

    search_terms: keywords to query (e.g. {"eal", "english teacher", "admin"}).
    location_filter: appended as location radius search; pass "" for UK-wide.
    allowlist / blocklist: applied locally after fetching stubs.

    Returns list of job dicts: {title, url, company, location, department, content}
    """
    if seen_urls is None:
        seen_urls = set()

    terms = search_terms or frozenset([""])

    stubs: list[dict] = []
    seen_in_run: set[str] = set()
    debug_fetched: list[str] = []
    debug_blocked: list[tuple[str, str]] = []
    debug_kept: list[str] = []
    seen_count = 0

    for term in terms:
        params = f"?title={quote(term)}&contract={_CONTRACT_PART_TIME}"
        start_url = TES_SEARCH + params
        url: str | None = start_url
        pages = 0

        while url and pages < MAX_PAGES_PER_TERM:
            pages += 1
            try:
                resp = requests.get(url, headers=_HEADERS, timeout=REQUEST_TIMEOUT_SECS)
                resp.raise_for_status()
            except requests.RequestException as e:
                logger.error(f"TES: failed to fetch {url}: {e}")
                break

            jobs, url = _parse_listing_page(resp.text)
            if not jobs:
                break

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
                    "location": location,
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
    Parse a TES search results page.
    Job cards are <a href="/jobs/vacancy/..."> elements wrapping all card content.
    Returns (list of (title, url, company, location), next_page_url or None).
    """
    soup = BeautifulSoup(html, "html.parser")
    results: list[tuple[str, str, str, str]] = []
    seen_hrefs: set[str] = set()

    vacancy_pattern = re.compile(r"^/jobs/vacancy/")

    for link in soup.find_all("a", href=vacancy_pattern):
        href: str = link["href"]
        if href in seen_hrefs:
            continue
        seen_hrefs.add(href)

        job_url = TES_BASE + href

        # Title: <h3> or <h2> inside the card
        title_el = link.find(["h3", "h2", "h4"])
        title = title_el.get_text(strip=True) if title_el else link.get_text(strip=True)[:100]
        if not title:
            continue

        # Company: from alt text of org logo image, or first <p>/<span> after title
        company = ""
        img = link.find("img", alt=re.compile(r"logo", re.I))
        if img and img.get("alt"):
            company = re.sub(r"\s*logo\s*$", "", img["alt"], flags=re.I).strip()

        if not company:
            # Fallback: first paragraph/span that isn't the title
            for el in link.find_all(["p", "span"]):
                text = el.get_text(strip=True)
                if text and text != title:
                    company = text[:100]
                    break

        # Location: second meaningful text element after company
        location = ""
        text_els = [
            el.get_text(strip=True)
            for el in link.find_all(["p", "span"])
            if el.get_text(strip=True) and el.get_text(strip=True) != title
        ]
        if len(text_els) >= 2:
            location = text_els[1][:100]
        elif len(text_els) == 1 and text_els[0] != company:
            location = text_els[0][:100]

        results.append((title, job_url, company, location))

    # "Next page" pagination link
    next_url: str | None = None
    for a in soup.find_all("a", href=True):
        text = a.get_text(strip=True).lower()
        if "next" in text:
            href = a["href"]
            if href and ("search" in href or "page" in href or href.startswith("/")):
                next_url = urljoin(TES_BASE, href)
                break

    return results, next_url


def _fetch_content(url: str) -> str:
    """Fetch and return plain text from a TES job detail page."""
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=REQUEST_TIMEOUT_SECS)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"TES: failed to fetch content from {url}: {e}")
        return ""

    soup = BeautifulSoup(resp.text, "html.parser")

    content_el = (
        soup.find(class_=re.compile(r"job.description|vacancy.description|description|content", re.I))
        or soup.find("main")
        or soup.find("article")
    )

    text = (
        content_el.get_text(separator="\n", strip=True)
        if content_el
        else soup.get_text(separator="\n", strip=True)
    )
    return text[:JOB_CONTENT_MAX_CHARS]
