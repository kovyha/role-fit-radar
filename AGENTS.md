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
| `sources/gmail_linkedin.py` | `uv run pytest tests/test_gmail_linkedin.py -v` |
| `sources/efinancialcareers.py` | `uv run pytest tests/test_efinancialcareers.py -v` |
| Any / all sources | `uv run pytest tests/ -v` |

If a test script does not yet exist for a new source you add, **create one** alongside the source file and add it to the table above.

## Pre-Commit Checklist (before any user-approved commit)

**Do not run this checklist yourself.** The moment files are staged, the very next action must be spawning the `pre-commit` subagent — no intermediate bash commands, no summary to the user first.

```
Agent(subagent_type="pre-commit", prompt="Run the pre-commit checklist.")
```

The agent needs no context passed to it — all steps are self-contained. Only proceed to ask the user for commit approval if the agent reports **Overall: PASS**. If it reports FAIL, fix the issues, re-stage, and re-spawn before asking for approval.

The steps the agent runs, for reference:

```bash
# 1. Lint
uv run ruff check .

# 2. Auto-fix safe lint issues
uv run ruff check . --fix

# 3. Full test suite
uv run pytest tests/ -v

# 4. Check for personal data / secrets in staged changes
git diff --cached | grep -iE '(@gmail\.com|@googlemail\.com|AKIA[0-9A-Z]{16}|sk-ant-|AIza|-----BEGIN (RSA |EC )?PRIVATE KEY)' && echo "BLOCKED: personal data or secrets detected in diff" && exit 1 || true
git diff --cached --name-only | grep -E '^(\.env|debug_gmail_efc\.py|.*service.?account.*\.json)$' && echo "BLOCKED: sensitive file staged" && exit 1 || true

# 5. Confirm documentation is current (see below)
```

### Documentation to keep current

- **`README.md`** — update if you add/remove a job source, change env vars, or change the run command.
- **`SKILLS.md`** — update if you add new test scripts or change how linting/testing is invoked.
- **`config.py`** — update `COMPANIES` list comments if you add or retire a source.

## Scope Discipline

- Don't refactor, add features, or clean up code beyond what the task requires.
- Don't add error handling for scenarios that cannot happen; trust existing framework guarantees.
- Default to writing no comments — only add one when the *why* is non-obvious.
