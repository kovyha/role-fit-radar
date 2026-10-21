# scripts/reassess_failed.py
# Re-assess Jobs-tab rows whose assessment failed ("Manual review needed", fit score 0).
#
# For each failed row: check the posting is still open, re-fetch the job description
# from its URL, run assess_fit, and overwrite the assessment columns (Fit Score →
# Reasoning) in place. Closed postings are marked "Closed" without an API call. Rows
# whose site blocks us, or whose description still can't be fetched, are left
# untouched and listed at the end.
#
# Safe to re-run: only rows still marked "Manual review needed" are picked up.
#
# Usage:
#   python -m scripts.reassess_failed            # re-assess and update the sheet
#   python -m scripts.reassess_failed --dry-run  # fetch + assess, print, no sheet writes

import argparse
import asyncio
import logging
import re
from datetime import date

from playwright.async_api import async_playwright

from assessor import assess_fit
from config import JOBS_TAB, JOB_CONTENT_MAX_CHARS, PLAYWRIGHT_PAGE_TIMEOUT_MS, PLAYWRIGHT_FALLBACK_WAIT_MS
from sheets import _get_sheet, get_profile
from sources import efinancialcareers, gmail_linkedin, greenhouse

logger = logging.getLogger("reassess")

FAILED_RECOMMENDATION = "Manual review needed"
CLOSED_RECOMMENDATION = "Closed"

# Page text that means the posting has been taken down (Oracle HCM, LinkedIn, generic boards)
CLOSED_MARKERS = (
    "job is no longer available",
    "no longer accepting applications",
    "job has expired",
    "position has been filled",
)

# Only "not found"/"gone" prove the posting is closed. Any other HTTP error (eFC returns
# 403 when it blocks a client) leaves the row untouched for a later re-run.
CLOSED_HTTP_STATUSES = frozenset({404, 410})
POSTING_OPEN, POSTING_CLOSED, POSTING_BLOCKED = "open", "closed", "blocked"

# 0-based column indexes into a Jobs-tab row (see sheets.append_jobs)
COL_COMPANY, COL_SOURCE, COL_TITLE, COL_LOCATION, COL_DEPARTMENT, COL_URL = 1, 2, 3, 4, 5, 6
COL_RECOMMENDATION = 11
ASSESSMENT_RANGE = "I{row}:M{row}"  # Fit Score, Key Strengths, Key Gaps, Recommendation, Reasoning

# Descriptions shorter than this are treated as a failed fetch (empty shell / sign-in wall)
MIN_CONTENT_CHARS = 200
FETCH_ATTEMPTS = 2

_GREENHOUSE_URL_RE = re.compile(r"greenhouse\.io/([^/]+)/jobs/(\d+)")


def find_failed_rows(rows: list[list[str]]) -> list[tuple[int, list[str]]]:
    """Return (sheet_row_number, row) for every failed assessment. Row 1 is the header."""
    return [
        (i, row)
        for i, row in enumerate(rows[1:], start=2)
        if len(row) > COL_RECOMMENDATION and row[COL_RECOMMENDATION] == FAILED_RECOMMENDATION
    ]


def classify_posting(status: int | None, text: str) -> str:
    """POSTING_OPEN, POSTING_CLOSED or POSTING_BLOCKED from the page's HTTP status and body text."""
    if status in CLOSED_HTTP_STATUSES:
        return POSTING_CLOSED
    if status is not None and status >= 400:
        # 403/429/5xx mean we're blocked or the site is down — says nothing about the posting
        return POSTING_BLOCKED
    text = text.lower()
    return POSTING_CLOSED if any(marker in text for marker in CLOSED_MARKERS) else POSTING_OPEN


async def _check_posting_async(url: str) -> tuple[str, int | None]:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            response = await page.goto(url, wait_until="load", timeout=PLAYWRIGHT_PAGE_TIMEOUT_MS)
            status = response.status if response is not None else None
            text = ""
            if status is None or status < 400:
                await page.wait_for_timeout(PLAYWRIGHT_FALLBACK_WAIT_MS)  # let SPAs render
                text = await page.evaluate("() => document.body ? document.body.innerText : ''")
        finally:
            await browser.close()
    return classify_posting(status, text), status


def check_posting(url: str) -> tuple[str, int | None]:
    try:
        return asyncio.run(_check_posting_async(url))
    except Exception as e:
        logger.error(f"Posting check failed for {url}: {e}")
        return POSTING_OPEN, None  # fall through to the normal fetch; an empty fetch is still caught later


async def _fetch_generic_async(url: str) -> str:
    """Load the page and prefer JSON-LD JobPosting.description, falling back to page text."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.goto(url, wait_until="load", timeout=PLAYWRIGHT_PAGE_TIMEOUT_MS)
            await page.wait_for_timeout(PLAYWRIGHT_FALLBACK_WAIT_MS)  # let SPAs render
            text = await page.evaluate('''
                () => {
                    for (const s of document.querySelectorAll('script[type="application/ld+json"]')) {
                        try {
                            const d = JSON.parse(s.textContent);
                            if (d['@type'] === 'JobPosting' && d.description) {
                                const tmp = document.createElement('div');
                                tmp.innerHTML = d.description;
                                return tmp.innerText;
                            }
                        } catch (e) {}
                    }
                    return document.body ? document.body.innerText : '';
                }
            ''')
        finally:
            await browser.close()
    return " ".join(text.split())[:JOB_CONTENT_MAX_CHARS]


async def _fetch_efc_async(url: str) -> str:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            return await efinancialcareers._fetch_job_description_async(browser, url)
        finally:
            await browser.close()


def fetch_content(source: str, url: str) -> str:
    """Re-fetch a job description using the source's own fetcher where one can be reused."""
    try:
        if source == "linkedin_email":
            return gmail_linkedin._fetch_job_description(url)["content"]
        if source == "efinancialcareers":
            return asyncio.run(_fetch_efc_async(url))
        if source == "greenhouse":
            m = _GREENHOUSE_URL_RE.search(url)
            if m:
                return greenhouse._fetch_content(m.group(1), int(m.group(2)))
        return asyncio.run(_fetch_generic_async(url))
    except Exception as e:
        logger.error(f"Fetch failed for {url}: {e}")
        return ""


