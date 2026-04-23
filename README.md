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
| Name | Ivy Yip |
| Current Level | Executive Director |
| Years Experience | 18 years electronic trading technology |
| Core Stack | kdb+/q, Java, Python, C++ |
| Domain | Sell-side, benchmark execution, algo trading, internalisation |
| ML Experience | Random Forest inference engine (production) |
| LLM/Agent Work | MCP server, alert triage agent, PR safety gates, prompt library |
| Education | MEng Information Systems Engineering, Imperial College London |
| Target Roles | Engineering Manager, Data Infrastructure, AI/LLM-adjacent technical leadership |
| Deal Breakers | No consulting, no sales, no pure front-end, no ML research |

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
# Greenhouse company (free, no scraping needed):
{"name": "DeepMind", "source": "greenhouse", "board": "deepmind"}

# Non-Greenhouse company (requires implementing scraper):
{"name": "Jane Street", "source": "scraper", "url": "https://www.janestreet.com/join-jane-street/open-roles/"}
```

---

## Manual run

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...
export GOOGLE_SERVICE_ACCOUNT_JSON=$(cat service-account.json)
export GMAIL_APP_PASSWORD=...
export SHEET_ID=...
python main.py
```

---

## Project structure

```
role-fit-radar/
├── config.py                    # All configuration — version controlled
├── main.py                      # Orchestrator
├── assessor.py                  # Claude API fit assessment
├── sheets.py                    # Google Sheets read/write
├── gmail.py                     # Email summary via SMTP
├── sources/
│   ├── greenhouse.py            # Greenhouse API fetcher
│   └── scraper.py               # Playwright scraper stub (future)
├── requirements.txt
└── .github/workflows/scan.yml   # GitHub Actions cron (daily 5pm UTC)
```
