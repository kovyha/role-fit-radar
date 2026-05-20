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
from pathlib import Path

from config import COMPANIES, LOCATION_FILTER, JOB_CONTENT_MAX_CHARS
from sources.greenhouse import fetch_jobs as greenhouse_fetch
from sources.scraper import fetch_jobs as scraper_fetch
from sources.gmail_linkedin import fetch_jobs as linkedin_fetch
from sources.efinancialcareers import fetch_jobs as efinancial_fetch
from sources.ashby import fetch_jobs as ashby_fetch
from sources.eightfold import fetch_jobs as eightfold_fetch
from sources.workday import fetch_jobs as workday_fetch
from sheets import get_seen_urls, get_seen_title_company_keys, get_profile, append_jobs
from assessor import assess_fit
from gmail import send_summary


def main():
    print("=== Role Fit Radar — Starting scan ===")

    # Step 1 & 2: Load state from Google Sheets
    seen_urls = get_seen_urls()
    seen_title_keys = get_seen_title_company_keys()  # cross-platform dedup; grows within the run too
    profile = get_profile()
    print(f"[main] {len(seen_urls)} previously seen role(s) loaded")

    if not profile:
        print("[main] WARNING: Profile tab is empty — assessments will be low quality")

    all_new_jobs = []

    # Step 3 & 4: Fetch and diff
    for company in COMPANIES:
        print(f"[main] Scanning {company['name']} ({company['source']})...")

        if company["source"] == "greenhouse":
            jobs = greenhouse_fetch(company["board"], LOCATION_FILTER, seen_urls=seen_urls)
        elif company["source"] == "scraper":
            jobs = scraper_fetch(company["url"], LOCATION_FILTER)
        elif company["source"] == "linkedin_email":
            jobs = linkedin_fetch(seen_urls=seen_urls)
        elif company["source"] == "efinancialcareers":
            jobs = efinancial_fetch(LOCATION_FILTER, seen_urls=seen_urls)
        elif company["source"] == "ashby":
            jobs = ashby_fetch(company["org"], LOCATION_FILTER, seen_urls=seen_urls)
        elif company["source"] == "eightfold":
            jobs = eightfold_fetch(company["domain"], LOCATION_FILTER, seen_urls=seen_urls)
        elif company["source"] == "workday":
            jobs = workday_fetch(company["tenant"], company["board"], LOCATION_FILTER, seen_urls=seen_urls)
        else:
            print(f"[main] Unknown source '{company['source']}' for {company['name']} — skipping")
            continue

        new_jobs = [j for j in jobs if j["url"] not in seen_urls]
        print(f"[main] {company['name']}: {len(jobs)} total, {len(new_jobs)} new")

        # Step 5: Assess each new role
        for job in new_jobs:
            if company["source"] in ("greenhouse", "ashby", "eightfold", "workday"):
                job["company"] = company["name"]
            title_key = f"{job.get('title', '').lower()}|{job.get('company', '').lower()}"
            if title_key in seen_title_keys:
                original_url = seen_title_keys[title_key]
                print(f"[main] Duplicate (cross-platform): {job['title']} @ {job.get('company', '')}")
                job.update({"fit_score": "", "key_strengths": "", "key_gaps": "",
                            "recommendation": "Dup", "reasoning": f"Dup of {original_url}"})
                job["source"] = company["source"]
                all_new_jobs.append(job)
                continue
            seen_title_keys[title_key] = job.get("url", "")
            print(f"[main] Assessing: {job['title']}")
            assessment = assess_fit(job, profile)
            job.update(assessment)
            job["source"] = company["source"]
            all_new_jobs.append(job)

    # Step 6 & 7: Write and notify
    if all_new_jobs:
        append_jobs(all_new_jobs)
    send_summary(all_new_jobs)
    if all_new_jobs:
        print(f"[main] Done — {len(all_new_jobs)} new role(s) processed and emailed")
    else:
        print("[main] Done — no new roles found, status email sent")


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

    print("=== Role Fit Radar — File Mode ===")

    if profile_path:
        profile = Path(profile_path).read_text(encoding="utf-8")
        print(f"[file_mode] Using local profile: {profile_path}")
    else:
        profile = get_profile()

    if not profile:
        print("[file_mode] WARNING: Profile is empty — assessments will be low quality")

    jds = load_jd(input_str)
    if not jds:
        print("[file_mode] No supported files found.")
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
        print(f"[file_mode] Assessing: {name}")
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
    args = parser.parse_args()

    if args.file:
        file_mode(args.file, profile_path=args.profile)
    else:
        main()
