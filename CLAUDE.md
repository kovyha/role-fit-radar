# Role Fit Radar — Codebase Guide

## Architecture

Scan pipeline: `main.py` orchestrates sources → assessor → sheets → email.

- **Sources** (`sources/`): one module per integration type. Each exposes `fetch_jobs(...)` returning `list[dict]` with keys `title, url, location, department, content`.
- **Filters** (`sources/filters.py`): shared title-relevance logic used by every source.
- **Config** (`config.py`): all tunable constants. Not version-controlled (contains secrets via env vars). See `config.example.py` for the template.

## Rules for adding a new source

1. Implement `fetch_jobs(...)` returning the standard dict shape above.
2. **Always apply `is_relevant_title(title)` from `sources.filters` before yielding a job.** Do this before fetching job content (Phase 2 / detail calls) to avoid wasted HTTP requests.
3. Respect `seen_urls`: skip URL-fetch and content-fetch for any URL already in the set.
4. Register the source in `main.py` dispatch and add an entry to `COMPANIES` in `config.py`.
5. Add tests covering: location match, title filter pass, title filter reject (irrelevant), title filter reject (blocklist), seen-URL skip, HTTP error, and required fields.

## Title filtering

`TITLE_TERMS` (allowlist) and `TITLE_BLOCKLIST` (denylist) in `config.py` drive all source filtering via `sources/filters.py:is_relevant_title()`. Update these lists in `config.py` when the target role profile changes — the change propagates automatically to all sources.

## Testing

```
pytest                          # full suite
pytest tests/test_greenhouse.py # single file
```

Coverage gate is 90%. Run `pytest --cov` to check.
