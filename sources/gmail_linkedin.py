# gmail_linkedin.py
# Fetches LinkedIn job alerts from Gmail via IMAP and extracts job listings.
# Each email contains job cards; we parse the HTML to extract URLs and titles.
# For each LinkedIn job, we fetch the full description via Playwright (headless).

import os
import imaplib
import email
import email.message
import re

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

from config import (
    LINKEDIN_LABEL, LINKEDIN_EMAIL_FROM, GMAIL_IMAP_HOST, LINKEDIN_TITLE_SUFFIXES,
    JOB_CONTENT_MAX_CHARS,
    PLAYWRIGHT_PAGE_TIMEOUT_MS, PLAYWRIGHT_SELECTOR_TIMEOUT_MS, PLAYWRIGHT_FALLBACK_WAIT_MS,
)


def fetch_jobs(seen_urls: set = None) -> list[dict]:
    """
    Fetch LinkedIn job alerts from Gmail, parse job listings, and fetch full descriptions.
    Pass seen_urls (from Google Sheet) to skip description fetches for known jobs.
    Returns list of dicts: {title, url, location, department, content, company}
    """
    jobs = []

    try:
        # Step 1: Connect to Gmail IMAP
        mail = imaplib.IMAP4_SSL(GMAIL_IMAP_HOST, 993)
        gmail_user = (os.environ.get("GMAIL_USER") or os.environ.get("EMAIL_SENDER") or "").strip()
        # Google App Passwords are 16-char codes; Google displays them with spaces
        # ("xxxx xxxx xxxx xxxx") but IMAP needs them without — strip all spaces.
        gmail_password = (os.environ.get("GMAIL_APP_PASSWORD") or "").replace(" ", "").strip()

        if not gmail_user or not gmail_password:
            print("[gmail_linkedin] Missing GMAIL_USER or GMAIL_APP_PASSWORD — skipping")
            return []

        mail.login(gmail_user, gmail_password)

        # Step 2: List available mailboxes to find the right label
        status, mailboxes = mail.list()
        if status != 'OK':
            print("[gmail_linkedin] Could not list mailboxes")
            mail.close()
            mail.logout()
            return []

        # Find the JobSearch2026 label (could be [Gmail]/JobSearch2026 or just JobSearch2026)
        label_name = None
        for mailbox in mailboxes:
            mailbox_str = mailbox.decode('utf-8') if isinstance(mailbox, bytes) else mailbox
            if LINKEDIN_LABEL in mailbox_str:
                # Extract the label name from the mailbox string
                # Format: (\\All \\HasNoChildren) "/" "JobSearch2026"
                parts = mailbox_str.split('"')
                if len(parts) >= 2:
                    label_name = parts[-2]
                    break

        if not label_name:
            print(f"[gmail_linkedin] Label '{LINKEDIN_LABEL}' not found. Available labels:")
            for mailbox in mailboxes:
                print(f"  {mailbox}")
            mail.close()
            mail.logout()
            return []

        # Step 3: Select the label
        status, _ = mail.select(label_name)
        if status != 'OK':
            print(f"[gmail_linkedin] Could not select label '{label_name}'")
            mail.close()
            mail.logout()
            return []

        # Step 4: Search for messages from LinkedIn
        status, message_nums = mail.search(None, 'UNSEEN', 'FROM', LINKEDIN_EMAIL_FROM)

        if status != 'OK' or not message_nums[0]:
            print("[gmail_linkedin] No LinkedIn job alert emails found")
            mail.close()
            mail.logout()
            return []

        print(f"[gmail_linkedin] Found {len(message_nums[0].split())} email(s) to parse")

        # Step 5: Parse each email and extract job listings
        for num in message_nums[0].split():
            status, msg_data = mail.fetch(num, '(RFC822)')
            if status != 'OK':
                continue

            msg = email.message_from_bytes(msg_data[0][1])

            # Extract job listings from email HTML
            job_listings = _parse_email_for_jobs(msg)
            jobs.extend(job_listings)

            # Mark as seen so we don't reprocess it
            mail.store(num, '+FLAGS', '\\Seen')

        mail.close()
        mail.logout()

        # Deduplicate within run, then drop URLs already in the Google Sheet
        sheet_seen = seen_urls or set()
        seen_in_run: set[str] = set()
        delta_jobs = []
        for job in jobs:
            if job["url"] not in seen_in_run and job["url"] not in sheet_seen:
                seen_in_run.add(job["url"])
                delta_jobs.append(job)

        # Step 6: Fetch descriptions only for the delta
        print(f"[gmail_linkedin] {len(delta_jobs)} new job(s) to fetch descriptions for")
        for i, job in enumerate(delta_jobs, 1):
            print(f"[gmail_linkedin] Fetching description {i}/{len(delta_jobs)}: {job['title']}")
            page_data = _fetch_job_description(job["url"])
            job["content"] = page_data["content"]
            if page_data["company"]:
                job["company"] = page_data["company"]
            if page_data["location"]:
                job["location"] = page_data["location"]

        print(f"[gmail_linkedin] Done — {len(delta_jobs)} new job(s) from LinkedIn alerts")
        return delta_jobs

    except Exception as e:
        print(f"[gmail_linkedin] Error fetching jobs: {e}")
        return []


