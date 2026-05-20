from unittest.mock import patch, MagicMock
from sources.workday import fetch_jobs, _discover_location_ids, _fetch_content, _strip_html


_LONDON_ID_A = "131d7f8fcf9f01c8d6145e57f75064cd"
_LONDON_ID_B = "131d7f8fcf9f013542e48f95f7503fcf"

_FACETS_RESPONSE = {
    "total": 1,
    "jobPostings": [{"title": "x", "externalPath": "/job/x", "locationsText": "London"}],
    "facets": [
        {
            "facetParameter": "locations",
            "values": [
                {"facetParameter": _LONDON_ID_A, "value": "London, Greater London", "count": 39},
                {"facetParameter": _LONDON_ID_B, "value": "LO9-London - Drapers Gardens", "count": 5},
                {"facetParameter": "paris-id", "value": "Paris, France", "count": 12},
            ],
        }
    ],
}


def _post_mock(data):
    m = MagicMock()
    m.json.return_value = data
    return m


def _get_mock(description):
    m = MagicMock()
    m.json.return_value = {"jobPostingInfo": {"jobDescription": description}}
    return m


def _stubs_page(postings, total):
    return _post_mock({"total": total, "jobPostings": postings, "facets": []})


def _posting(title, path):
    return {"title": title, "externalPath": path, "locationsText": "London, Greater London"}


class TestFetchJobs:
    def test_returns_relevant_london_jobs(self):
        posting = _posting("Quantitative Developer", "/job/London/Quant-Dev_R001")
        discovery = _post_mock(_FACETS_RESPONSE)
        stubs = _stubs_page([posting], total=1)
        detail = _get_mock("<p>Build trading systems.</p>")

        with patch("requests.post", side_effect=[discovery, stubs]), \
             patch("requests.get", return_value=detail), \
             patch("sources.workday.time.sleep"):
            jobs = fetch_jobs("blackrock", "BlackRock_Professional", "London")

        assert len(jobs) == 1
        assert jobs[0]["title"] == "Quantitative Developer"
        assert "blackrock.wd1.myworkdayjobs.com" in jobs[0]["url"]
        assert "Build trading systems" in jobs[0]["content"]
        assert "<p>" not in jobs[0]["content"]

    def test_irrelevant_title_filtered_out(self):
        posting = _posting("Product Manager", "/job/London/PM_R002")
        discovery = _post_mock(_FACETS_RESPONSE)
        stubs = _stubs_page([posting], total=1)

        with patch("requests.post", side_effect=[discovery, stubs]), \
             patch("requests.get") as mock_get, \
             patch("sources.workday.time.sleep"):
            jobs = fetch_jobs("blackrock", "BlackRock_Professional", "London")

        assert jobs == []
        mock_get.assert_not_called()

    def test_seen_url_skips_detail_fetch(self):
        posting = _posting("Algo Engineer", "/job/London/Algo_R003")
        canonical_url = "https://blackrock.wd1.myworkdayjobs.com/BlackRock_Professional/job/London/Algo_R003"
        discovery = _post_mock(_FACETS_RESPONSE)
        stubs = _stubs_page([posting], total=1)

        with patch("requests.post", side_effect=[discovery, stubs]), \
             patch("requests.get") as mock_get, \
             patch("sources.workday.time.sleep"):
            jobs = fetch_jobs("blackrock", "BlackRock_Professional", "London", seen_urls={canonical_url})

        assert jobs == []
        mock_get.assert_not_called()

    def test_no_matching_location_returns_empty(self):
        facets_no_match = {**_FACETS_RESPONSE, "facets": [
            {"facetParameter": "locations", "values": [
                {"facetParameter": "paris-id", "value": "Paris, France", "count": 12},
            ]}
        ]}
        discovery = _post_mock(facets_no_match)

        with patch("requests.post", return_value=discovery):
            jobs = fetch_jobs("blackrock", "BlackRock_Professional", "Tokyo")

        assert jobs == []

    def test_post_error_returns_empty(self):
        import requests
        with patch("requests.post", side_effect=requests.RequestException("timeout")):
            jobs = fetch_jobs("blackrock", "BlackRock_Professional", "London")

        assert jobs == []

    def test_pagination(self):
        page1_postings = [_posting(f"Algo Trader {i}", f"/job/London/Role_{i}") for i in range(20)]
        page2_postings = [_posting(f"Algo Trader {i}", f"/job/London/Role_{i}") for i in range(20, 25)]

        discovery = _post_mock(_FACETS_RESPONSE)
        page1 = _stubs_page(page1_postings, total=25)
        page2 = _stubs_page(page2_postings, total=25)
        detail = _get_mock("Trading role.")

        with patch("requests.post", side_effect=[discovery, page1, page2]), \
             patch("requests.get", return_value=detail), \
             patch("sources.workday.time.sleep"):
            jobs = fetch_jobs("blackrock", "BlackRock_Professional", "London")

        assert len(jobs) == 25

    def test_content_truncated_at_6000(self):
        posting = _posting("Electronic Trading Developer", "/job/London/ETD_R004")
        discovery = _post_mock(_FACETS_RESPONSE)
        stubs = _stubs_page([posting], total=1)
        detail = _get_mock("<p>" + "x" * 8000 + "</p>")

        with patch("requests.post", side_effect=[discovery, stubs]), \
             patch("requests.get", return_value=detail), \
             patch("sources.workday.time.sleep"):
            jobs = fetch_jobs("blackrock", "BlackRock_Professional", "London")

        assert len(jobs[0]["content"]) == 6000

    def test_all_required_fields_present(self):
        posting = _posting("Low Latency Developer", "/job/London/LL_R005")
        discovery = _post_mock(_FACETS_RESPONSE)
        stubs = _stubs_page([posting], total=1)
        detail = _get_mock("Low latency C++ role.")

        with patch("requests.post", side_effect=[discovery, stubs]), \
             patch("requests.get", return_value=detail), \
             patch("sources.workday.time.sleep"):
            jobs = fetch_jobs("blackrock", "BlackRock_Professional", "London")

        assert len(jobs) == 1
        for field in ("title", "url", "location", "department", "content"):
            assert field in jobs[0]

    def test_sleep_called_per_detail_fetch(self):
        postings = [_posting(f"Algo Dev {i}", f"/job/London/AD_{i}") for i in range(3)]
        discovery = _post_mock(_FACETS_RESPONSE)
        stubs = _stubs_page(postings, total=3)
        detail = _get_mock("Algo trading.")

        with patch("requests.post", side_effect=[discovery, stubs]), \
             patch("requests.get", return_value=detail), \
             patch("sources.workday.time.sleep") as mock_sleep:
            fetch_jobs("blackrock", "BlackRock_Professional", "London")

        assert mock_sleep.call_count == 3


