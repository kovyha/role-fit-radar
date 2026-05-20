# config.example.py
# Copy this file to config.py and fill in your own values.
# config.py is gitignored — your personal settings never leave your machine
# (or your GitHub Secrets — see scan.yml for how CI injects it).
#
# Secrets (API keys, passwords) are NOT here — they go in GitHub Secrets / env vars.

import os

# ── Title filter lists ────────────────────────────────────────────────────────
# Lowercase substrings checked against each job's title.
# A title must match at least one allowlist term and no blocklist entry to pass.
TITLE_TERMS = frozenset([
    "term1", "term2", "term3",
])

# Optional secondary allowlist for small, curated company boards where generic
# tech titles (e.g. "Platform Engineer", "C++ Developer") are still relevant.
# Use TITLE_TERMS | TECH_TERMS as local_allowlist for those companies.
TECH_TERMS = frozenset([
    "engineer", "developer", "architect", "platform", "software",
])

# Titles containing any of these are rejected even if they match an allowlist.
TITLE_BLOCKLIST = frozenset([
    "recruiter",
    "relocation",
    "junior",
    "intern",
    "graduate",
])

# ── Company / source registry ─────────────────────────────────────────────────
# Each entry must include:
#   local_allowlist  — frozenset of substrings the title must match (empty = skip check)
#   local_blocklist  — frozenset of substrings that disqualify a title
#
# Broad-fetch sources (Greenhouse, Ashby, Workday, Eightfold) fetch all company
# jobs then filter locally — set local_allowlist=TITLE_TERMS (or | TECH_TERMS for
# small curated boards where generic tech titles are still relevant).
#
# For companies where all roles are in scope (e.g. AI firms), set
# local_allowlist=frozenset() to skip the allowlist check entirely.
#
# eFinancialCareers uses search_terms for server-side keyword search; set
# local_allowlist=frozenset() since the server already filters by search_terms.

COMPANIES = [
    # Greenhouse (broad-fetch, domain-filtered):
    # {"name": "Acme Quant", "source": "greenhouse", "board": "acmequant",
    #  "local_allowlist": TITLE_TERMS, "local_blocklist": TITLE_BLOCKLIST},

    # Greenhouse (small curated board — also catch generic tech titles):
    # {"name": "Acme HFT", "source": "greenhouse", "board": "acmehft",
    #  "local_allowlist": TITLE_TERMS | TECH_TERMS, "local_blocklist": TITLE_BLOCKLIST},

    # Greenhouse (AI firm — fetch all roles):
    # {"name": "Acme AI", "source": "greenhouse", "board": "acmeai",
    #  "local_allowlist": frozenset(), "local_blocklist": TITLE_BLOCKLIST},

    # Ashby:
    # {"name": "Acme Corp", "source": "ashby", "org": "acmecorp",
    #  "local_allowlist": frozenset(), "local_blocklist": TITLE_BLOCKLIST},

    # Eightfold (standard — no browser session needed):
    # {"name": "Acme Corp", "source": "eightfold", "domain": "acme.com",
    #  "local_allowlist": TITLE_TERMS, "local_blocklist": TITLE_BLOCKLIST},

    # Eightfold (PCSX-protected board — Playwright establishes browser session):
    # {"name": "Acme Bank", "source": "eightfold", "domain": "acmebank.com",
    #  "use_playwright": True,
    #  "local_allowlist": TITLE_TERMS, "local_blocklist": TITLE_BLOCKLIST},

    # Workday:
    # {"name": "Acme Corp", "source": "workday", "tenant": "acme", "board": "Acme_Professional",
    #  "local_allowlist": TITLE_TERMS, "local_blocklist": TITLE_BLOCKLIST},

    # Oracle HCM Cloud (requires Playwright session for location filtering):
    # {"name": "JPMorgan", "source": "oracle_hcm",
    #  "host": "jpmc.fa.oraclecloud.com", "site": "CX_1001",
    #  "local_allowlist": TITLE_TERMS, "local_blocklist": TITLE_BLOCKLIST},

    # Goldman Sachs (higher.gs.com — custom GraphQL API, no tenant/board params needed):
    # {"name": "Goldman Sachs", "source": "higher",
    #  "local_allowlist": TITLE_TERMS, "local_blocklist": TITLE_BLOCKLIST},

    # LinkedIn job alert emails (requires Gmail IMAP + LinkedIn job alert setup):
    {
        "name": "LinkedIn",
        "source": "linkedin_email",
    },

    # eFinancialCareers — search_terms drives server-side keyword search:
    {
        "name": "eFinancialCareers",
        "source": "efinancialcareers",
        "search_terms": TITLE_TERMS,
        "local_allowlist": frozenset(),
        "local_blocklist": TITLE_BLOCKLIST,
    },
]

# ── General settings ──────────────────────────────────────────────────────────
LOCATION_FILTER = ""  # e.g. "London", "New York", "Singapore"

EMAIL_SENDER = os.environ.get("GMAIL_USER", "")
EMAIL_RECIPIENT = os.environ.get("EMAIL_RECIPIENT", os.environ.get("GMAIL_USER", ""))
EMAIL_SUBJECT = "Role Fit Radar — New Roles Found"

JOBS_TAB = "Jobs"
PROFILE_TAB = "Profile"

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
    "Reasoning",
]

LINKEDIN_LABEL = "JobSearch"
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
# Slug: city name lowercased with hyphens (e.g. "new-york", "hong-kong").
# lat/lng: coordinates for your city.
EFINANCIAL_LOCATION_SLUG = "<your-city>"
EFINANCIAL_LOCATION_LAT  = "0.00000"
EFINANCIAL_LOCATION_LNG  = "0.00000"

# eFC seniority allowlist. Available values:
# VP_PRINCIPAL, SVP_HEAD_OF, DIRECTOR, MANAGING_DIRECTOR, C_SUITE
EFINANCIAL_SENIORITY_LEVELS = [
    "VP_PRINCIPAL",
    "SVP_HEAD_OF",
    "DIRECTOR",
    "MANAGING_DIRECTOR",
    "C_SUITE",
]
