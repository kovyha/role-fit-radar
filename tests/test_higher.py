from unittest.mock import patch, MagicMock
from sources.higher import fetch_jobs, _discover_location_filter, _strip_html


def _filters_response(country="United Kingdom", subfilter="Greater London, England"):
    m = MagicMock()
    m.json.return_value = {
        "data": {
            "roleSearchFilters": [
                {
                    "filterCategoryType": {"code": "LOCATION"},
                    "filters": [
                        {
                            "filter": country,
                            "subFilters": [{"filter": subfilter}],
                        }
                    ],
                }
            ]
        }
    }
    return m


def _search_response(items, total=None):
    m = MagicMock()
    m.json.return_value = {
        "data": {
            "roleSearch": {
                "totalCount": total if total is not None else len(items),
                "items": items,
            }
        }
    }
    return m


def _item(title, source_id, city="London", country="United Kingdom", division="Engineering", description="<p>Build trading systems.</p>"):
    return {
        "jobTitle": title,
        "division": division,
        "locations": [{"city": city, "country": country}],
        "descriptionHtml": description,
        "externalSource": {"sourceId": str(source_id)},
    }


class TestFetchJobs:
    def test_returns_relevant_london_jobs(self):
        filters_mock = _filters_response()
        search_mock = _search_response([_item("Quantitative Developer", "12345")])

        with patch("requests.post", side_effect=[filters_mock, search_mock]):
            jobs = fetch_jobs("London")

        assert len(jobs) == 1
        assert jobs[0]["title"] == "Quantitative Developer"
        assert jobs[0]["url"] == "https://higher.gs.com/roles/12345"
        assert jobs[0]["location"] == "London, United Kingdom"
        assert jobs[0]["department"] == "Engineering"
        assert "Build trading systems" in jobs[0]["content"]
        assert "<p>" not in jobs[0]["content"]

    def test_irrelevant_title_filtered_out(self):
        filters_mock = _filters_response()
        search_mock = _search_response([_item("Product Manager", "99001")])

        with patch("requests.post", side_effect=[filters_mock, search_mock]):
            jobs = fetch_jobs("London")

        assert jobs == []

    def test_blocklisted_title_filtered_out(self):
        filters_mock = _filters_response()
        search_mock = _search_response([_item("Junior Quant Developer", "99002")])

        with patch("requests.post", side_effect=[filters_mock, search_mock]):
            jobs = fetch_jobs("London")

        assert jobs == []

    def test_seen_url_skipped(self):
        filters_mock = _filters_response()
        search_mock = _search_response([_item("Algo Developer", "12345")])
        seen = {"https://higher.gs.com/roles/12345"}

        with patch("requests.post", side_effect=[filters_mock, search_mock]):
            jobs = fetch_jobs("London", seen_urls=seen)

        assert jobs == []

    def test_no_matching_location_returns_empty(self):
        filters_mock = _filters_response(country="United Kingdom", subfilter="Greater London, England")

        with patch("requests.post", return_value=filters_mock):
            jobs = fetch_jobs("Tokyo")

        assert jobs == []

    def test_http_error_on_filters_returns_empty(self):
        import requests
        with patch("requests.post", side_effect=requests.RequestException("timeout")):
            jobs = fetch_jobs("London")

        assert jobs == []

    def test_http_error_on_search_returns_empty(self):
        import requests
        filters_mock = _filters_response()

        with patch("requests.post", side_effect=[filters_mock, requests.RequestException("timeout")]):
            jobs = fetch_jobs("London")

        assert jobs == []

    def test_pagination(self):
        page1_items = [_item(f"Algo Trader {i}", i) for i in range(50)]
        page2_items = [_item(f"Algo Trader {i}", i + 50) for i in range(10)]

        filters_mock = _filters_response()
        page1 = _search_response(page1_items, total=60)
        page2 = _search_response(page2_items, total=60)

        with patch("requests.post", side_effect=[filters_mock, page1, page2]):
            jobs = fetch_jobs("London")

        assert len(jobs) == 60

    def test_content_truncated_at_6000(self):
        filters_mock = _filters_response()
        search_mock = _search_response([_item("Electronic Trading Developer", "56789", description="<p>" + "x" * 8000 + "</p>")])

        with patch("requests.post", side_effect=[filters_mock, search_mock]):
            jobs = fetch_jobs("London")

        assert len(jobs[0]["content"]) == 6000

    def test_all_required_fields_present(self):
        filters_mock = _filters_response()
        search_mock = _search_response([_item("Systematic Trader", "11111")])

        with patch("requests.post", side_effect=[filters_mock, search_mock]):
            jobs = fetch_jobs("London")

        assert len(jobs) == 1
        for field in ("title", "url", "location", "department", "content"):
            assert field in jobs[0]


class TestDiscoverLocationFilter:
    def test_finds_london_subfilter(self):
        m = _filters_response("United Kingdom", "Greater London, England")
        with patch("requests.post", return_value=m):
            country, sf = _discover_location_filter("London")

        assert country == "United Kingdom"
        assert "London" in sf

    def test_case_insensitive(self):
        m = _filters_response("United Kingdom", "Greater London, England")
        with patch("requests.post", return_value=m):
            country, sf = _discover_location_filter("london")

        assert sf != ""

    def test_no_match_returns_empty_strings(self):
        m = _filters_response("United Kingdom", "Greater London, England")
        with patch("requests.post", return_value=m):
            country, sf = _discover_location_filter("Tokyo")

        assert country == ""
        assert sf == ""

    def test_country_level_match(self):
        """When location_filter matches a country name directly (no subfilter match), return country."""
        m = MagicMock()
        m.json.return_value = {
            "data": {
                "roleSearchFilters": [
                    {
                        "filterCategoryType": {"code": "LOCATION"},
                        "filters": [
                            {"filter": "Singapore", "subFilters": []},
                        ],
                    }
                ]
            }
        }
        with patch("requests.post", return_value=m):
            country, sf = _discover_location_filter("Singapore")

        assert country == "Singapore"
        assert sf == ""

    def test_http_error_returns_empty(self):
        import requests
        with patch("requests.post", side_effect=requests.RequestException("timeout")):
            country, sf = _discover_location_filter("London")

        assert country == ""
        assert sf == ""


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
