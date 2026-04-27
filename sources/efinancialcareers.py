# sources/efinancialcareers.py
# Scrapes eFinancialCareers for jobs matching specified keywords using Playwright.
# Searches for keyword-filtered jobs in a location, then fetches full descriptions.

from urllib.parse import quote

from playwright.async_api import async_playwright
from config import (
    EFINANCIAL_KEYWORDS, EFINANCIAL_TITLE_TERMS,
    JOB_CONTENT_MAX_CHARS,
    PLAYWRIGHT_PAGE_TIMEOUT_MS, PLAYWRIGHT_SELECTOR_TIMEOUT_MS, PLAYWRIGHT_FALLBACK_WAIT_MS,
)


EFINANCIAL_BASE = "https://www.efinancialcareers.co.uk/jobs"
USER_AGENT = (
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
    'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
)


def _is_relevant_title(title: str) -> bool:
    t = title.lower()
    return any(term in t for term in EFINANCIAL_TITLE_TERMS)


def fetch_jobs(location_filter: str) -> list[dict]:
    """
    Fetch jobs from eFinancialCareers for each keyword, filtered by location.

    Args:
        location_filter: Location string e.g. "London"

    Returns:
        List of job dicts: {title, url, location, company, department, content}
    """
    try:
        import asyncio
        return asyncio.run(_fetch_jobs_async(location_filter))
    except Exception as e:
        print(f"[efinancialcareers] Error fetching jobs: {e}")
        return []


async def _fetch_jobs_async(location_filter: str) -> list[dict]:
    """
    Async helper to fetch jobs using Playwright.
    """
    jobs = []
    seen_urls = set()

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)

            for keyword in EFINANCIAL_KEYWORDS:
                url = f"{EFINANCIAL_BASE}?keyword={quote(keyword)}&location={quote(location_filter)}&countryCode=GB"

                try:
                    context = await browser.new_context()
                    page = await context.new_page()
                    await page.set_extra_http_headers({"User-Agent": USER_AGENT})

                    await page.goto(url, wait_until='domcontentloaded', timeout=PLAYWRIGHT_PAGE_TIMEOUT_MS)

                    # Wait for job cards to appear (common selectors for Angular SPAs)
                    try:
                        await page.wait_for_selector('[data-test="job-card"], .job-card, efc-job-card', timeout=PLAYWRIGHT_SELECTOR_TIMEOUT_MS)
                    except Exception:
                        await page.wait_for_timeout(PLAYWRIGHT_FALLBACK_WAIT_MS)

                    # Extract job cards
                    job_elements = await page.query_selector_all('[data-test="job-card"], .job-card, efc-job-card')

                    for elem in job_elements:
                        try:
                            title   = await elem.evaluate("el => el.querySelector('a.job-title')?.title?.trim() || el.querySelector('h3, h2')?.textContent?.trim() || ''")
                            job_url = await elem.evaluate("el => el.querySelector('a.job-title')?.href || ''")
                            company = await elem.evaluate('el => el.querySelector(".font-body-3.company")?.textContent?.trim() || "Unknown"')
                            location = await elem.evaluate('el => el.querySelector(".font-helper-text.location span.dot-divider")?.textContent?.trim() || ""')

                            if job_url and job_url not in seen_urls and _is_relevant_title(title):
                                seen_urls.add(job_url)

                                # Fetch full description
                                content = await _fetch_job_description_async(browser, job_url)

                                jobs.append({
                                    "title": title or "Unknown Role",
                                    "url": job_url,
                                    "company": company,
                                    "location": location,
                                    "department": "",
                                    "content": content
                                })
                        except Exception as e:
                            print(f"[efinancialcareers] Error extracting job card: {e}")
                            continue

                    await page.close()
                    await context.close()

                except Exception as e:
                    print(f"[efinancialcareers] Error processing keyword '{keyword}': {e}")
                    try:
                        await page.close()
                        await context.close()
                    except Exception:
                        pass
                    continue

            await browser.close()

    except Exception as e:
        print(f"[efinancialcareers] Playwright error: {e}")
        return []

    return jobs


async def _fetch_job_description_async(browser, job_url: str) -> str:
    """
    Fetch full job description from a single job page.
    """
    try:
        context = await browser.new_context()
        page = await context.new_page()
        await page.set_extra_http_headers({"User-Agent": USER_AGENT})

        await page.goto(job_url, wait_until='domcontentloaded', timeout=PLAYWRIGHT_PAGE_TIMEOUT_MS)

        # Wait for job description to load
        try:
            await page.wait_for_selector('efc-job-description, .job-description', timeout=PLAYWRIGHT_SELECTOR_TIMEOUT_MS)
        except Exception:
            await page.wait_for_timeout(PLAYWRIGHT_FALLBACK_WAIT_MS)

        # Extract description text — .inner-content is the actual body inside efc-job-description
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

        description = ' '.join(description.split())[:JOB_CONTENT_MAX_CHARS]
        return description

    except Exception as e:
        print(f"[efinancialcareers] Could not fetch description for {job_url}: {e}")
        return ""
