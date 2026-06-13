# Agent Guidelines

## Git & Commits

- **Never commit, squash, or push changes without explicit user approval.** Show a diff summary and ask first.
- Never use `--no-verify` or skip hooks unless the user explicitly requests it.
- Prefer creating new commits over amending existing ones.

## Testing Data Fetching Changes

Whenever you modify any file under `sources/` or `gmail.py`, run the relevant test script(s) locally **before** reporting the change as done.

| Source changed | Test command |
|---|---|
| `sources/greenhouse.py` | `uv run pytest tests/test_greenhouse.py -v` |
| `sources/ashby.py` | `uv run pytest tests/test_ashby.py -v` |
| `sources/eightfold.py` | `uv run pytest tests/test_eightfold.py -v` |
| `sources/workday.py` | `uv run pytest tests/test_workday.py -v` |
| `sources/higher.py` | `uv run pytest tests/test_higher.py -v` |
| `sources/oracle_hcm.py` | `uv run pytest tests/test_oracle_hcm.py -v` |
| `sources/gmail_linkedin.py` | `uv run pytest tests/test_gmail_linkedin.py -v` |
| `sources/efinancialcareers.py` | `uv run pytest tests/test_efinancialcareers.py -v` |
| `sources/simplyhired.py` | `uv run pytest tests/test_simplyhired.py -v` |
| `sources/tes.py` | `uv run pytest tests/test_tes.py -v` |
| `sources/wfh_hub.py` | `uv run pytest tests/test_wfh_hub.py -v` |
| `sources/filters.py` | `uv run pytest tests/test_filters.py -v` |
| `sources/file_mode.py` | `uv run pytest tests/test_file_mode.py -v` |
| `gmail.py` | `uv run pytest tests/test_gmail.py -v` |
| `main.py` | `uv run pytest tests/test_main_timeout.py tests/test_main_dedup.py -v` |
| Any / all sources | `uv run pytest tests/ -v` |

If a test script does not yet exist for a new source you add, **create one** alongside the source file and add it to the table above.

## Scope Discipline

- Don't refactor, add features, or clean up code beyond what the task requires.
- Don't add error handling for scenarios that cannot happen; trust existing framework guarantees.
- Default to writing no comments — only add one when the *why* is non-obvious.