class TestDiscoverLocationIds:
    def test_returns_matching_ids(self):
        with patch("requests.post", return_value=_post_mock(_FACETS_RESPONSE)):
            ids = _discover_location_ids("https://example.com/jobs", "London")

        assert _LONDON_ID_A in ids
        assert _LONDON_ID_B in ids
        assert "paris-id" not in ids

    def test_case_insensitive(self):
        with patch("requests.post", return_value=_post_mock(_FACETS_RESPONSE)):
            ids = _discover_location_ids("https://example.com/jobs", "london")

        assert len(ids) == 2

    def test_no_match_returns_empty(self):
        with patch("requests.post", return_value=_post_mock(_FACETS_RESPONSE)):
            ids = _discover_location_ids("https://example.com/jobs", "Tokyo")

        assert ids == []

    def test_http_error_returns_empty(self):
        import requests
        with patch("requests.post", side_effect=requests.RequestException("timeout")):
            ids = _discover_location_ids("https://example.com/jobs", "London")

        assert ids == []


class TestFetchContent:
    def test_strips_html(self):
        with patch("requests.get", return_value=_get_mock("<p>Hello <strong>world</strong></p>")):
            result = _fetch_content("https://example.com/cxs/blackrock/BRP", "/job/x")

        assert "<p>" not in result
        assert "Hello" in result

    def test_http_error_returns_empty(self):
        import requests
        with patch("requests.get", side_effect=requests.RequestException("timeout")):
            result = _fetch_content("https://example.com", "/job/x")

        assert result == ""

    def test_missing_description_returns_empty(self):
        m = MagicMock()
        m.json.return_value = {"jobPostingInfo": {}}
        with patch("requests.get", return_value=m):
            result = _fetch_content("https://example.com", "/job/x")

        assert result == ""


class TestStripHtml:
    def test_strips_tags(self):
        assert "<p>" not in _strip_html("<p>Hello</p>")
        assert "Hello" in _strip_html("<p>Hello</p>")

    def test_handles_entity_encoded_html(self):
        result = _strip_html("&lt;p&gt;Hello&lt;/p&gt;")
        assert "<p>" not in result
        assert "Hello" in result

    def test_empty_string(self):
        assert _strip_html("") == ""

    def test_none(self):
        assert _strip_html(None) == ""
