from unittest.mock import patch, MagicMock
from sources.ashby import fetch_jobs, _matches_location


LONDON_JOB = {
    "id": "abc-123",
    "title": "Quantitative Developer",
    "jobUrl": "https://jobs.ashbyhq.com/openai/abc-123",
    "location": "London, UK",
    "secondaryLocations": [],
    "department": "Engineering",
    "team": "Platform",
    "descriptionPlain": "We are looking for a quantitative developer with 5+ years experience.",
    "descriptionHtml": "<p>We are looking for a quantitative developer with 5+ years experience.</p>",
    "employmentType": "FullTime",
    "isListed": True,
}

SF_JOB = {
    "id": "def-456",
    "title": "Product Manager",
    "jobUrl": "https://jobs.ashbyhq.com/openai/def-456",
    "location": "San Francisco, CA",
    "secondaryLocations": [],
    "department": "Product",
    "team": "Growth",
    "descriptionPlain": "Seeking an experienced product manager.",
    "descriptionHtml": "<p>Seeking an experienced product manager.</p>",
    "employmentType": "FullTime",
    "isListed": True,
}

MULTI_LOCATION_JOB = {
    "id": "ghi-789",
    "title": "Electronic Trading Developer",
    "jobUrl": "https://jobs.ashbyhq.com/openai/ghi-789",
    "location": "Dublin, Ireland",
    "secondaryLocations": [
        {"location": "London, UK", "address": {}},
        {"location": "Zurich, Switzerland", "address": {}},
    ],
    "department": "Engineering",
    "team": "Trading",
    "descriptionPlain": "Electronic trading role across multiple offices.",
    "descriptionHtml": "<p>Electronic trading role across multiple offices.</p>",
    "employmentType": "FullTime",
    "isListed": True,
}


def _mock_response(jobs):
    mock = MagicMock()
    mock.json.return_value = {"jobs": jobs, "apiVersion": "1"}
    return mock


class TestFetchJobs:
    def test_location_match_returns_job(self):
        with patch("requests.get", return_value=_mock_response([LONDON_JOB, SF_JOB])):
            jobs = fetch_jobs("openai", "London")

        assert len(jobs) == 1
        assert jobs[0]["title"] == "Quantitative Developer"
        assert jobs[0]["location"] == "London, UK"
        assert jobs[0]["url"] == "https://jobs.ashbyhq.com/openai/abc-123"
        assert jobs[0]["department"] == "Engineering"

    def test_secondary_location_match(self):
        with patch("requests.get", return_value=_mock_response([MULTI_LOCATION_JOB, SF_JOB])):
            jobs = fetch_jobs("openai", "London")

        assert len(jobs) == 1
        assert jobs[0]["title"] == "Electronic Trading Developer"

    def test_location_no_match_returns_empty(self):
        with patch("requests.get", return_value=_mock_response([LONDON_JOB, SF_JOB])):
            jobs = fetch_jobs("openai", "Tokyo")

        assert jobs == []

    def test_empty_board_returns_empty(self):
        with patch("requests.get", return_value=_mock_response([])):
            jobs = fetch_jobs("openai", "London")

        assert jobs == []

    def test_http_error_returns_empty(self):
        import requests
        with patch("requests.get", side_effect=requests.RequestException("timeout")):
            jobs = fetch_jobs("openai", "London")

        assert jobs == []

    def test_content_truncated_at_6000(self):
        long_job = {**LONDON_JOB, "descriptionPlain": "x" * 8000}
        with patch("requests.get", return_value=_mock_response([long_job])):
            jobs = fetch_jobs("openai", "London")

        assert len(jobs[0]["content"]) == 6000

    def test_seen_url_skipped(self):
        seen = {"https://jobs.ashbyhq.com/openai/abc-123"}
        with patch("requests.get", return_value=_mock_response([LONDON_JOB, SF_JOB])):
            jobs = fetch_jobs("openai", "London", seen_urls=seen)

        assert jobs == []

    def test_all_required_fields_present(self):
        with patch("requests.get", return_value=_mock_response([LONDON_JOB])):
            jobs = fetch_jobs("openai", "London")

        assert len(jobs) == 1
        for field in ("title", "url", "location", "department", "content"):
            assert field in jobs[0]

    def test_uses_description_plain(self):
        with patch("requests.get", return_value=_mock_response([LONDON_JOB])):
            jobs = fetch_jobs("openai", "London")

        assert "quantitative developer" in jobs[0]["content"].lower()
        assert "<p>" not in jobs[0]["content"]

    def test_irrelevant_title_filtered_out(self):
        irrelevant = {**LONDON_JOB, "title": "Product Manager", "jobUrl": "https://jobs.ashbyhq.com/openai/pm-1"}
        with patch("requests.get", return_value=_mock_response([irrelevant])):
            jobs = fetch_jobs("openai", "London")
        assert jobs == []

    def test_blocklisted_title_filtered_out(self):
        blocklisted = {**LONDON_JOB, "title": "Junior Quant Developer", "jobUrl": "https://jobs.ashbyhq.com/openai/jr-1"}
        with patch("requests.get", return_value=_mock_response([blocklisted])):
            jobs = fetch_jobs("openai", "London")
        assert jobs == []


class TestMatchesLocation:
    def test_primary_location_match(self):
        assert _matches_location(LONDON_JOB, "London") is True

    def test_secondary_location_match(self):
        assert _matches_location(MULTI_LOCATION_JOB, "London") is True

    def test_no_match(self):
        assert _matches_location(SF_JOB, "London") is False

    def test_case_insensitive(self):
        assert _matches_location(LONDON_JOB, "london") is True
