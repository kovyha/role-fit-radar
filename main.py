# main.py
# Orchestrator — runs the full pipeline:
#   1. Load seen URLs from Google Sheets (deduplication)
#   2. Load user profile from Google Sheets
#   3. Fetch jobs from each configured company
#   4. Identify net new roles
#   5. Assess each new role against the profile via Claude API
#   6. Append results to Google Sheets
#   7. Send summary email if any new roles found

from config import COMPANIES, LOCATION_FILTER
from sources.greenhouse import fetch_jobs as greenhouse_fetch
from sources.scraper import fetch_jobs as scraper_fetch
from sheets import get_seen_urls, get_profile, append_jobs
from assessor import assess_fit
from gmail import send_summary


def main():
    print("=== Role Fit Radar — Starting scan ===")

    # Step 1 & 2: Load state from Google Sheets
    seen_urls = get_seen_urls()
    profile = get_profile()
    print(f"[main] {len(seen_urls)} previously seen role(s) loaded")

    if not profile:
        print("[main] WARNING: Profile tab is empty — assessments will be low quality")

    all_new_jobs = []

    # Step 3 & 4: Fetch and diff
    for company in COMPANIES:
        print(f"[main] Scanning {company['name']} ({company['source']})...")

        if company["source"] == "greenhouse":
            jobs = greenhouse_fetch(company["board"], LOCATION_FILTER)
        elif company["source"] == "scraper":
            jobs = scraper_fetch(company["url"], LOCATION_FILTER)
        else:
            print(f"[main] Unknown source '{company['source']}' for {company['name']} — skipping")
            continue

        new_jobs = [j for j in jobs if j["url"] not in seen_urls]
        print(f"[main] {company['name']}: {len(jobs)} total, {len(new_jobs)} new")

        # Step 5: Assess each new role
        for job in new_jobs:
            print(f"[main] Assessing: {job['title']}")
            assessment = assess_fit(job, profile)
            job.update(assessment)
            job["company"] = company["name"]
            all_new_jobs.append(job)

    # Step 6 & 7: Write and notify
    if all_new_jobs:
        append_jobs(all_new_jobs)
    send_summary(all_new_jobs)
    if all_new_jobs:
        print(f"[main] Done — {len(all_new_jobs)} new role(s) processed and emailed")
    else:
        print("[main] Done — no new roles found, status email sent")


if __name__ == "__main__":
    main()
