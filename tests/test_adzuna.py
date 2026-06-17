from unittest.mock import patch, MagicMock
import pytest
import requests

from sources.adzuna import fetch_jobs, _fetch_content


# ── API response fixtures ─────────────────────────────────────────────────────

def _api_response(results: list, status_code: int = 200):
    mock = MagicMock()
    mock.status_code = status_code
    mock.raise_for_status = MagicMock()
    mock.json.return_value = {"results": results, "count": len(results)}
    return mock


def _empty_api_response():
    return _api_response([])


def _eal_job(job_id="111"):
    return {
        "id": job_id,
        "title": "EAL Teacher Part Time",
        "company": {"display_name": "Language School Ltd"},
        "location": {"display_name": "London"},
        "description": "EAL teaching role, 15 hrs/week.",
        "redirect_url": f"https://www.adzuna.co.uk/land/ad/{job_id}?utm_source=api",
        "created": "2024-06-01T10:00:00Z",
    }


def _admin_job(job_id="222"):
    return {
        "id": job_id,
        "title": "Admin Coordinator Remote",
        "company": {"display_name": "Remote Office Co"},
        "location": {"display_name": "Remote"},
        "description": "Administrative support role.",
        "redirect_url": f"https://www.adzuna.co.uk/land/ad/{job_id}?utm_source=api",
        "created": "2024-06-02T09:00:00Z",
    }


def _sales_job(job_id="333"):
    return {
        "id": job_id,
        "title": "Sales Executive",
        "company": {"display_name": "Sales Corp"},
        "location": {"display_name": "Manchester"},
        "description": "B2B sales role.",
        "redirect_url": f"https://www.adzuna.co.uk/land/ad/{job_id}?utm_source=api",
        "created": "2024-06-03T08:00:00Z",
    }


_DETAIL_HTML = """
<html><body>
  <div class="job-description">
    <h1>EAL Teacher Part Time</h1>
    <p>We are seeking an experienced EAL teacher for part-time remote work.</p>
    <p>CELTA or equivalent required. 15 hours per week.</p>
  </div>
</body></html>
"""


def _make_get(api_jobs=None, detail_html=_DETAIL_HTML, api_error=None):
    """Returns a side_effect for requests.get that serves API responses then detail pages."""
    api_jobs = api_jobs if api_jobs is not None else [_eal_job()]
    call_count = [0]

    def side_effect(url, **kwargs):
        call_count[0] += 1
        if "api.adzuna.com" in url:
            if api_error:
                raise api_error
            # First page returns jobs, subsequent pages return empty (stop pagination)
            page = int(url.rstrip("/").rsplit("/", 1)[-1])
            if page == 1:
                return _api_response(api_jobs)
            return _empty_api_response()
        else:
            # Detail page
            mock = MagicMock()
            mock.raise_for_status = MagicMock()
            mock.text = detail_html
            return mock

    return side_effect, call_count


# ── fetch_jobs ────────────────────────────────────────────────────────────────

