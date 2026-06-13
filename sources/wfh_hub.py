# sources/wfh_hub.py
# Scrapes The Work From Home Hub (theworkfromhomehub.co.uk) for part-time remote jobs.
# Filters to "Fully Remote" and "Remote First" categories only.
#
# Two-phase fetch:
#   Phase 1: paginate listing pages, collect stubs that pass category + title filter
#   Phase 2: fetch full content from each job detail page

import logging
import re
import requests
from bs4 import BeautifulSoup

from config import JOB_CONTENT_MAX_CHARS, REQUEST_TIMEOUT_SECS
from sources.filters import explain_filter_result, log_filter_debug

logger = logging.getLogger(__name__.rsplit(".", 1)[-1])

WFH_BASE_URL = "https://www.theworkfromhomehub.co.uk"
WFH_LISTING_PATH = "/jobs"
MAX_PAGES = 15

# Category labels that meet Domi's "fully remote or once/twice a month in office" requirement
ALLOWED_REMOTE_CATEGORIES = {"fully remote", "remote first"}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
}


def fetch_jobs(
    location_filter: str,
    seen_urls: set | None = None,
    *,
    allowlist: frozenset = frozenset(),
    blocklist: frozenset = frozenset(),
) -> list[dict]:
    """
    Fetch part-time remote jobs from The Work From Home Hub.

    Ignores location_filter — jobs are already WFH-filtered at source via category.
    Only keeps listings categorised as "Fully Remote" or "Remote First".

    Returns list of job dicts: {title, url, company, location, department, content}
    """
    if seen_urls is None:
        seen_urls = set()

    stubs, debug_fetched, debug_blocked, debug_kept, seen_count = _collect_stubs(
        seen_urls, allowlist, blocklist
    )
    log_filter_debug(
        logger, debug_fetched, debug_blocked, debug_kept,
        total=len(debug_fetched), seen=seen_count, new=len(stubs),
    )

    results = []
    for stub in stubs:
        stub["content"] = _fetch_content(stub["url"])
        results.append(stub)

    return results


def _collect_stubs(
    seen_urls: set,
    allowlist: frozenset,
    blocklist: frozenset,
) -> tuple[list[dict], list[str], list[tuple[str, str]], list[str], int]:
    """Paginate listing pages; return (stubs, fetched, blocked, kept, seen_count)."""
    stubs: list[dict] = []
    seen_in_run: set[str] = set()
    debug_fetched: list[str] = []
    debug_blocked: list[tuple[str, str]] = []
    debug_kept: list[str] = []
    seen_count = 0

    url: str | None = f"{WFH_BASE_URL}{WFH_LISTING_PATH}?category=Part+Time"
    page_num = 0

    while url and page_num < MAX_PAGES:
        page_num += 1
        try:
            resp = requests.get(url, headers=_HEADERS, timeout=REQUEST_TIMEOUT_SECS)
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"Failed to fetch listing page {url}: {e}")
            break

        jobs, url = _parse_listing_page(resp.text)

        for title, job_url, categories, company in jobs:
            if job_url in seen_in_run:
                continue
            if job_url in seen_urls:
                seen_count += 1
                seen_in_run.add(job_url)
                continue

            # Only accept Fully Remote / Remote First
            if not any(cat in ALLOWED_REMOTE_CATEGORIES for cat in categories):
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
                "location": "Remote",
                "department": "",
                "first_published": None,
            })

    return stubs, debug_fetched, debug_blocked, debug_kept, seen_count


def _parse_listing_page(html: str) -> tuple[list[tuple[str, str, list[str], str]], str | None]:
    """
    Parse a WFH Hub listing page.
    Returns (list of (title, url, categories, company), next_page_url or None).
    """
    soup = BeautifulSoup(html, "html.parser")
    results: list[tuple[str, str, list[str], str]] = []
    seen_hrefs: set[str] = set()

    # Job title links: href starts with /jobs/ but not a category or paginated listing URL
    for link in soup.find_all("a", href=True):
        href: str = link["href"]
        if not href.startswith("/jobs/"):
            continue
        if "/category/" in href or href == "/jobs" or "?" in href:
            continue
        title = link.get_text(strip=True)
        if not title or href in seen_hrefs:
            continue
        seen_hrefs.add(href)

        job_url = WFH_BASE_URL + href

        # Walk up to find the card containing categories and company
        card = link.find_parent(["article", "div", "li", "section"])

        categories: list[str] = []
        company = ""
        if card:
            categories = [
                a.get_text(strip=True).lower()
                for a in card.find_all("a", href=True)
                if "/jobs/category/" in a["href"]
            ]
            company = _extract_company(card.get_text(separator=" "))

        results.append((title, job_url, categories, company))

    # "Older Posts" pagination link
    next_url: str | None = None
    for a in soup.find_all("a", href=True):
        text = a.get_text(strip=True).lower()
        href = a["href"]
        if ("older" in text or ("next" in text and "page" not in text)) and (
            "offset=" in href or "paged=" in href
        ):
            next_url = href if href.startswith("http") else WFH_BASE_URL + href
            break

    return results, next_url


def _extract_company(text: str) -> str:
    """Pull company name from card text following 'Employer:', 'Recruiter:', or 'Company:'."""
    for marker in ("Employer:", "Recruiter:", "Company:"):
        idx = text.find(marker)
        if idx != -1:
            after = text[idx + len(marker):].strip()
            return after.split("\n")[0].strip()[:120]
    return ""


def _fetch_content(url: str) -> str:
    """Fetch and return plain text content from a job detail page."""
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=REQUEST_TIMEOUT_SECS)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"Failed to fetch content from {url}: {e}")
        return ""

    soup = BeautifulSoup(resp.text, "html.parser")

    content_el = (
        soup.find(class_=re.compile(r"entry.content|job.description|post.content", re.I))
        or soup.find("article")
        or soup.find("main")
    )

    text = (
        content_el.get_text(separator="\n", strip=True)
        if content_el
        else soup.get_text(separator="\n", strip=True)
    )
    return text[:JOB_CONTENT_MAX_CHARS]
