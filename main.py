# main.py
# Orchestrator — two modes:
#
# Scan mode (default):
#   1. Load seen URLs from Google Sheets (deduplication)
#   2. Load user profile from Google Sheets
#   3. Fetch jobs from each configured company
#   4. Identify net new roles
#   5. Assess each new role against the profile via Claude API
#   6. Append results to Google Sheets
#   7. Send summary email if any new roles found
#
# File mode (--file <path_or_url>):
#   Assess a JD from a local file, directory, or URL against the user's profile.
#   Prints results to stdout. No Sheets write, no email.

import argparse
import logging
import signal
import time
from pathlib import Path

from config import COMPANIES, LOCATION_FILTER, JOB_CONTENT_MAX_CHARS
from sources.greenhouse import fetch_jobs as greenhouse_fetch
from sources.scraper import fetch_jobs as scraper_fetch
from sources.gmail_linkedin import fetch_jobs as linkedin_fetch
from sources.efinancialcareers import fetch_jobs as efinancial_fetch
from sources.ashby import fetch_jobs as ashby_fetch
from sources.eightfold import fetch_jobs as eightfold_fetch
from sources.workday import fetch_jobs as workday_fetch
from sources.higher import fetch_jobs as higher_fetch
from sources.oracle_hcm import fetch_jobs as oracle_hcm_fetch
from sheets import get_seen_urls, get_seen_title_company_keys, get_profile, append_jobs
from assessor import assess_fit
from gmail import send_summary

logging.basicConfig(
    format="%(asctime)s [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    level=logging.INFO,
)
logger = logging.getLogger("main")


class _ScanTimeout(BaseException):
    """Raised by the SIGTERM handler to trigger a partial flush when the runner times out."""
    def __init__(self, pending: list):
        self.pending = pending


def _write_and_notify(all_new_jobs: list[dict], pending_companies: list[dict]) -> None:
    """Write collected jobs to Sheets and send the summary email."""
    if pending_companies:
        logger.warning(
            f"Time limit reached — {len(pending_companies)} source(s) not scanned: "
            + ", ".join(c["name"] for c in pending_companies)
        )

    if all_new_jobs:
        sheet_urls = append_jobs(all_new_jobs)
        for job, sheet_url in zip(all_new_jobs, sheet_urls):
            job["sheet_url"] = sheet_url

    send_summary(all_new_jobs, pending_companies=pending_companies)

    if pending_companies:
        logger.info(f"Partial run — {len(all_new_jobs)} role(s) processed, {len(pending_companies)} source(s) pending")
    elif all_new_jobs:
        logger.info(f"Done — {len(all_new_jobs)} new role(s) processed and emailed")
    else:
        logger.info("Done — no new roles found, status email sent")


