# config.example.py
# Copy this file to config.py and fill in your own values.
# config.py is gitignored — your personal settings never leave your machine
# (or your GitHub Secrets — see scan.yml for how CI injects it).
#
# Secrets (API keys, passwords) are NOT here — they go in GitHub Secrets / env vars.

import os

COMPANIES = [
    # Greenhouse-hosted companies (uses the public jobs API — no scraping needed).
    # Find the board slug at: https://boards.greenhouse.io/{slug}
    # {"name": "Acme Corp", "source": "greenhouse", "board": "acmecorp"},

    # LinkedIn job alert emails (requires Gmail IMAP + LinkedIn job alert setup):
    {
        "name": "LinkedIn",
        "source": "linkedin_email"
    },
    # eFinancialCareers (Playwright scraper — finance/banking/tech roles):
    {
        "name": "eFinancialCareers",
        "source": "efinancialcareers"
    }
]

# Location string passed to job sources that support free-text location filtering.
# Leave empty to disable (not all sources support this).
LOCATION_FILTER = ""  # e.g. "London", "New York", "Singapore"

EMAIL_SENDER = os.environ.get("GMAIL_USER", "")
EMAIL_RECIPIENT = os.environ.get("EMAIL_RECIPIENT", os.environ.get("GMAIL_USER", ""))
EMAIL_SUBJECT = "Role Fit Radar — New Roles Found"

JOBS_TAB = "Jobs"
PROFILE_TAB = "Profile"

# Sheet column order — must match append_jobs() in sheets.py
JOBS_COLUMNS = [
    "Date Found",
    "Company",
    "Source",
    "Title",
    "Location",
    "Department",
    "URL",
    "Fit Score (1-10)",
    "Key Strengths",
    "Key Gaps",
    "Recommendation",
    "Reasoning"
]

LINKEDIN_LABEL = "JobSearch"  # Gmail label applied to your LinkedIn job alert emails
LINKEDIN_EMAIL_FROM = [
    "jobalerts-noreply@linkedin.com",
    "jobs-listings@linkedin.com",
]
GMAIL_IMAP_HOST = "imap.gmail.com"
LINKEDIN_TITLE_SUFFIXES = [
    "Actively recruiting",
    "Easy Apply",
    "Be an early applicant",
]

CLAUDE_MODEL = "claude-haiku-4-5-20251001"
ASSESSOR_MAX_TOKENS = 500

JOB_CONTENT_MAX_CHARS = 6000
REQUEST_TIMEOUT_SECS = 15
PLAYWRIGHT_PAGE_TIMEOUT_MS = 30000
PLAYWRIGHT_SELECTOR_TIMEOUT_MS = 10000
PLAYWRIGHT_FALLBACK_WAIT_MS = 2000
EFINANCIAL_PAGE_SIZE = 200

# eFinancialCareers location parameters — set these to your target city.
# Slug: city name lowercased with spaces replaced by hyphens (e.g. "new-york", "hong-kong").
# lat/lng: look up your city's coordinates with any geocoder.
EFINANCIAL_LOCATION_SLUG = "<your-city>"   # e.g. "new-york"
EFINANCIAL_LOCATION_LAT  = "0.00000"       # e.g. "40.71280"
EFINANCIAL_LOCATION_LNG  = "0.00000"       # e.g. "-74.00600"

# Keywords submitted as separate searches to eFinancialCareers.
# Use broad terms — the title filter below then narrows results further.
# Replace these with the role types you're targeting.
EFINANCIAL_KEYWORDS = [
    "Keyword One",
    "Keyword Two",
    "Keyword Three",
]

# Lowercase substrings — a job title must contain at least one to pass.
# Use partial forms to catch variations (e.g. "quant" matches "quantitative").
EFINANCIAL_TITLE_TERMS = frozenset([
    "term1", "term2", "term3",
])

# Titles containing any of these are rejected even if they match EFINANCIAL_TITLE_TERMS.
EFINANCIAL_TITLE_BLOCKLIST = frozenset([
    "recruiter",
    "relocation",
    "production support",
    "support engineer",
    "junior",
    "intern",
    "graduate",
])

# eFC filters.seniority allowlist — customize for your target seniority level(s).
# Available values: VP_PRINCIPAL, SVP_HEAD_OF, DIRECTOR, MANAGING_DIRECTOR, C_SUITE
EFINANCIAL_SENIORITY_LEVELS = [
    "VP_PRINCIPAL",
    "SVP_HEAD_OF",
    "DIRECTOR",
    "MANAGING_DIRECTOR",
    "C_SUITE",
]
