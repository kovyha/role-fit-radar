# sources/efinancialcareers.py
# Scrapes eFinancialCareers for jobs matching specified keywords using Playwright.
# Two-phase fetch: (1) collect all job stubs cheaply, (2) fetch descriptions only
# for the delta (URLs not already in the Google Sheet).

import logging
from urllib.parse import quote

from playwright.async_api import async_playwright
from config import (
    EFINANCIAL_SENIORITY_LEVELS, EFINANCIAL_PAGE_SIZE,
    EFINANCIAL_LOCATION_SLUG, EFINANCIAL_LOCATION_LAT, EFINANCIAL_LOCATION_LNG,
    JOB_CONTENT_MAX_CHARS,
    PLAYWRIGHT_PAGE_TIMEOUT_MS, PLAYWRIGHT_SELECTOR_TIMEOUT_MS, PLAYWRIGHT_FALLBACK_WAIT_MS,
    TITLE_TERMS, TITLE_BLOCKLIST,
)
from sources.filters import passes_local_filter, explain_filter_result, log_filter_debug

logger = logging.getLogger(__name__.rsplit(".", 1)[-1])

EFINANCIAL_BASE = "https://www.efinancialcareers.co.uk/jobs"
USER_AGENT = (
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
    'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
)

def _build_search_url(keyword: str, location_filter: str, page: int = 1) -> str:
    keyword_slug = keyword.lower().replace(' ', '-')
    seniority_params = "".join(f"&filters.seniority={level}" for level in EFINANCIAL_SENIORITY_LEVELS)
    return (
        f"{EFINANCIAL_BASE}/{keyword_slug}/in-{EFINANCIAL_LOCATION_SLUG}%2C-uk"
        f"?q={quote(keyword)}&location={quote(location_filter + ', UK')}"
        f"&latitude={EFINANCIAL_LOCATION_LAT}&longitude={EFINANCIAL_LOCATION_LNG}&countryCode=GB"
        f"&locationPrecision=City&radius=40&radiusUnit=km&pageSize={EFINANCIAL_PAGE_SIZE}"
        f"&currencyCode=GBP&language=en&includeUnspecifiedSalary=true"
        f"&page={page}{seniority_params}"
    )


def fetch_jobs(
    location_filter: str,
    seen_urls: set = None,
    *,
    search_terms: frozenset = TITLE_TERMS,
    allowlist: frozenset = frozenset(),
    blocklist: frozenset = TITLE_BLOCKLIST,
) -> list[dict]:
    """
    Fetch jobs from eFinancialCareers for each search term, filtered by location.
    Pass seen_urls (from Google Sheet) to skip description fetches for known jobs.

    Returns:
        List of job dicts: {title, url, location, company, department, content}
    """
    try:
        import asyncio
        return asyncio.run(_fetch_jobs_async(location_filter, seen_urls or set(), search_terms, allowlist, blocklist))
    except Exception as e:
        logger.error(f"Error fetching jobs: {e}")
        return []