class TestFetchJobs:

    @pytest.fixture(autouse=True)
    def patch_creds(self):
        with patch.multiple("sources.adzuna", _APP_ID="test_id", _APP_KEY="test_key"):
            yield

    def test_returns_matching_jobs(self):
        side_effect, _ = _make_get([_eal_job()])
        with patch("requests.get", side_effect=side_effect):
            jobs = fetch_jobs("", search_terms=frozenset(["eal"]), allowlist=frozenset(["eal"]))
        assert len(jobs) == 1
        assert jobs[0]["title"] == "EAL Teacher Part Time"

    def test_title_allowlist_filters_out_unmatched(self):
        side_effect, _ = _make_get([_sales_job()])
        with patch("requests.get", side_effect=side_effect):
            jobs = fetch_jobs("", search_terms=frozenset(["sales"]), allowlist=frozenset(["eal"]))
        assert jobs == []

    def test_title_blocklist_filters_out_blocked(self):
        side_effect, _ = _make_get([_sales_job()])
        with patch("requests.get", side_effect=side_effect):
            jobs = fetch_jobs(
                "", search_terms=frozenset(["sales"]),
                allowlist=frozenset(), blocklist=frozenset(["sales"]),
            )
        assert jobs == []

    def test_seen_url_skips_detail_fetch(self):
        job = _eal_job("111")
        seen = {"https://www.adzuna.co.uk/jobs/details/111"}
        side_effect, call_count = _make_get([job])
        with patch("requests.get", side_effect=side_effect):
            jobs = fetch_jobs("", seen_urls=seen, search_terms=frozenset(["eal"]))
        assert jobs == []
        # Only the API page fetch; no detail fetch
        assert call_count[0] == 1

    def test_http_error_returns_empty(self):
        side_effect, _ = _make_get(api_error=requests.RequestException("timeout"))
        with patch("requests.get", side_effect=side_effect):
            jobs = fetch_jobs("", search_terms=frozenset(["eal"]))
        assert jobs == []

    def test_all_required_fields_present(self):
        side_effect, _ = _make_get([_eal_job()])
        with patch("requests.get", side_effect=side_effect):
            jobs = fetch_jobs("", search_terms=frozenset(["eal"]), allowlist=frozenset(["eal"]))
        assert len(jobs) == 1
        for field in ("title", "url", "company", "location", "department", "content"):
            assert field in jobs[0]

    def test_no_internal_redirect_url_field_leaked(self):
        side_effect, _ = _make_get([_eal_job()])
        with patch("requests.get", side_effect=side_effect):
            jobs = fetch_jobs("", search_terms=frozenset(["eal"]), allowlist=frozenset(["eal"]))
        assert "_redirect_url" not in jobs[0]

    def test_no_duplicate_across_search_terms(self):
        job = _eal_job("111")
        side_effect, call_count = _make_get([job])
        with patch("requests.get", side_effect=side_effect):
            jobs = fetch_jobs(
                "", search_terms=frozenset(["eal", "english teacher"]),
                allowlist=frozenset(["eal"]),
            )
        assert len(jobs) == 1

    def test_canonical_url_uses_stable_job_id(self):
        """Stored URL must be stable across runs (no tracking tokens)."""
        side_effect, _ = _make_get([_eal_job("999")])
        with patch("requests.get", side_effect=side_effect):
            jobs = fetch_jobs("", search_terms=frozenset(["eal"]), allowlist=frozenset(["eal"]))
        assert jobs[0]["url"] == "https://www.adzuna.co.uk/jobs/details/999"
        assert "utm_source" not in jobs[0]["url"]

    def test_first_published_extracted_from_created(self):
        side_effect, _ = _make_get([_eal_job()])
        with patch("requests.get", side_effect=side_effect):
            jobs = fetch_jobs("", search_terms=frozenset(["eal"]), allowlist=frozenset(["eal"]))
        assert jobs[0]["first_published"] == "2024-06-01"

    def test_content_from_detail_page(self):
        side_effect, _ = _make_get([_eal_job()])
        with patch("requests.get", side_effect=side_effect):
            jobs = fetch_jobs("", search_terms=frozenset(["eal"]), allowlist=frozenset(["eal"]))
        assert "CELTA" in jobs[0]["content"]

    def test_pagination_stops_on_empty_page(self):
        """Should stop fetching pages when API returns fewer results than page size."""
        side_effect, call_count = _make_get([_eal_job()])
        with patch("requests.get", side_effect=side_effect):
            fetch_jobs("", search_terms=frozenset(["eal"]), allowlist=frozenset(["eal"]))
        # Page 1 (API, 1 result < 50 → stop) + 1 detail fetch = 2 calls
        assert call_count[0] == 2

    def test_multiple_jobs_all_returned(self):
        side_effect, _ = _make_get([_eal_job("111"), _admin_job("222")])
        with patch("requests.get", side_effect=side_effect):
            jobs = fetch_jobs(
                "", search_terms=frozenset(["eal"]),
                allowlist=frozenset(["eal", "admin"]),
            )
        assert len(jobs) == 2

    def test_network_error_returns_empty(self):
        side_effect, _ = _make_get(api_error=requests.RequestException("timeout"))
        with patch("requests.get", side_effect=side_effect):
            jobs = fetch_jobs("", search_terms=frozenset(["eal"]))
        assert jobs == []


class TestFetchJobsMissingCreds:

    def test_missing_credentials_raises(self):
        with pytest.raises(RuntimeError, match="not configured"):
            with patch.multiple("sources.adzuna", _APP_ID="", _APP_KEY=""):
                fetch_jobs("", search_terms=frozenset(["eal"]))

    def test_missing_credentials_makes_no_http_requests(self):
        with patch("requests.get") as mock_get:
            with patch.multiple("sources.adzuna", _APP_ID="", _APP_KEY=""):
                with pytest.raises(RuntimeError):
                    fetch_jobs("", search_terms=frozenset(["eal"]))
        mock_get.assert_not_called()

    def test_auth_rejected_raises(self):
        auth_error = requests.HTTPError(response=MagicMock(status_code=401))
        side_effect, _ = _make_get(api_error=auth_error)
        with pytest.raises(RuntimeError, match="auth rejected"):
            with patch.multiple("sources.adzuna", _APP_ID="test_id", _APP_KEY="test_key"):
                with patch("requests.get", side_effect=side_effect):
                    fetch_jobs("", search_terms=frozenset(["eal"]))


# ── _fetch_content ────────────────────────────────────────────────────────────

class TestFetchContent:

    def test_returns_text_from_detail_page(self):
        mock = MagicMock()
        mock.raise_for_status = MagicMock()
        mock.text = _DETAIL_HTML
        with patch("requests.get", return_value=mock):
            result = _fetch_content("https://www.adzuna.co.uk/land/ad/111")
        assert "EAL Teacher" in result
        assert "CELTA" in result
        assert "<p>" not in result

    def test_falls_back_to_api_description_on_error(self):
        with patch("requests.get", side_effect=requests.RequestException("blocked")):
            result = _fetch_content("https://example.com/job/1", fallback="API description text")
        assert result == "API description text"

    def test_content_truncated_at_max(self):
        long_html = f"<div class='job-description'>{'word ' * 5000}</div>"
        mock = MagicMock()
        mock.raise_for_status = MagicMock()
        mock.text = long_html
        with patch("requests.get", return_value=mock):
            result = _fetch_content("https://www.adzuna.co.uk/land/ad/111")
        assert len(result) <= 6000
