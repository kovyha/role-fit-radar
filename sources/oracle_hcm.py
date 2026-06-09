# sources/oracle_hcm.py
# Fetches jobs from Oracle HCM Cloud public career sites.
# Requires a Playwright browser session — location filtering in the API is
# silently ignored without valid session cookies established by the SPA.

import html as html_lib
import asyncio
import logging
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from config import (
    JOB_CONTENT_MAX_CHARS, PLAYWRIGHT_PAGE_TIMEOUT_MS,
    TITLE_TERMS, TITLE_BLOCKLIST,
)
from sources.filters import passes_local_filter, explain_filter_result, log_filter_debug

logger = logging.getLogger(__name__.rsplit(".", 1)[-1])

_USER_AGENT = (
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
    'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
)
_LIST_API   = "/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
_DETAIL_API = "/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails"


def fetch_jobs(
    host: str,
    site: str,
    location_filter: str,
    seen_urls: set | None = None,
    *,
    allowlist: frozenset = TITLE_TERMS,
    blocklist: frozenset = TITLE_BLOCKLIST,
) -> list[dict]:
    """
    Fetch new jobs from an Oracle HCM Cloud career site, filtered by location.

    Args:
        host:            Oracle HCM hostname e.g. "jpmc.fa.oraclecloud.com"
        site:            Site number e.g. "CX_1001"
        location_filter: City name e.g. "London"
        seen_urls:       URLs already recorded; descriptions skipped for these

    Returns:
        List of job dicts with keys: title, url, location, department, content
    """
    return asyncio.run(_fetch_jobs_async(host, site, location_filter, seen_urls or set(), allowlist, blocklist))


async def _fetch_jobs_async(
    host: str,
    site: str,
    location_filter: str,
    seen_urls: set,
    allowlist: frozenset,
    blocklist: frozenset,
) -> list[dict]:
    careers_url = f"https://{host}/hcmUI/CandidateExperience/en/sites/{site}/jobs"
    list_url    = f"https://{host}{_LIST_API}"
    detail_url  = f"https://{host}{_DETAIL_API}"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=_USER_AGENT)
        page    = await context.new_page()

        try:
            await page.goto(careers_url, wait_until="load", timeout=PLAYWRIGHT_PAGE_TIMEOUT_MS)
        except Exception as e:
            logger.error(f"Failed to load {careers_url}: {e}")
            await browser.close()
            return []

        # Phase 0: discover location ID from facets (same API the SPA calls on load)
        location_id = await _discover_location_id(context, list_url, site, location_filter)
        if not location_id:
            logger.warning(f"No location found for '{location_filter}'")
            await browser.close()
            return []
        logger.info(f"'{location_filter}' → location ID {location_id}")

        # Phase 1: paginate stubs
        stubs  = []
        limit  = 100
        offset = 0
        while True:
            finder = (
                f"findReqs;siteNumber={site},facetsList=NONE,"
                f"limit={limit},offset={offset},"
                f"locationId={location_id},sortBy=POSTING_DATES_DESC"
            )
            try:
                resp = await context.request.get(list_url, params={
                    "onlyData": "true",
                    "expand":   "requisitionList.workLocation",
                    "finder":   finder,
                }, timeout=PLAYWRIGHT_PAGE_TIMEOUT_MS)
                if not resp.ok:
                    logger.error(f"List API returned {resp.status}")
                    break
                data = await resp.json()
            except Exception as e:
                logger.error(f"Stub fetch failed (offset={offset}): {e}")
                break

            first     = (data.get("items") or [{}])[0]
            page_jobs = first.get("requisitionList", [])
            total     = first.get("TotalJobsCount", 0)

            for job in page_jobs:
                req_id = job.get("Id", "")
                stubs.append({
                    "id":         req_id,
                    "title":      job.get("Title", ""),
                    "url":        f"https://{host}/hcmUI/CandidateExperience/en/sites/{site}/job/{req_id}",
                    "location":   job.get("PrimaryLocation", ""),
                    "department": job.get("Department", ""),
                })

            offset += len(page_jobs)
            if offset >= total or not page_jobs:
                break

        logger.info(f"{len(stubs)} stubs for '{location_filter}'")

        # Phase 2: filter then fetch descriptions for new jobs only
        debug_fetched: list[str] = []
        debug_blocked: list[tuple[str, str]] = []
        debug_kept: list[str] = []
        seen_count = 0

        results = []
        for stub in stubs:
            if stub["url"] in seen_urls:
                seen_count += 1
                continue
            title = stub["title"]
            debug_fetched.append(title)
            if not passes_local_filter(title, allowlist, blocklist):
                debug_blocked.append((title, explain_filter_result(title, allowlist, blocklist)))
                continue
            debug_kept.append(title)
            req_id = stub.pop("id")
            try:
                resp = await context.request.get(detail_url, params={
                    "expand":    "all",
                    "onlyData":  "true",
                    "finder":    f'ById;Id="{req_id}",siteNumber={site}',
                }, timeout=PLAYWRIGHT_PAGE_TIMEOUT_MS)
                stub["content"] = _extract_content(await resp.json()) if resp.ok else ""
            except Exception as e:
                logger.error(f"Content fetch failed for {req_id}: {e}")
                stub["content"] = ""
            results.append(stub)

        log_filter_debug(logger, debug_fetched, debug_blocked, debug_kept,
                         total=seen_count + len(debug_fetched), seen=seen_count, new=len(results))
        await browser.close()

    return results


async def _discover_location_id(context, list_url: str, site: str, location_filter: str) -> str | None:
    """
    Call the list API with facetsList=LOCATIONS to retrieve the locationsFacet,
    then pick the ID whose first component matches location_filter (case-insensitive).
    Fewest components wins (city-level parent covers all child sub-locations).
    """
    finder = f"findReqs;siteNumber={site},facetsList=LOCATIONS,limit=1"
    try:
        resp = await context.request.get(list_url, params={"onlyData": "true", "finder": finder}, timeout=PLAYWRIGHT_PAGE_TIMEOUT_MS)
        if not resp.ok:
            return None
        data = await resp.json()
    except Exception:
        return None

    needle     = location_filter.lower()
    candidates = []
    for item in data.get("items", []):
        for loc in item.get("locationsFacet", []):
            name  = loc.get("Name", "") or ""
            parts = [p.strip() for p in name.split(",")]
            if parts[0].lower() == needle:
                candidates.append((len(parts), str(loc["Id"]), name))

    if not candidates:
        return None
    candidates.sort()   # fewest parts first → most general city-level parent
    chosen = candidates[0]
    logger.info(f"Matched facet: '{chosen[2]}' (ID {chosen[1]})")
    return chosen[1]


def _extract_content(data: dict) -> str:
    """Combine description fields from recruitingCEJobRequisitionDetails."""
    items = data.get("items", [])
    if not items:
        return ""
    item  = items[0]
    parts = [
        item.get("ExternalDescriptionStr", "") or "",
        item.get("ExternalResponsibilitiesStr", "") or "",
        item.get("ExternalQualificationsStr", "") or "",
    ]
    combined = "\n".join(p for p in parts if p)
    return _strip_html(combined)[:JOB_CONTENT_MAX_CHARS]


def _strip_html(html: str) -> str:
    if not html:
        return ""
    return BeautifulSoup(html_lib.unescape(html), "html.parser").get_text(separator="\n", strip=True)
