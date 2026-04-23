# sources/scraper.py
# Generic Playwright-based scraper for companies not on Greenhouse.
# Stub only — implement per-company when needed.

# To use: pip install playwright && playwright install chromium


def fetch_jobs(url: str, location_filter: str) -> list[dict]:
    """
    Scrape jobs from a careers page using Playwright.
    Currently a stub — implement per company as needed.

    Args:
        url:             Company careers page URL
        location_filter: String to match against job location

    Returns:
        List of job dicts with keys: title, url, location, department, content
    """
    raise NotImplementedError(
        f"Generic scraper not yet implemented for {url}. "
        "Add a company-specific scraping function here."
    )