def fetch_with_retry(source: str, url: str) -> str:
    for attempt in range(1, FETCH_ATTEMPTS + 1):
        content = fetch_content(source, url)
        if len(content) >= MIN_CONTENT_CHARS:
            return content
        logger.warning(f"Empty/short description (attempt {attempt}/{FETCH_ATTEMPTS}): {url}")
    return ""


def reassess(worksheet, profile: str, dry_run: bool = False) -> dict:
    """Re-assess every failed row. Returns lists of (label, detail) keyed by
    "fixed", "closed", "blocked", "still_failed" and "unfetchable"."""
    failed = find_failed_rows(worksheet.get_all_values())
    logger.info(f"{len(failed)} failed assessment row(s) found")

    outcome = {"fixed": [], "closed": [], "blocked": [], "still_failed": [], "unfetchable": []}
    for n, (row_num, row) in enumerate(failed, 1):
        title, url, source = row[COL_TITLE], row[COL_URL], row[COL_SOURCE]
        label = f"row {row_num}: {title} ({row[COL_COMPANY]}, {source})"
        logger.info(f"[{n}/{len(failed)}] {label}")

        state, status = check_posting(url)
        if state == POSTING_BLOCKED:
            logger.warning(f"  → blocked (HTTP {status}); row left untouched")
            outcome["blocked"].append((label, f"HTTP {status}"))
            continue
        if state == POSTING_CLOSED:
            logger.info("  → posting closed")
            if not dry_run:
                values = [["", "", "", CLOSED_RECOMMENDATION,
                           f"Posting closed when re-checked on {date.today().isoformat()}; not assessed"]]
                worksheet.update(values=values, range_name=ASSESSMENT_RANGE.format(row=row_num), value_input_option="RAW")
            outcome["closed"].append((label, url))
            continue

        content = fetch_with_retry(source, url)
        if not content:
            outcome["unfetchable"].append((label, url))
            continue

        job = {
            "title": title,
            "department": row[COL_DEPARTMENT],
            "location": row[COL_LOCATION],
            "url": url,
            "content": content,
        }
        result = assess_fit(job, profile)
        if result.get("assessment_failed"):
            outcome["still_failed"].append((label, result.get("reasoning", "")))
            continue

        values = [[
            result.get("fit_score", ""),
            result.get("key_strengths", ""),
            result.get("key_gaps", ""),
            result.get("recommendation", ""),
            result.get("reasoning", ""),
        ]]
        logger.info(f"  → {result.get('fit_score')}/10 {result.get('recommendation')}")
        if not dry_run:
            worksheet.update(values=values, range_name=ASSESSMENT_RANGE.format(row=row_num), value_input_option="RAW")
        outcome["fixed"].append((label, f"{result.get('fit_score')}/10 {result.get('recommendation')}"))

    return outcome


def _print_summary(outcome: dict, dry_run: bool) -> None:
    verb = "Would update" if dry_run else "Updated"
    print(f"\n{verb} {len(outcome['fixed'])} row(s).")
    for label, score in outcome["fixed"]:
        print(f"  ✓ {score:14} {label}")
    if outcome["closed"]:
        mark = "would be marked" if dry_run else "marked"
        print(f"\nPosting closed — {len(outcome['closed'])} row(s) {mark} '{CLOSED_RECOMMENDATION}':")
        for label, _ in outcome["closed"]:
            print(f"  – {label}")
    if outcome["blocked"]:
        print(f"\nSite blocked the request — {len(outcome['blocked'])} row(s) left untouched; re-run later:")
        for label, detail in outcome["blocked"]:
            print(f"  ✗ {detail:9} {label}")
    if outcome["unfetchable"]:
        print(f"\nCould not fetch description — {len(outcome['unfetchable'])} row(s) left for manual review:")
        for label, url in outcome["unfetchable"]:
            print(f"  ✗ {label}\n      {url}")
    if outcome["still_failed"]:
        print(f"\nAssessment failed again — {len(outcome['still_failed'])} row(s):")
        for label, err in outcome["still_failed"]:
            print(f"  ✗ {label}\n      {err}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Re-assess Jobs-tab rows marked 'Manual review needed'")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and assess but don't write to the sheet")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s", datefmt="%H:%M:%S")

    profile = get_profile()
    if not profile:
        raise SystemExit("Profile tab is empty — aborting")

    worksheet = _get_sheet().worksheet(JOBS_TAB)
    outcome = reassess(worksheet, profile, dry_run=args.dry_run)
    _print_summary(outcome, args.dry_run)


if __name__ == "__main__":
    main()
