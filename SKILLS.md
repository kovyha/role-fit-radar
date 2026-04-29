# Skills & Local Commands

## Package manager

This project uses `uv`. Always prefix Python/pytest/ruff commands with `uv run`.

## Linting

```bash
# Check for issues
uv run ruff check .

# Auto-fix safe issues
uv run ruff check . --fix
```

## Running tests

```bash
# All tests
uv run pytest tests/ -v

# Single source
uv run pytest tests/test_greenhouse.py -v
uv run pytest tests/test_gmail_linkedin.py -v
uv run pytest tests/test_efinancialcareers.py -v
```

Tests use `unittest.mock` to avoid real network calls — safe to run locally at any time.

## Test scripts per data source

| Source file | Test file | What it covers |
|---|---|---|
| `sources/greenhouse.py` | `tests/test_greenhouse.py` | Greenhouse API fetch, location filter, HTML stripping, content truncation |
| `sources/gmail_linkedin.py` | `tests/test_gmail_linkedin.py` | IMAP login, email parsing, LinkedIn URL extraction |
| `sources/efinancialcareers.py` | `tests/test_efinancialcareers.py` | Playwright browser automation, keyword/location URL encoding, user-agent headers |
| `sources/file_mode.py` | `tests/test_file_mode.py` | Google Doc URL export, URL dispatch by content-type, local file loading, directory scan, error skipping |

### Adding a new source

1. Create `sources/<name>.py`.
2. Create `tests/test_<name>.py` with at minimum: happy path, empty result, and error/exception cases.
3. Add a row to the table above.
4. Add the source to `config.py` COMPANIES list and wire it into `main.py`.
5. Update `README.md` with any new env vars or configuration.

## Debugging sources locally

`debug_gmail_efc.py` tests Gmail/LinkedIn IMAP fetching and eFC scraping without writing to Sheets or sending email. Runs eFC with one keyword for speed.

```bash
# Uses first keyword from EFINANCIAL_KEYWORDS by default
uv run python debug_gmail_efc.py

# Override the keyword
EFC_KEYWORD="VWAP" uv run python debug_gmail_efc.py
```

Requires `GMAIL_USER`, `GMAIL_APP_PASSWORD` in the environment. Not committed (gitignored).

## Running the full pipeline (dry-run)

```bash
# Requires real credentials in environment — do not run in CI without secrets
uv run python main.py
```

## Environment variables required

| Variable | Purpose |
|---|---|
| `GMAIL_USER` | Gmail address used for sending summary emails and IMAP access |
| `GMAIL_APP_PASSWORD` | Gmail App Password (spaces optional, will be stripped) |
| `ANTHROPIC_API_KEY` | Claude API key for job fit assessments |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Service account JSON for Google Sheets access |
| `SHEET_ID` | Google Sheet ID (from the sheet URL) |