def _parse_email_for_jobs(msg: email.message.Message) -> list[dict]:
    """
    Parse LinkedIn job alert email and extract job listings.
    Returns list of job stubs: {title, url, location, company}
    """
    jobs = []

    # Get email body (HTML part)
    html_content = None
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == 'text/html':
                html_content = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                break
    else:
        if msg.get_content_type() == 'text/html':
            html_content = msg.get_payload(decode=True).decode('utf-8', errors='ignore')

    if not html_content:
        return []

    # Parse HTML with BeautifulSoup
    soup = BeautifulSoup(html_content, 'html.parser')

    # Find all LinkedIn job view links
    # Pattern: linkedin.com/jobs/view/JOBID or linkedin.com/jobs/view/JOBID/?...
    for link in soup.find_all('a', href=True):
        href = link['href']

        # Match direct and redirect variants:
        #   linkedin.com/jobs/view/JOBID
        #   linkedin.com/comm/jobs/view/JOBID  (tracking redirect)
        if 'linkedin.com' in href and 'jobs/view/' in href:
            # Normalise to canonical URL — /comm/jobs/view/ redirects require
            # auth and time out; extract the job ID and rebuild the public URL.
            job_id_match = re.search(r'/jobs/view/(\d+)', href)
            if not job_id_match:
                continue
            job_url = f"https://www.linkedin.com/jobs/view/{job_id_match.group(1)}/"

            # Extract title — LinkedIn emails sometimes nest company/location/status
            # text inside the same <a> tag, concatenated without separators.
            # Take only the first line of text, then strip known LinkedIn suffixes.
            raw_text = link.get_text(separator='\n', strip=True)
            title = raw_text.splitlines()[0].strip() if raw_text else ""
            # Strip metadata that appears mid-string when there are no line breaks
            if '·' in title:
                title = title[:title.index('·')].strip()
            for suffix in LINKEDIN_TITLE_SUFFIXES:
                title = title.replace(suffix, '').strip()
            if not title:
                continue  # skip logo/image links that share the job URL but carry no text

            # Try to find company and location from the card container
            # Don't pass unexpected kwargs to BeautifulSoup APIs — just find the nearest container tag
            card = link.find_parent(['div', 'li', 'article'])
            company = "Unknown"
            location = "Unknown"

            if card:
                # Look for company and location in the card
                text = card.get_text(separator=' ')
                # Normalize whitespace for more predictable matching
                norm_text = ' '.join(text.split())

                # Heuristic: find text after ' at ' for company, stopping at bullet or ' in '
                at_idx = norm_text.lower().find(' at ')
                if at_idx != -1:
                    after_at = norm_text[at_idx + 4:]
                    parts = re.split(r'\s*•\s*|\s+in\s+', after_at, maxsplit=1)
                    if parts and parts[0].strip():
                        company = parts[0].strip()

                # Heuristic: find ' in ' for location
                in_match = re.search(r'\bin\s+(.+?)(?:\s+•|\s*$)', norm_text, flags=re.IGNORECASE)
                if in_match:
                    location = in_match.group(1).strip()

            jobs.append({
                "title": title,
                "url": job_url,
                "location": location,
                "company": company,
                "department": "",
                "content": ""  # Will be filled later
            })

    return jobs


def _fetch_job_description(job_url: str) -> dict:
    """
    Fetch full job description, company, and location from LinkedIn using Playwright.
    Returns dict with content, company, location keys.
    """
    try:
        import asyncio
        return asyncio.run(_fetch_description_async(job_url))
    except Exception as e:
        print(f"[gmail_linkedin] Could not fetch description for {job_url}: {e}")
        return {"content": "", "company": "", "location": ""}


async def _fetch_description_async(job_url: str) -> dict:
    """
    Async helper to fetch job description, company, and location using Playwright.
    Extracts from JSON-LD structured data first, then falls back to CSS selectors.
    """
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()
            page = await context.new_page()
            await page.set_extra_http_headers({"User-Agent": (
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )})

            await page.goto(job_url, wait_until='domcontentloaded', timeout=PLAYWRIGHT_PAGE_TIMEOUT_MS)

            try:
                await page.wait_for_selector('.show-more-less-html__markup, [data-test-id="jserp-job-details"]', timeout=PLAYWRIGHT_SELECTOR_TIMEOUT_MS)
            except Exception:
                await page.wait_for_timeout(PLAYWRIGHT_FALLBACK_WAIT_MS)

            data = await page.evaluate('''
                () => {
                    // JSON-LD structured data is the most reliable source
                    let company = '', location = '';
                    for (const script of document.querySelectorAll('script[type="application/ld+json"]')) {
                        try {
                            const d = JSON.parse(script.textContent);
                            if (d['@type'] === 'JobPosting') {
                                company = (d.hiringOrganization && d.hiringOrganization.name) || '';
                                const loc = d.jobLocation;
                                if (loc) {
                                    const addr = loc.address || loc;
                                    location = addr.addressLocality || addr.addressRegion || '';
                                }
                                break;
                            }
                        } catch(e) {}
                    }
                    // CSS selector fallbacks
                    if (!company) {
                        const el = document.querySelector('a.topcard__org-name-link') ||
                                   document.querySelector('.company-name');
                        company = el ? el.textContent.trim() : '';
                    }
                    if (!location) {
                        const el = document.querySelector('.topcard__flavor--bullet');
                        location = el ? el.textContent.trim() : '';
                    }
                    // Description
                    const descEl = document.querySelector('.show-more-less-html__markup') ||
                                   document.querySelector('[data-test-id="jserp-job-details"]') ||
                                   document.querySelector('[class*="description"]');
                    const description = descEl ? descEl.innerText : '';
                    return { description, company, location };
                }
            ''')

            await page.close()
            await context.close()
            await browser.close()

            content = ' '.join((data.get('description') or '').split())[:JOB_CONTENT_MAX_CHARS]
            return {
                "content": content,
                "company": (data.get('company') or '').strip(),
                "location": (data.get('location') or '').strip(),
            }

    except Exception as e:
        print(f"[gmail_linkedin] Playwright error for {job_url}: {e}")
        return {"content": "", "company": "", "location": ""}
