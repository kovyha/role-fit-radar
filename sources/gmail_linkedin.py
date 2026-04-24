# gmail_linkedin.py
# Fetches LinkedIn job alerts from Gmail via IMAP and extracts job listings.
# Each email contains job cards; we parse the HTML to extract URLs and titles.
# For each LinkedIn job, we fetch the full description via Playwright (headless).

import os
import imaplib
import email
from email.header import decode_header
from html.parser import HTMLParser
from urllib.parse import urlparse, parse_qs
import re

import requests
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

from config import LINKEDIN_LABEL, GMAIL_IMAP_HOST


def fetch_jobs() -> list[dict]:
    """
    Fetch LinkedIn job alerts from Gmail, parse job listings, and fetch full descriptions.
    Returns list of dicts: {title, url, location, department, content, company}
    """
    jobs = []

    try:
        # Step 1: Connect to Gmail IMAP
        mail = imaplib.IMAP4_SSL(GMAIL_IMAP_HOST, 993)
        gmail_user = os.environ.get("GMAIL_USER") or os.environ.get("EMAIL_SENDER")
        # Use get() so missing env var doesn't raise during tests where IMAP is mocked
        gmail_password = os.environ.get("GMAIL_APP_PASSWORD")
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
        status, message_nums = mail.search(None, 'FROM', 'jobalerts-noreply@linkedin.com')

        if status != 'OK' or not message_nums[0]:
            print("[gmail_linkedin] No LinkedIn job alert emails found")
            mail.close()
            mail.logout()
            return []

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

        # Step 6: Fetch full job descriptions for each job (synchronously)
        for job in jobs:
            job["content"] = _fetch_job_description(job["url"])

        # Deduplicate by URL
        seen_urls = set()
        unique_jobs = []
        for job in jobs:
            if job["url"] not in seen_urls:
                seen_urls.add(job["url"])
                unique_jobs.append(job)

        print(f"[gmail_linkedin] Fetched {len(unique_jobs)} unique job(s) from LinkedIn alerts")
        return unique_jobs

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

        # Check if it's a LinkedIn job link
        if 'linkedin.com/jobs/view/' in href:
            # Extract job URL (ensure it's clean)
            job_url = href.split('?')[0]  # Remove query params
            if not job_url.startswith('http'):
                job_url = 'https://' + job_url

            # Extract title and metadata from surrounding elements
            title = link.get_text(strip=True)
            if not title:
                title = "Unknown Role"

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


def _fetch_job_description(job_url: str) -> str:
    """
    Fetch full job description from LinkedIn using Playwright.
    Returns the job description text, or empty string on failure.
    """
    try:
        import asyncio
        return asyncio.run(_fetch_description_async(job_url))
    except Exception as e:
        print(f"[gmail_linkedin] Could not fetch description for {job_url}: {e}")
        return ""


async def _fetch_description_async(job_url: str) -> str:
    """
    Async helper to fetch job description using Playwright.
    """
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            # Set a realistic user agent
            await page.set_user_agent(
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )

            await page.goto(job_url, wait_until='networkidle', timeout=30000)

            # Wait for the job description to load
            # LinkedIn uses .show-more-less-html__markup or similar selector
            try:
                await page.wait_for_selector('[data-test-id="jserp-job-details"]', timeout=10000)
            except:
                # Fallback: just wait for some content
                await page.wait_for_timeout(2000)

            # Extract description text
            description = await page.evaluate('''
                () => {
                    // Try primary selector
                    let elem = document.querySelector('[data-test-id="jserp-job-details"]');
                    if (!elem) {
                        // Fallback: get all text content
                        elem = document.querySelector('.show-more-less-html__markup') ||
                               document.querySelector('[class*="description"]') ||
                               document.body;
                    }
                    return elem ? elem.innerText : '';
                }
            ''')

            await browser.close()

            # Clean up whitespace
            description = ' '.join(description.split())[:6000]  # Cap at 6000 chars like greenhouse
            return description

    except Exception as e:
        print(f"[gmail_linkedin] Playwright error for {job_url}: {e}")
        return ""
