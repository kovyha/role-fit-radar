from unittest.mock import patch, MagicMock
from sources.greenhouse import fetch_jobs, _fetch_content, _strip_html


def _make_get(stubs, detail=None):
    """Return a requests.get side_effect that serves stubs for the list URL
    and detail for any per-job URL (contains a numeric segment after /jobs/)."""
    def side_effect(url, **kwargs):
        mock = MagicMock()
        # Per-job detail URL contains the job id after /jobs/
        segments = url.rstrip("?content=true").rstrip("/").split("/")
        if segments[-1].isdigit():
            mock.json.return_value = detail or {}
        else:
            mock.json.return_value = stubs
        return mock
    return side_effect


class TestFetchJobs:
    """Tests for greenhouse.fetch_jobs()"""

    def test_location_match_returns_job(self, greenhouse_stubs_response, greenhouse_detail_1001):
        with patch("requests.get", side_effect=_make_get(greenhouse_stubs_response, greenhouse_detail_1001)):
            jobs = fetch_jobs("anthropic", "London")

        assert len(jobs) == 1
        assert jobs[0]["title"] == "Senior Quantitative Developer"
        assert jobs[0]["location"] == "London, UK"
        assert jobs[0]["url"] == "https://www.anthropic.com/careers/1001"

    def test_location_no_match_returns_empty(self, greenhouse_stubs_response):
        with patch("requests.get", side_effect=_make_get(greenhouse_stubs_response)):
            jobs = fetch_jobs("anthropic", "Tokyo")

        assert jobs == []

    def test_empty_board_returns_empty(self, greenhouse_api_empty):
        with patch("requests.get", side_effect=_make_get(greenhouse_api_empty)):
            jobs = fetch_jobs("anthropic", "London")

        assert jobs == []

    def test_http_error_returns_empty(self):
        import requests
        with patch("requests.get", side_effect=requests.RequestException("timeout")):
            jobs = fetch_jobs("anthropic", "London")

        assert jobs == []

    def test_html_stripped_from_content(self, greenhouse_stubs_response, greenhouse_detail_1001):
        with patch("requests.get", side_effect=_make_get(greenhouse_stubs_response, greenhouse_detail_1001)):
            jobs = fetch_jobs("anthropic", "London")

        assert len(jobs) == 1
        assert "<p>" not in jobs[0]["content"]
        assert "<strong>" not in jobs[0]["content"]
        assert "senior quant developer" in jobs[0]["content"].lower()

    def test_content_truncated_at_6000(self, greenhouse_stubs_long_content, greenhouse_detail_3001):
        with patch("requests.get", side_effect=_make_get(greenhouse_stubs_long_content, greenhouse_detail_3001)):
            jobs = fetch_jobs("anthropic", "London")

        assert len(jobs) == 1
        assert len(jobs[0]["content"]) == 6000

    def test_no_departments_defaults_to_unknown(self, greenhouse_stubs_no_departments, greenhouse_detail_2001):
        with patch("requests.get", side_effect=_make_get(greenhouse_stubs_no_departments, greenhouse_detail_2001)):
            jobs = fetch_jobs("anthropic", "London")

        assert len(jobs) == 1
        assert jobs[0]["department"] == "Unknown"

    def test_all_required_fields_present(self, greenhouse_stubs_response, greenhouse_detail_1001):
        with patch("requests.get", side_effect=_make_get(greenhouse_stubs_response, greenhouse_detail_1001)):
            jobs = fetch_jobs("anthropic", "London")

        assert len(jobs) == 1
        job = jobs[0]
        for field in ("title", "url", "location", "department", "content"):
            assert field in job

    def test_seen_url_skips_detail_fetch(self, greenhouse_stubs_response):
        """Jobs whose URL is in seen_urls are excluded — no detail API call made."""
        seen = {"https://www.anthropic.com/careers/1001"}
        call_count = 0

        def counting_get(url, **kwargs):
            nonlocal call_count
            call_count += 1
            mock = MagicMock()
            mock.json.return_value = greenhouse_stubs_response
            return mock

        with patch("requests.get", side_effect=counting_get):
            jobs = fetch_jobs("anthropic", "London", seen_urls=seen)

        assert jobs == []
        assert call_count == 1  # only the stubs call, no detail calls

    def test_partial_seen_urls_fetches_only_new(self, greenhouse_stubs_response, greenhouse_detail_1001):
        """When some URLs are seen and some are new, only new ones get detail fetched."""
        # Add a second London job to stubs
        stubs = {
            "jobs": greenhouse_stubs_response["jobs"] + [
                {
                    "id": 1003,
                    "title": "Quant Researcher",
                    "absolute_url": "https://www.anthropic.com/careers/1003",
                    "location": {"name": "London, UK"},
                    "departments": [{"name": "Research"}],
                }
            ]
        }
        seen = {"https://www.anthropic.com/careers/1001"}

        with patch("requests.get", side_effect=_make_get(stubs, greenhouse_detail_1001)):
            jobs = fetch_jobs("anthropic", "London", seen_urls=seen)

        assert len(jobs) == 1
        assert jobs[0]["title"] == "Quant Researcher"


    def test_irrelevant_title_filtered_out(self):
        """London jobs with non-trading titles are dropped before content fetch."""
        stubs = {"jobs": [
            {
                "id": 9001,
                "title": "Product Manager",
                "absolute_url": "https://example.com/careers/9001",
                "location": {"name": "London, UK"},
                "departments": [{"name": "Product"}],
            }
        ]}
        with patch("requests.get", side_effect=_make_get(stubs)):
            jobs = fetch_jobs("anthropic", "London")
        assert jobs == []

    def test_blocklisted_title_filtered_out(self):
        """London jobs matching title terms but hitting the blocklist are dropped."""
        stubs = {"jobs": [
            {
                "id": 9002,
                "title": "Junior Quant Developer",
                "absolute_url": "https://example.com/careers/9002",
                "location": {"name": "London, UK"},
                "departments": [{"name": "Engineering"}],
            }
        ]}
        with patch("requests.get", side_effect=_make_get(stubs)):
            jobs = fetch_jobs("anthropic", "London")
        assert jobs == []


class TestFetchContent:
    """Tests for greenhouse._fetch_content()"""

    def test_returns_clean_text(self):
        detail = {"content": "<p>Hello <strong>world</strong></p>"}
        mock = MagicMock()
        mock.json.return_value = detail
        with patch("requests.get", return_value=mock):
            result = _fetch_content("anthropic", 1001)
        assert "<p>" not in result
        assert "Hello" in result
        assert "world" in result

    def test_http_error_returns_empty_string(self):
        import requests
        with patch("requests.get", side_effect=requests.RequestException("timeout")):
            result = _fetch_content("anthropic", 1001)
        assert result == ""

    def test_missing_content_field_returns_empty_string(self):
        mock = MagicMock()
        mock.json.return_value = {"id": 1001}
        with patch("requests.get", return_value=mock):
            result = _fetch_content("anthropic", 1001)
        assert result == ""


class TestStripHtml:
    """Tests for greenhouse._strip_html()"""

    def test_removes_tags(self):
        html = "<p>Hello <strong>World</strong>!</p><p>Second paragraph.</p>"
        result = _strip_html(html)
        assert "<p>" not in result
        assert "<strong>" not in result
        assert "Hello" in result
        assert "World" in result
        assert "Second paragraph" in result

    def test_empty_string(self):
        assert _strip_html("") == ""

    def test_none_value(self):
        assert _strip_html(None) == ""
