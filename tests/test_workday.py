from unittest.mock import patch, MagicMock
from sources.workday import fetch_jobs, _discover_location_ids, _fetch_content, _strip_html


_LONDON_ID_A = "131d7f8fcf9f01c8d6145e57f75064cd"
_LONDON_ID_B = "131d7f8fcf9f013542e48f95f7503fcf"
_CANARY_WHARF_ID = "canary-wharf-id-001"

# Real Workday nested facet format (BlackRock / Barclays pattern):
# locationMainGroup → values[].facetParameter="locations" → values[].{id, descriptor}
_FACETS_RESPONSE = {
    "total": 1,
    "jobPostings": [{"title": "x", "externalPath": "/job/x", "locationsText": "London"}],
    "facets": [
        {
            "facetParameter": "locationMainGroup",
            "values": [
                {
                    "facetParameter": "locations",
                    "descriptor": "Locations",
                    "values": [
                        {"descriptor": "London, Greater London", "id": _LONDON_ID_A, "count": 39},
                        {"descriptor": "LO9-London - Drapers Gardens", "id": _LONDON_ID_B, "count": 5},
                        {"descriptor": "Canary Wharf, 1 Churchill Place", "id": _CANARY_WHARF_ID, "count": 106},
                        {"descriptor": "Paris, France", "id": "paris-id", "count": 12},
                    ],
                }
            ],
        }
    ],
}

# Flat facet format (Deutsche Bank pattern): Location → values[].{id, descriptor}
_FLAT_FACETS_RESPONSE = {
    "total": 1,
    "jobPostings": [],
    "facets": [
        {
            "facetParameter": "Location",
            "values": [
                {"descriptor": "London, United Kingdom", "id": "london-uk-id", "count": 20},
                {"descriptor": "Frankfurt, Germany", "id": "frankfurt-id", "count": 15},
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

    def test_wd3_url(self):
        posting = _posting("Algo Trading Developer", "/job/London/ATD_R001")
        discovery = _post_mock(_FACETS_RESPONSE)
        stubs = _stubs_page([posting], total=1)
        detail = _get_mock("Algo role.")

        with patch("requests.post", side_effect=[discovery, stubs]), \
             patch("requests.get", return_value=detail), \
             patch("sources.workday.time.sleep"):
            jobs = fetch_jobs("barclays", "External_Career_Site_Barclays", "London", wd="wd3")

        assert len(jobs) == 1
        assert "barclays.wd3.myworkdayjobs.com" in jobs[0]["url"]

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
        facets_no_match = {
            "total": 0,
            "jobPostings": [],
            "facets": [
                {
                    "facetParameter": "locationMainGroup",
                    "values": [
                        {
                            "facetParameter": "locations",
                            "descriptor": "Locations",
                            "values": [
                                {"descriptor": "Paris, France", "id": "paris-id", "count": 12},
                            ],
                        }
                    ],
                }
            ],
        }
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

    def test_location_aliases_passed_to_discovery(self):
        """location_aliases from company config are forwarded to _discover_location_ids."""
        posting = _posting("Electronic Trading Developer", "/job/CanaryWharf/ETD_R010")
        # Facet response where only the alias matches (no "London" descriptor)
        alias_only_facets = {
            "total": 1,
            "jobPostings": [posting],
            "facets": [{
                "facetParameter": "locationMainGroup",
                "values": [{
                    "facetParameter": "locations",
                    "descriptor": "Locations",
                    "values": [
                        {"descriptor": "Canary Wharf, 1 Churchill Place", "id": _CANARY_WHARF_ID, "count": 106},
                        {"descriptor": "Paris, France", "id": "paris-id", "count": 5},
                    ],
                }],
            }],
        }
        stubs = _stubs_page([posting], total=1)
        detail = _get_mock("Electronic trading role.")

        with patch("requests.post", side_effect=[_post_mock(alias_only_facets), stubs]), \
             patch("requests.get", return_value=detail), \
             patch("sources.workday.time.sleep"):
            jobs = fetch_jobs(
                "barclays", "External_Career_Site_Barclays", "London",
                wd="wd3", location_aliases=["canary wharf"]
            )

        assert len(jobs) == 1
        assert jobs[0]["title"] == "Electronic Trading Developer"


class TestDiscoverLocationIds:
    def test_nested_pattern_returns_matching_ids(self):
        with patch("requests.post", return_value=_post_mock(_FACETS_RESPONSE)):
            facet_key, ids = _discover_location_ids("https://example.com/jobs", "London")

        assert facet_key == "locations"
        assert _LONDON_ID_A in ids
        assert _LONDON_ID_B in ids
        assert _CANARY_WHARF_ID not in ids  # alias not provided — Canary Wharf excluded
        assert "paris-id" not in ids

    def test_location_alias_unions_with_primary(self):
        """location_aliases extends the match: Canary Wharf included alongside London."""
        with patch("requests.post", return_value=_post_mock(_FACETS_RESPONSE)):
            facet_key, ids = _discover_location_ids(
                "https://example.com/jobs", "London", location_aliases=["canary wharf"]
            )

        assert _LONDON_ID_A in ids
        assert _LONDON_ID_B in ids
        assert _CANARY_WHARF_ID in ids
        assert "paris-id" not in ids

    def test_alias_only_match(self):
        """An alias that matches but the primary filter doesn't still returns IDs."""
        with patch("requests.post", return_value=_post_mock(_FACETS_RESPONSE)):
            facet_key, ids = _discover_location_ids(
                "https://example.com/jobs", "Tokyo", location_aliases=["canary wharf"]
            )

        assert _CANARY_WHARF_ID in ids
        assert _LONDON_ID_A not in ids

    def test_flat_pattern_returns_matching_ids(self):
        with patch("requests.post", return_value=_post_mock(_FLAT_FACETS_RESPONSE)):
            facet_key, ids = _discover_location_ids("https://example.com/jobs", "London")

        assert facet_key == "Location"
        assert "london-uk-id" in ids
        assert "frankfurt-id" not in ids

    def test_case_insensitive(self):
        with patch("requests.post", return_value=_post_mock(_FACETS_RESPONSE)):
            facet_key, ids = _discover_location_ids("https://example.com/jobs", "london")

        assert len(ids) == 2

    def test_no_match_returns_empty(self):
        with patch("requests.post", return_value=_post_mock(_FACETS_RESPONSE)):
            facet_key, ids = _discover_location_ids("https://example.com/jobs", "Tokyo")

        assert facet_key == ""
        assert ids == []

    def test_http_error_returns_empty(self):
        import requests
        with patch("requests.post", side_effect=requests.RequestException("timeout")):
            facet_key, ids = _discover_location_ids("https://example.com/jobs", "London")

        assert facet_key == ""
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
