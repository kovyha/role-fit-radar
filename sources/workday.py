# sources/workday.py
# Fetches jobs from a Workday job board via its undocumented but stable CXS API.
# No authentication required. Two-phase: paginated list POST for stubs, GET per
# job for descriptions. Cloudflare is present — a User-Agent header is required
# and detail calls are paced at 1 s apart.
#
# Hard constraint: Workday's limit param is capped at 20. Higher values silently
# return null total and an empty jobPostings array.
#
# Location IDs are auto-discovered from the facets returned by the first request
# so they don't need to be hardcoded in config.

import html as html_lib
import logging
import time
import requests
from bs4 import BeautifulSoup
from config import JOB_CONTENT_MAX_CHARS, REQUEST_TIMEOUT_SECS, TITLE_TERMS, TITLE_BLOCKLIST
from sources.filters import passes_local_filter, explain_filter_result, log_filter_debug

logger = logging.getLogger(__name__.rsplit(".", 1)[-1])


_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
}

_PAGE_SIZE = 20  # Workday hard-caps at 20; any higher returns null total + empty results


def fetch_jobs(tenant: str, board: str, location_filter: str, seen_urls: set | None = None, *, wd: str = "wd1", allowlist: frozenset = TITLE_TERMS, blocklist: frozenset = TITLE_BLOCKLIST, location_aliases: list[str] | None = None) -> list[dict]:
    """
    Fetch new jobs from a Workday board, filtered by location.

    Phase 1: discover location facet IDs, then paginate the list endpoint.
    Phase 2: GET the description for each new, relevant job.

    Args:
        tenant:           Workday tenant slug e.g. "blackrock"
        board:            Workday board name e.g. "BlackRock_Professional"
        location_filter:  String to match against location facet descriptors e.g. "London"
        seen_urls:        URLs already recorded; descriptions skipped for these
        wd:               Workday subdomain e.g. "wd1" or "wd3"
        location_aliases: Additional location terms unioned with location_filter e.g. ["canary wharf"]
                          Useful when a company uses building/district names instead of city names.

    Returns:
        List of job dicts with keys: title, url, location, department, content
    """
    if seen_urls is None:
        seen_urls = set()

    api_base = f"https://{tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{board}"
    jobs_url = f"{api_base}/jobs"
    canonical_base = f"https://{tenant}.{wd}.myworkdayjobs.com/{board}"

    # Phase 1: discover location facet key + IDs then collect stubs
    location_facet_key, location_ids = _discover_location_ids(jobs_url, location_filter, location_aliases)
    if not location_ids:
        logger.warning(f"No location facets matched '{location_filter}' for {tenant}/{board}")
        return []

    stubs = _fetch_stubs(jobs_url, location_facet_key, location_ids, canonical_base)

    # Phase 2: fetch descriptions for new, relevant jobs
    debug_fetched: list[str] = []
    debug_blocked: list[tuple[str, str]] = []
    debug_kept: list[str] = []
    seen_count = 0

    results = []
    for stub in stubs:
        if stub["url"] in seen_urls:
            seen_count += 1
            continue
        title = stub["title"]
        debug_fetched.append(title)
        if not passes_local_filter(title, allowlist, blocklist):
            debug_blocked.append((title, explain_filter_result(title, allowlist, blocklist)))
            continue
        debug_kept.append(title)
        content = _fetch_content(api_base, stub.pop("external_path"))
        stub["content"] = content
        results.append(stub)
        time.sleep(1)  # pace detail calls — Cloudflare is present

    log_filter_debug(logger, debug_fetched, debug_blocked, debug_kept,
                     total=seen_count + len(debug_fetched), seen=seen_count, new=len(results))
    return results


def _discover_location_ids(jobs_url: str, location_filter: str, location_aliases: list[str] | None = None) -> tuple[str, list[str]]:
    """POST with limit=1 to get location facets; return (facet_key, [matching_ids]).

    Handles two Workday facet structures:
    - Nested (BlackRock, Barclays): locationMainGroup → values[].facetParameter="locations" → values[].{id, descriptor}
    - Flat (Deutsche Bank): Location → values[].{id, descriptor}

    location_aliases adds extra match terms (OR logic) so offices that don't use the city
    name (e.g. "Canary Wharf, 1 Churchill Place") are still included.
    """
    try:
        resp = requests.post(
            jobs_url,
            json={"limit": 1, "offset": 0, "appliedFacets": {}},
            headers=_HEADERS,
            timeout=REQUEST_TIMEOUT_SECS,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"Failed to discover location facets: {e}")
        return ("", [])

    needles = {location_filter.lower()} | {a.lower() for a in (location_aliases or [])}

    def _matches(descriptor: str) -> bool:
        d = descriptor.lower()
        return any(n in d for n in needles)

    for facet in resp.json().get("facets", []):
        fp = facet.get("facetParameter", "")
        values = facet.get("values", [])

        # Nested pattern: top-level facet (e.g. "locationMainGroup") contains sub-facets
        for v in values:
            if v.get("values"):
                nested_fp = v.get("facetParameter", fp)
                ids = [nv["id"] for nv in v["values"] if _matches(nv.get("descriptor", "")) and nv.get("id")]
                if ids:
                    return (nested_fp, ids)

        # Flat pattern: location facet directly holds {id, descriptor} entries
        if "location" in fp.lower():
            ids = [v["id"] for v in values if _matches(v.get("descriptor", "")) and v.get("id")]
            if ids:
                return (fp, ids)

    return ("", [])


def _fetch_stubs(jobs_url: str, location_facet_key: str, location_ids: list[str], canonical_base: str) -> list[dict]:
    """Paginate the Workday list endpoint and return all matching job stubs."""
    stubs = []
    offset = 0

    while True:
        try:
            resp = requests.post(
                jobs_url,
                json={
                    "limit": _PAGE_SIZE,
                    "offset": offset,
                    "searchText": "",
                    "appliedFacets": {location_facet_key: location_ids},
                },
                headers=_HEADERS,
                timeout=REQUEST_TIMEOUT_SECS,
            )
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"Failed to fetch stubs (offset={offset}): {e}")
            break

        data = resp.json()
        batch = data.get("jobPostings", [])

        for job in batch:
            external_path = job.get("externalPath", "")
            stubs.append({
                "external_path": external_path,
                "title":         job.get("title", ""),
                "url":           f"{canonical_base}{external_path}",
                "location":      job.get("locationsText", ""),
                "department":    "",
            })

        total = data.get("total") or 0
        offset += len(batch)
        if offset >= total or not batch:
            break

    return stubs


def _fetch_content(api_base: str, external_path: str) -> str:
    """GET the job detail page and return the cleaned description."""
    url = f"{api_base}{external_path}"
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=REQUEST_TIMEOUT_SECS)
        resp.raise_for_status()
        raw = resp.json().get("jobPostingInfo", {}).get("jobDescription", "") or ""
        return _strip_html(raw)[:JOB_CONTENT_MAX_CHARS]
    except requests.RequestException as e:
        logger.error(f"Failed to fetch content for {external_path}: {e}")
        return ""


def _strip_html(html: str) -> str:
    if not html:
        return ""
    return BeautifulSoup(html_lib.unescape(html), "html.parser").get_text(separator="\n", strip=True)
