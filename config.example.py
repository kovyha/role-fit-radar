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
# Plain terms match as substrings anywhere in the title (e.g. "junior" blocks "Junior Developer").
# Glob-wrapped terms (e.g. "*term4*") use embedded-only matching: blocked only when the term
# appears inside a larger word (e.g. "financial"), not when it stands alone (e.g. "Term4 Engineer").
# Use glob-wrapping for short acronyms that would otherwise cause false positives.
TITLE_BLOCKLIST = frozenset([
    "recruiter",
    "relocation",
    "junior",
    "intern",
    "graduate",
    "*term4*",  # example: blocks 'unterm4ed' but not 'Term4 Engineer'
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
    # Optional: add "wd": "wd3" when the company's subdomain is wd3 (check their careers URL).
    # Optional: add "location_aliases": ["canary wharf"] to also match locations whose
    #  Workday facet descriptor does not contain the primary LOCATION_FILTER string.

    # Oracle HCM Cloud (requires Playwright session for location filtering):
    # {"name": "Acme Bank", "source": "oracle_hcm",
    #  "host": "acme.fa.oraclecloud.com", "site": "CX_1001",
    #  "local_allowlist": TITLE_TERMS, "local_blocklist": TITLE_BLOCKLIST},

    # Higher (custom GraphQL API, no tenant/board params needed):
    # {"name": "Acme Corp", "source": "higher",
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
# EMAIL_RECIPIENT supports comma-separated addresses: "a@example.com, b@example.com"
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

# ── Ask AI — CV variant routing ──────────────────────────────────────────────
# CV_VARIANTS maps a short key to the exact Google Drive filename for each CV.
# CV_AI_KEYWORDS / CV_QUANT_KEYWORDS are matched (case-insensitive substring)
# against the combined title + department + content of a job to auto-select the
# most relevant variant. AI keywords are checked first; quant second; "main" is
# the fallback.
CV_VARIANTS = {
    "main":  "Your_CV.docx",
    # Add more variants if you have role-specific CV versions, e.g.:
    # "ai":    "Your_CV_AI.docx",
    # "quant": "Your_CV_Quant.docx",
}

CV_AI_KEYWORDS: set[str] = {
    # Lowercase substrings that signal an AI/ML-focused role, e.g.:
    # "machine learning", "llm", "deep learning",
}

CV_QUANT_KEYWORDS: set[str] = {
    # Lowercase substrings that signal a quant/research role, e.g.:
    # "quant", "derivatives", "monte carlo",
}

CLAUDE_MODEL = "claude-haiku-4-5-20251001"
ASSESSOR_MAX_TOKENS = 500

# Score caps applied when the model identifies unmet required qualifications.
# Key = number of unmet required quals, value = maximum allowed fit_score.
UNMET_REQUIRED_SCORE_CAPS: dict[int, int] = {1: 6, 2: 4}

# Keyword-triggered hints injected into the assessor prompt.
# Each entry is (list_of_keywords, hint_text). If any keyword in the list
# appears in the job title (case-insensitive substring match), the hint is
# appended to the prompt before assessment. Use this to guide the model when
# certain role types should be evaluated differently — e.g. suppressing a
# perceived "gap" that does not actually apply to that type of role.
KEYWORD_ASSESS_HINTS: list[tuple[list[str], str]] = [
    # Example: tell the model not to flag a missing domain as a gap for specialist roles.
    # (
    #     ["keyword1", "keyword2"],
    #     "This is a <role-type> role. Focus on <relevant criteria> only.",
    # ),
]

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
