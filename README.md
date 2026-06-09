# role-fit-radar

Scans target company job boards daily, assesses each new role against your profile using Claude, logs results to Google Sheets, and emails a summary.

---

## Setup — one-time steps

### 1. Google Cloud

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create a new project: `role-fit-radar`
3. Enable two APIs: **Google Sheets API** and **Google Drive API**
4. Create a **Service Account**:
   - IAM & Admin → Service Accounts → Create
   - No role needed at project level
   - Create a JSON key — download it
5. Copy the `client_email` from the JSON key (looks like `xxx@role-fit-radar.iam.gserviceaccount.com`)

### 2. Google Sheet

1. Create a new Google Sheet
2. Rename it `role-fit-radar`
3. Create two tabs: `Jobs` and `Profile`
4. **Share the sheet** with the service account email (Editor access)
5. Copy the Sheet ID from the URL: `https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit`

### 3. Profile tab

In the `Profile` tab, write your background as key-value rows:

| Field | Value |
|-------|-------|
| Name | blah |
| Current Level | blah |
| Years Experience | blah |
| Core Stack | blah |
| Domain | blah |
| ML Experience | blah |
| LLM/Agent Work | blahy |
| Education | blah |
| Target Roles | blah |
| Deal Breakers | blah |

Extend or edit freely — the LLM reads this tab directly.

### 4. Gmail App Password

1. Google Account → Security → 2-Step Verification → App Passwords
2. Generate one for "Mail" / "Other"
3. Save the 16-character password

### 5. GitHub Secrets

In your GitHub repo: Settings → Secrets and variables → Actions → New repository secret

| Secret name | Value |
|-------------|-------|
| `ANTHROPIC_API_KEY` | Your Anthropic API key |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Full contents of the service account JSON key file |
| `GMAIL_APP_PASSWORD` | 16-character app password from step 4 |
| `SHEET_ID` | Sheet ID from step 2 |

---

## Adding more companies

In `config.py`, add to the `COMPANIES` list:

```python
# Greenhouse:
{"name": "DeepMind", "source": "greenhouse", "board": "deepmind",
 "local_allowlist": frozenset(), "local_blocklist": TITLE_BLOCKLIST}

# Ashby:
{"name": "Acme Corp", "source": "ashby", "org": "acmecorp",
 "local_allowlist": TITLE_TERMS, "local_blocklist": TITLE_BLOCKLIST}

# Eightfold:
{"name": "Millennium", "source": "eightfold", "domain": "mlp.com",
 "local_allowlist": TITLE_TERMS, "local_blocklist": TITLE_BLOCKLIST}

# Workday (wd1 subdomain — default):
{"name": "BlackRock", "source": "workday", "tenant": "blackrock", "board": "BlackRock_Professional",
 "local_allowlist": TITLE_TERMS, "local_blocklist": TITLE_BLOCKLIST}

# Workday (wd3 subdomain — some banks use wd3 instead of wd1):
{"name": "Barclays", "source": "workday", "tenant": "barclays", "board": "External_Career_Site_Barclays",
 "wd": "wd3", "local_allowlist": TITLE_TERMS, "local_blocklist": TITLE_BLOCKLIST}
```

The `"wd"` key is optional and defaults to `"wd1"`. Set it to `"wd3"` (or `"wd5"`) when the company's Workday subdomain differs — check the company's careers URL to determine which subdomain they use.

The `"location_aliases"` key is an optional list of extra location strings to union with the primary `LOCATION_FILTER` when discovering Workday facet IDs. Use it when a company posts roles under a campus or district name that does not contain your primary city string (e.g. `"location_aliases": ["canary wharf"]` for a firm whose London postings appear under "Canary Wharf, 1 Churchill Place").

---

## Manual run

### Scan mode (default)

Fetches new jobs from all configured sources, assesses them, logs to Google Sheets, and sends a summary email.

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...
export GOOGLE_SERVICE_ACCOUNT_JSON=$(cat service-account.json)
export GMAIL_APP_PASSWORD=...
export SHEET_ID=...
python main.py
```

### File mode

Assess a single JD (or a directory of JDs) against your profile without writing to Sheets or sending email. Prints results to stdout.

```bash
python main.py --file path/to/job.pdf
python main.py --file path/to/jds/          # all supported files in a directory
python main.py --file https://docs.google.com/...  # Google Doc URL
python main.py --file https://...           # SharePoint / direct download link
```

Supported formats: PDF, DOCX, XLSX, TXT.

Optionally override the Google Sheets profile with a local plain-text file:

```bash
python main.py --file job.pdf --profile my_profile.txt
```

---

## Project structure

```
role-fit-radar/
├── config.py                    # All configuration — version controlled
├── main.py                      # Orchestrator (scan mode + --file mode)
├── assessor.py                  # Claude API fit assessment
├── sheets.py                    # Google Sheets read/write
├── gmail.py                     # Email summary via SMTP
├── sources/
│   ├── greenhouse.py            # Greenhouse API fetcher
│   ├── gmail_linkedin.py        # LinkedIn jobs via Gmail digest emails
│   ├── efinancialcareers.py     # eFinancialCareers scraper
│   ├── ashby.py                 # Ashby ATS fetcher
│   ├── eightfold.py             # Eightfold AI job board fetcher
│   ├── workday.py               # Workday CXS API fetcher
│   ├── higher.py                # Goldman Sachs (higher.gs.com) GraphQL fetcher
│   ├── oracle_hcm.py            # Oracle HCM Cloud career site fetcher
│   ├── filters.py               # Shared title-relevance logic
│   ├── file_mode.py             # File/URL loader for --file mode
│   └── scraper.py               # Playwright scraper stub (future)
├── tests/
│   ├── conftest.py              # Shared fixtures
│   ├── test_assessor.py
│   ├── test_greenhouse.py
│   ├── test_gmail_linkedin.py
│   ├── test_efinancialcareers.py
│   ├── test_ashby.py
│   ├── test_eightfold.py
│   ├── test_workday.py
│   ├── test_higher.py
│   ├── test_oracle_hcm.py
│   ├── test_main_dedup.py
│   ├── test_sheets.py
│   └── test_file_mode.py
├── requirements.txt
└── .github/workflows/scan.yml   # GitHub Actions cron (daily 5pm UTC)
```