async def _fetch_jobs_async(
    location_filter: str,
    sheet_seen_urls: set,
    search_terms: frozenset = TITLE_TERMS,
    allowlist: frozenset = frozenset(),
    blocklist: frozenset = TITLE_BLOCKLIST,
) -> list[dict]:
    """
    Async helper — two phases:
      Phase 1: collect all job stubs across every search term (title, url, company, location)
      Phase 2: fetch descriptions only for URLs not already in the Google Sheet
    """
    logger.info(f"Searching {len(search_terms)} term(s): {', '.join(sorted(search_terms))}")

    stubs = []
    seen_in_run: set[str] = set()
    first_url_per_keyword: list[str] = []
    is_debug = logger.isEnabledFor(logging.DEBUG)

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)

            # ── Phase 1: collect stubs (paginated) ───────────────────────────
            for keyword in search_terms:
                page_num = 1
                keyword_first_url = None
                keyword_total_cards = 0
                keyword_stubs_before = len(stubs)
                kw_fetched: list[str] = []
                kw_blocked: list[tuple[str, str]] = []
                kw_kept: list[str] = []
                while True:
                    url = _build_search_url(keyword, location_filter, page=page_num)
                    try:
                        context = await browser.new_context()
                        page = await context.new_page()
                        await page.set_extra_http_headers({"User-Agent": USER_AGENT})
                        await page.goto(url, wait_until='domcontentloaded', timeout=PLAYWRIGHT_PAGE_TIMEOUT_MS)
                        try:
                            await page.wait_for_selector('[data-test="job-card"], .job-card, efc-job-card', timeout=PLAYWRIGHT_SELECTOR_TIMEOUT_MS)
                        except Exception:
                            await page.wait_for_timeout(PLAYWRIGHT_FALLBACK_WAIT_MS)

                        job_elements = await page.query_selector_all('[data-test="job-card"], .job-card, efc-job-card')

                        if page_num == 1 and job_elements:
                            keyword_first_url = await job_elements[0].evaluate("el => el.querySelector('a.job-title')?.href || ''")
                            first_url_per_keyword.append(keyword_first_url)

                        for elem in job_elements:
                            try:
                                title    = await elem.evaluate("el => el.querySelector('a.job-title')?.title?.trim() || el.querySelector('h3, h2')?.textContent?.trim() || ''")
                                job_url  = await elem.evaluate("el => el.querySelector('a.job-title')?.href || ''")
                                company  = await elem.evaluate('el => el.querySelector(".font-body-3.company")?.textContent?.trim() || "Unknown"')
                                location = await elem.evaluate('el => el.querySelector(".font-helper-text.location span.dot-divider")?.textContent?.trim() || ""')

                                if not job_url or job_url in seen_in_run or job_url in sheet_seen_urls:
                                    continue
                                if is_debug:
                                    kw_fetched.append(title or "Unknown Role")
                                if not passes_local_filter(title, allowlist, blocklist):
                                    if is_debug:
                                        kw_blocked.append((title or "Unknown Role", explain_filter_result(title, allowlist, blocklist)))
                                    continue
                                if is_debug:
                                    kw_kept.append(title or "Unknown Role")
                                seen_in_run.add(job_url)
                                stubs.append({
                                    "title":      title or "Unknown Role",
                                    "url":        job_url,
                                    "company":    company,
                                    "location":   location,
                                    "department": "",
                                    "content":    "",
                                })
                            except Exception as e:
                                logger.warning(f"Error extracting job card: {e}")
                                continue

                        keyword_total_cards += len(job_elements)
                        await page.close()
                        await context.close()

                        # Stop paginating when eFC returns a partial page (last page reached)
                        if len(job_elements) < EFINANCIAL_PAGE_SIZE:
                            break
                        page_num += 1

                    except Exception as e:
                        logger.error(f"Error processing keyword '{keyword}' page {page_num}: {e}")
                        try:
                            await page.close()
                            await context.close()
                        except Exception:
                            pass
                        break

                keyword_kept = len(stubs) - keyword_stubs_before
                logger.info(f"'{keyword}': {keyword_total_cards} cards fetched ({page_num} page(s)), {keyword_kept} kept after filter")
                if is_debug:
                    log_filter_debug(logger, kw_fetched, kw_blocked, kw_kept)

            # Fallback detection — warn if eFC is returning a generic default list
            if len(first_url_per_keyword) >= 3:
                most_common = max(set(first_url_per_keyword), key=first_url_per_keyword.count)
                repeat_rate = first_url_per_keyword.count(most_common) / len(first_url_per_keyword)
                if repeat_rate > 0.5:
                    logger.warning(
                        f"{int(repeat_rate * 100)}% of keywords returned the same first result "
                        f"— eFC search URL format may be broken."
                    )

            # ── Phase 2: fetch descriptions for the delta only ────────────────
            logger.info(f"{len(stubs)} new job(s) to fetch descriptions for")
            for i, stub in enumerate(stubs, 1):
                logger.info(f"Fetching description {i}/{len(stubs)}: {stub['title']}")
                stub["content"] = await _fetch_job_description_async(browser, stub["url"])

            await browser.close()

    except Exception as e:
        logger.error(f"Playwright error: {e}")
        return []

    return stubs


async def _fetch_job_description_async(browser, job_url: str) -> str:
    """
    Fetch full job description from a single job page.
    """
    try:
        context = await browser.new_context()
        page = await context.new_page()
        await page.set_extra_http_headers({"User-Agent": USER_AGENT})

        await page.goto(job_url, wait_until='domcontentloaded', timeout=PLAYWRIGHT_PAGE_TIMEOUT_MS)

        try:
            await page.wait_for_selector('efc-job-description, .job-description', timeout=PLAYWRIGHT_SELECTOR_TIMEOUT_MS)
        except Exception:
            await page.wait_for_timeout(PLAYWRIGHT_FALLBACK_WAIT_MS)

        # .inner-content is the actual body inside efc-job-description
        description = await page.evaluate('''
            () => {
                const elem = document.querySelector('efc-job-description .inner-content') ||
                             document.querySelector('efc-job-description') ||
                             document.querySelector('.job-description');
                return elem ? elem.innerText : '';
            }
        ''')

        await page.close()
        await context.close()

        return ' '.join(description.split())[:JOB_CONTENT_MAX_CHARS]

    except Exception as e:
        logger.error(f"Could not fetch description for {job_url}: {e}")
        return ""
