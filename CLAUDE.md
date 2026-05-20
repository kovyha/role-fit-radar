# Role Fit Radar — Codebase Guide

## Architecture

Scan pipeline: `main.py` orchestrates sources → assessor → sheets → email.

- **Sources** (`sources/`): one module per integration type. Each exposes `fetch_jobs(...)` returning `list[dict]` with keys `title, url, location, department, content`.
- **Filters** (`sources/filters.py`): shared title-relevance logic used by every source.
- **Config** (`config.py`): all tunable constants. Not version-controlled (contains secrets via env vars). See `config.example.py` for the template.

## Rules for adding a new source

1. Implement `fetch_jobs(...)` returning the standard dict shape above.
2. **Call `passes_local_filter(title, allowlist, blocklist)` from `sources.filters` before yielding a job.** Pass the `allowlist` and `blocklist` received from the caller (populated by `main.py` from the company's `local_allowlist`/`local_blocklist` config keys). Do this before fetching job content (Phase 2 / detail calls) to avoid wasted HTTP requests.
3. Respect `seen_urls`: skip URL-fetch and content-fetch for any URL already in the set.
4. Register the source in `main.py` dispatch and add an entry to `COMPANIES` in `config.py`.
5. Add tests covering: location match, title filter pass, title filter reject (irrelevant), title filter reject (blocklist), seen-URL skip, HTTP error, and required fields.

## Title filtering

`TITLE_TERMS` (allowlist) and `TITLE_BLOCKLIST` (denylist) in `config.py` are the canonical filter lists. Each company entry in `COMPANIES` declares `local_allowlist` and `local_blocklist`; `main.py` passes these to `fetch_jobs(..., allowlist=..., blocklist=...)`. Sources call `passes_local_filter(title, allowlist, blocklist)` from `sources/filters.py`.

- **Broad-fetch sources** (Greenhouse, Ashby, Workday, Eightfold): set `local_allowlist=TITLE_TERMS` to filter titles locally after fetching all company jobs.
- **Keyword-search sources** (eFC): set `local_allowlist=frozenset()` — the server-side search already uses `search_terms=TITLE_TERMS`, so only the blocklist adds value locally.
- **AI firms** (Anthropic, DeepMind, OpenAI): set `local_allowlist=frozenset()` to receive all roles — job titles at AI companies don't match the finance-oriented `TITLE_TERMS`.

Update `TITLE_TERMS` and `TITLE_BLOCKLIST` in `config.py` when the target role profile changes.

## Testing

```
pytest                          # full suite
pytest tests/test_greenhouse.py # single file
```

Coverage gate is 90% and is configurable via `fail_under` in `pyproject.toml`. Run `pytest --cov` to check.

## Gates

### Before any agent handoff to user

1. Run the full test suite (`pytest`) — all tests must pass.

### Before any commit or push

Spawn the `pre-commit` subagent immediately after staging files — no intermediate commands, no summary to the user first. Only proceed to ask the user for commit approval if it reports **Overall: PASS**.

```
Agent(subagent_type="pre-commit", prompt="Run the pre-commit checklist.")
```

The agent runs: lint → auto-fix → full test suite → secrets scan → coverage check → documentation currency check.
