# sources/goldman.py
# Fetches jobs from Goldman Sachs careers (higher.gs.com) via their GraphQL API.
# No authentication required — the endpoint is publicly accessible.
# Single-phase: one paginated GraphQL query returns stubs + full description HTML,
# so there are no per-job detail calls.
#
# Location filtering uses a two-level hierarchy in the GS filter schema:
# country (e.g. "United Kingdom") → region/city subfilter (e.g. "Greater London, England").
# _discover_location_filter() resolves both levels from location_filter at runtime.

import html as html_lib
import requests
from bs4 import BeautifulSoup
from config import JOB_CONTENT_MAX_CHARS, REQUEST_TIMEOUT_SECS, TITLE_TERMS, TITLE_BLOCKLIST
from sources.filters import passes_local_filter


_GQL_URL = "https://api-higher.gs.com/gateway/api/v1/graphql"
_CAREERS_BASE = "https://higher.gs.com"
_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Origin": "https://higher.gs.com",
    "Referer": "https://higher.gs.com/roles",
}
_PAGE_SIZE = 50
_EXPERIENCE = "PROFESSIONAL"

_ROLE_SEARCH_QUERY = """
query GetRoles($input: RoleSearchQueryInput!) {
  roleSearch(searchQueryInput: $input) {
    totalCount
    items {
      roleId
      jobTitle
      division
      locations { city country }
      descriptionHtml
      externalSource { sourceId }
    }
  }
}
"""

_FILTERS_QUERY = """
{
  roleSearchFilters(experiences: [PROFESSIONAL], categories: [LOCATION]) {
    filterCategoryType { code }
    filters {
      filter
      subFilters { filter }
    }
  }
}
"""


def fetch_jobs(location_filter: str, seen_urls: set | None = None, *, allowlist: frozenset = TITLE_TERMS, blocklist: frozenset = TITLE_BLOCKLIST) -> list[dict]:
    """
    Fetch new Goldman Sachs jobs, filtered by location.

    Args:
        location_filter: String matched case-insensitively against city/region subfilters e.g. "London"
        seen_urls:       URLs already recorded; jobs with these URLs are skipped
        allowlist:       Title allowlist (empty frozenset = skip check)
        blocklist:       Title blocklist

    Returns:
        List of job dicts with keys: title, url, location, department, content
    """
    if seen_urls is None:
        seen_urls = set()

    country, subfilter = _discover_location_filter(location_filter)
    if not subfilter:
        print(f"[higher] No location filter matched '{location_filter}'")
        return []

    return _fetch_stubs(country, subfilter, seen_urls, allowlist, blocklist)


def _discover_location_filter(location_filter: str) -> tuple[str, str]:
    """Return (country, subfilter) matching location_filter, or ("", "") if none found."""
    try:
        resp = requests.post(_GQL_URL, json={"query": _FILTERS_QUERY}, headers=_HEADERS, timeout=REQUEST_TIMEOUT_SECS)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"[higher] Failed to fetch location filters: {e}")
        return ("", "")

    needle = location_filter.lower()
    for cat in resp.json().get("data", {}).get("roleSearchFilters", []):
        if cat.get("filterCategoryType", {}).get("code") != "LOCATION":
            continue
        for country_entry in cat.get("filters", []):
            country = country_entry.get("filter", "")
            for sub in country_entry.get("subFilters", []):
                sf = sub.get("filter", "")
                if needle in sf.lower():
                    return (country, sf)
            # Also match at country level (e.g. location_filter="Singapore")
            if needle in country.lower():
                return (country, "")
    return ("", "")


def _fetch_stubs(country: str, subfilter: str, seen_urls: set, allowlist: frozenset, blocklist: frozenset) -> list[dict]:
    """Paginate the roleSearch GraphQL query and return filtered job dicts."""
    if subfilter:
        gql_filters = [
            {
                "filterCategoryType": "LOCATION",
                "filters": [{"filter": country, "subFilters": [{"filter": subfilter, "subFilters": []}]}],
            }
        ]
    else:
        gql_filters = [
            {
                "filterCategoryType": "LOCATION",
                "filters": [{"filter": country, "subFilters": []}],
            }
        ]

    results = []
    page = 0

    while True:
        payload = {
            "query": _ROLE_SEARCH_QUERY,
            "variables": {
                "input": {
                    "page": {"pageSize": _PAGE_SIZE, "pageNumber": page},
                    "experiences": [_EXPERIENCE],
                    "filters": gql_filters,
                }
            },
        }
        try:
            resp = requests.post(_GQL_URL, json=payload, headers=_HEADERS, timeout=REQUEST_TIMEOUT_SECS)
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"[higher] Failed to fetch jobs (page={page}): {e}")
            break

        data = resp.json().get("data", {}).get("roleSearch", {})
        items = data.get("items") or []
        total = data.get("totalCount") or 0

        for item in items:
            source_id = (item.get("externalSource") or {}).get("sourceId", "")
            url = f"{_CAREERS_BASE}/roles/{source_id}" if source_id else ""
            if not url or url in seen_urls:
                continue

            title = item.get("jobTitle", "")
            if not passes_local_filter(title, allowlist, blocklist):
                continue

            locs = item.get("locations") or []
            location = ", ".join(filter(None, [locs[0].get("city", ""), locs[0].get("country", "")])) if locs else ""
            content = _strip_html(item.get("descriptionHtml") or "")[:JOB_CONTENT_MAX_CHARS]

            results.append({
                "title": title,
                "url": url,
                "location": location,
                "department": item.get("division", ""),
                "content": content,
            })

        fetched = page * _PAGE_SIZE + len(items)
        if fetched >= total or not items:
            break
        page += 1

    return results


def _strip_html(html: str) -> str:
    if not html:
        return ""
    return BeautifulSoup(html_lib.unescape(html), "html.parser").get_text(separator="\n", strip=True)
