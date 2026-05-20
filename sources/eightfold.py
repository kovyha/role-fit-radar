# sources/eightfold.py
# Fetches jobs from an Eightfold AI job board.
# Standard path (most boards): direct API calls via requests.
# Playwright path (use_playwright=True): navigates the careers page first to
# establish session cookies — required for boards with PCSX auth (e.g. Citi).

import html as html_lib
import asyncio
import requests
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from config import (
    JOB_CONTENT_MAX_CHARS, REQUEST_TIMEOUT_SECS, PLAYWRIGHT_PAGE_TIMEOUT_MS,
    TITLE_TERMS, TITLE_BLOCKLIST,
)
from sources.filters import passes_local_filter

_USER_AGENT = (
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
    'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
)


def fetch_jobs(
    domain: str,
    location_filter: str,
    seen_urls: set | None = None,
    *,
    allowlist: frozenset = TITLE_TERMS,
    blocklist: frozenset = TITLE_BLOCKLIST,
    use_playwright: bool = False,
) -> list[dict]:
    """
    Fetch new jobs from an Eightfold board, filtered by location.

    Args:
        domain:          Eightfold domain e.g. "mlp.com"
        location_filter: Location string e.g. "London"
        seen_urls:       URLs already recorded; descriptions skipped for these
        use_playwright:  True for boards requiring browser session (e.g. Citi)

    Returns:
        List of job dicts with keys: title, url, location, department, content
    """
    if seen_urls is None:
        seen_urls = set()

    if use_playwright:
        return asyncio.run(_fetch_jobs_playwright(domain, location_filter, seen_urls, allowlist, blocklist))

    subdomain = domain.split(".")[0]
    base_url = f"https://{subdomain}.eightfold.ai/api/apply/v2/jobs"

    stubs = _fetch_stubs(base_url, domain, location_filter)

    results = []
    for stub in stubs:
        if stub["url"] in seen_urls:
            continue
        if not passes_local_filter(stub["title"], allowlist, blocklist):
            continue
        content = _fetch_content(base_url, domain, stub.pop("id"))
        stub["content"] = content
        results.append(stub)

    return results


# ── Shared parsers (used by both requests and Playwright paths) ────────────────

def _parse_stubs(data: dict) -> tuple[list[dict], int]:
    """Parse Eightfold list API response into stub dicts and total count."""
    positions = data.get("positions", [])
    stubs = [{
        "id":         job["id"],
        "title":      job.get("name", ""),
        "url":        job.get("canonicalPositionUrl", ""),
        "location":   job.get("location", ""),
        "department": job.get("department", ""),
    } for job in positions]
    return stubs, data.get("count", 0)


def _parse_description(detail: dict) -> str:
    """Extract and clean job description from Eightfold detail API response."""
    raw = detail.get("job_description", "") or ""
    return _strip_html(raw)[:JOB_CONTENT_MAX_CHARS]


# ── Requests path ──────────────────────────────────────────────────────────────

def _fetch_stubs(base_url: str, domain: str, location_filter: str) -> list[dict]:
    """Paginate the Eightfold list endpoint and return all matching job stubs."""
    stubs = []
    limit = 100
    start = 0

    while True:
        params = {"domain": domain, "location": location_filter, "limit": limit, "start": start}
        try:
            response = requests.get(base_url, params=params, timeout=REQUEST_TIMEOUT_SECS)
            response.raise_for_status()
        except requests.RequestException as e:
            print(f"[eightfold] Failed to fetch stubs (start={start}): {e}")
            break

        page_stubs, total = _parse_stubs(response.json())
        stubs.extend(page_stubs)
        start += len(page_stubs)
        if start >= total or not page_stubs:
            break

    return stubs


def _fetch_content(detail_base: str, domain: str, job_id: int) -> str:
    """Fetch and clean the description for a single Eightfold job."""
    url = f"{detail_base}/{job_id}"
    try:
        response = requests.get(url, params={"domain": domain}, timeout=REQUEST_TIMEOUT_SECS)
        response.raise_for_status()
        return _parse_description(response.json())
    except requests.RequestException as e:
        print(f"[eightfold] Failed to fetch content for job {job_id}: {e}")
        return ""


# ── Playwright path ────────────────────────────────────────────────────────────

async def _fetch_jobs_playwright(
    domain: str,
    location_filter: str,
    seen_urls: set,
    allowlist: frozenset,
    blocklist: frozenset,
) -> list[dict]:
    """Navigate the careers page to establish a PCSX session, then call the API."""
    subdomain = domain.split(".")[0]
    careers_url = f"https://{subdomain}.eightfold.ai/careers"
    api_base = f"https://{subdomain}.eightfold.ai/api/apply/v2/jobs"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=_USER_AGENT)
        page = await context.new_page()

        try:
            await page.goto(careers_url, wait_until="networkidle", timeout=PLAYWRIGHT_PAGE_TIMEOUT_MS)
        except Exception as e:
            print(f"[eightfold] Playwright: failed to load {careers_url}: {e}")
            await browser.close()
            return []

        # Phase 1: paginate stubs using the authenticated browser session
        stubs = []
        limit = 100
        start = 0
        while True:
            try:
                resp = await context.request.get(api_base, params={
                    "domain": domain, "location": location_filter,
                    "limit": limit, "start": start,
                })
                if not resp.ok:
                    print(f"[eightfold] Playwright: API returned {resp.status} for {domain}")
                    break
                page_stubs, total = _parse_stubs(await resp.json())
            except Exception as e:
                print(f"[eightfold] Playwright: stub fetch failed for {domain}: {e}")
                break
            stubs.extend(page_stubs)
            start += len(page_stubs)
            if start >= total or not page_stubs:
                break

        # Phase 2: filter, then fetch descriptions for new jobs only
        results = []
        for stub in stubs:
            if stub["url"] in seen_urls:
                continue
            if not passes_local_filter(stub["title"], allowlist, blocklist):
                continue
            job_id = stub.pop("id")
            try:
                resp = await context.request.get(f"{api_base}/{job_id}", params={"domain": domain})
                stub["content"] = _parse_description(await resp.json()) if resp.ok else ""
            except Exception as e:
                print(f"[eightfold] Playwright: content fetch failed for job {job_id}: {e}")
                stub["content"] = ""
            results.append(stub)

        await browser.close()

    return results


# ── Utilities ──────────────────────────────────────────────────────────────────

def _strip_html(html: str) -> str:
    """Strip HTML tags and return clean text, handling entity-encoded HTML."""
    if not html:
        return ""
    return BeautifulSoup(html_lib.unescape(html), "html.parser").get_text(separator="\n", strip=True)