def main():
    run_start = time.monotonic()
    logger.info("=== Role Fit Radar — Starting scan ===")

    # Step 1 & 2: Load state from Google Sheets
    seen_urls = get_seen_urls()
    seen_title_keys = get_seen_title_company_keys()  # cross-platform dedup; grows within the run too
    profile = get_profile()
    logger.info(f"{len(seen_urls)} previously seen role(s) loaded")

    if not profile:
        logger.warning("Profile tab is empty — assessments will be low quality")

    all_new_jobs = []
    total_sources = len(COMPANIES)

    # _source_idx tracks which company is currently being fetched so the SIGTERM handler
    # can correctly mark it (and all subsequent companies) as pending.
    _source_idx = [0]

    def _on_sigterm(sig, frame):
        raise _ScanTimeout(list(COMPANIES[_source_idx[0]:]))

    signal.signal(signal.SIGTERM, _on_sigterm)

    try:
        # Step 3 & 4: Fetch and diff
        for i, company in enumerate(COMPANIES):
            _source_idx[0] = i  # mark as in-progress; SIGTERM will include this in pending
            logger.info(f"======= [{i+1}/{total_sources}] Scanning {company['name']} ({company['source']}) =======")

            allowlist = company.get("local_allowlist")
            blocklist = company.get("local_blocklist")

            t0 = time.monotonic()
            if company["source"] == "greenhouse":
                jobs = greenhouse_fetch(company["board"], LOCATION_FILTER, seen_urls=seen_urls, allowlist=allowlist, blocklist=blocklist)
            elif company["source"] == "scraper":
                jobs = scraper_fetch(company["url"], LOCATION_FILTER)
            elif company["source"] == "linkedin_email":
                jobs = linkedin_fetch(seen_urls=seen_urls)
            elif company["source"] == "efinancialcareers":
                jobs = efinancial_fetch(LOCATION_FILTER, seen_urls=seen_urls, search_terms=company.get("search_terms"), allowlist=allowlist, blocklist=blocklist)
            elif company["source"] == "ashby":
                jobs = ashby_fetch(company["org"], LOCATION_FILTER, seen_urls=seen_urls, allowlist=allowlist, blocklist=blocklist)
            elif company["source"] == "eightfold":
                jobs = eightfold_fetch(company["domain"], LOCATION_FILTER, seen_urls=seen_urls, allowlist=allowlist, blocklist=blocklist, use_playwright=company.get("use_playwright", False))
            elif company["source"] == "workday":
                jobs = workday_fetch(company["tenant"], company["board"], LOCATION_FILTER, seen_urls=seen_urls, wd=company.get("wd", "wd1"), allowlist=allowlist, blocklist=blocklist)
            elif company["source"] == "higher":
                jobs = higher_fetch(LOCATION_FILTER, seen_urls=seen_urls, allowlist=allowlist, blocklist=blocklist)
            elif company["source"] == "oracle_hcm":
                jobs = oracle_hcm_fetch(company["host"], company["site"], LOCATION_FILTER, seen_urls=seen_urls, allowlist=allowlist, blocklist=blocklist)
            else:
                logger.warning(f"Unknown source '{company['source']}' for {company['name']} — skipping")
                _source_idx[0] = i + 1
                continue

            elapsed = time.monotonic() - t0
            new_jobs = [j for j in jobs if j["url"] not in seen_urls]
            logger.info(f"{company['name']}: {len(jobs)} total, {len(new_jobs)} new ({elapsed:.1f}s)")

            # Step 5: Assess each new role
            assess_total = len(new_jobs)
            for assess_idx, job in enumerate(new_jobs, 1):
                if company["source"] in ("greenhouse", "ashby", "eightfold", "workday", "higher", "oracle_hcm"):
                    job["company"] = company["name"]
                title_key = f"{job.get('title', '').lower()}|{job.get('company', '').lower()}"
                if title_key in seen_title_keys:
                    original_url = seen_title_keys[title_key]
                    logger.info(f"Duplicate (cross-platform): {job['title']} @ {job.get('company', '')}")
                    job.update({"fit_score": "", "key_strengths": "", "key_gaps": "",
                                "recommendation": "Dup", "reasoning": f"Dup of {original_url}"})
                    job["source"] = company["source"]
                    all_new_jobs.append(job)
                    continue
                seen_title_keys[title_key] = job.get("url", "")
                logger.info(f"Assessing [{assess_idx}/{assess_total}]: {job['title']}")
                assessment = assess_fit(job, profile)
                job.update(assessment)
                job["source"] = company["source"]
                all_new_jobs.append(job)

            _source_idx[0] = i + 1  # mark as complete

    except _ScanTimeout as exc:
        # SIGTERM from GitHub Actions hitting its runner timeout.
        # Ignore any further SIGTERMs so the flush can complete uninterrupted.
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        _write_and_notify(all_new_jobs, exc.pending)
        logger.info(f"Total scan time: {time.monotonic() - run_start:.0f}s")
        return

    finally:
        signal.signal(signal.SIGTERM, signal.SIG_DFL)

    # Step 6 & 7: Normal completion — write and notify
    _write_and_notify(all_new_jobs, [])
    logger.info(f"Total scan time: {time.monotonic() - run_start:.0f}s")


def _print_assessment(name: str, result: dict) -> None:
    sep = "=" * 60
    print(f"\n{sep}")
    print(f"  {name}")
    print(sep)
    print(f"  Fit Score  : {result.get('fit_score', '?')}/10")
    print(f"  Recommend  : {result.get('recommendation', '?')}")
    print(f"  Strengths  : {result.get('key_strengths', '')}")
    print(f"  Gaps       : {result.get('key_gaps', '')}")
    print(f"  Reasoning  : {result.get('reasoning', '')}")
    print(f"{sep}\n")


def file_mode(input_str: str, profile_path=None) -> None:
    """Assess JD(s) from a file, directory, or URL against the user's profile."""
    from sources.file_mode import load_jd

    logger.info("=== Role Fit Radar — File Mode ===")

    if profile_path:
        profile = Path(profile_path).read_text(encoding="utf-8")
        logger.info(f"Using local profile: {profile_path}")
    else:
        profile = get_profile()

    if not profile:
        logger.warning("Profile is empty — assessments will be low quality")

    jds = load_jd(input_str)
    if not jds:
        logger.info("No supported files found.")
        return

    for name, content in jds:
        content = content[:JOB_CONTENT_MAX_CHARS]
        job = {
            "title": name,
            "department": "",
            "location": "",
            "url": input_str if len(jds) == 1 else name,
            "content": content,
        }
        logger.info(f"Assessing: {name}")
        result = assess_fit(job, profile)
        _print_assessment(name, result)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Role Fit Radar — scan job boards or assess a local JD file"
    )
    parser.add_argument(
        "--file",
        metavar="PATH_OR_URL",
        help=(
            "Assess a JD from a local file (PDF/DOCX/XLSX/TXT), "
            "directory, or URL (Google Doc, SharePoint direct link)"
        ),
    )
    parser.add_argument(
        "--profile",
        metavar="FILE",
        help="Path to a local plain-text profile file (overrides Google Sheets profile)",
    )
    parser.add_argument(
        "--debug", "-v",
        action="store_true",
        help="Enable DEBUG logging (shows per-source title filter breakdown)",
    )
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
        for lib in ("urllib3", "asyncio", "playwright", "hpack", "httpcore", "httpx"):
            logging.getLogger(lib).setLevel(logging.WARNING)

    if args.file:
        file_mode(args.file, profile_path=args.profile)
    else:
        main()
