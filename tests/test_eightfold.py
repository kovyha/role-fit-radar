from unittest.mock import patch, MagicMock
from sources.eightfold import fetch_jobs, _fetch_content, _strip_html


def _stub(job_id, title, url, location="London, United Kingdom", department="Technology"):
    return {
        "id": job_id,
        "name": title,
        "canonicalPositionUrl": url,
        "location": location,
        "locations": [location],
        "department": department,
        "business_unit": department,
        "job_description": "",
    }


def _list_response(positions, count=None):
    mock = MagicMock()
    mock.json.return_value = {
        "positions": positions,
        "count": count if count is not None else len(positions),
    }
    return mock


def _detail_response(job_description):
    mock = MagicMock()
    mock.json.return_value = {"job_description": job_description}
    return mock


class TestFetchJobs:
    def test_returns_new_jobs_with_content(self):
        stub = _stub(1001, "Quant Developer", "https://mlp.eightfold.ai/careers/job/1001")
        list_mock = _list_response([stub])
        detail_mock = _detail_response("<p>Exciting quant role in London.</p>")

        with patch("requests.get", side_effect=[list_mock, detail_mock]):
            jobs = fetch_jobs("mlp.com", "London")

        assert len(jobs) == 1
        assert jobs[0]["title"] == "Quant Developer"
        assert jobs[0]["url"] == "https://mlp.eightfold.ai/careers/job/1001"
        assert "Exciting quant role" in jobs[0]["content"]
        assert "<p>" not in jobs[0]["content"]

    def test_seen_url_skips_detail_fetch(self):
        stub = _stub(1001, "Quant Researcher", "https://mlp.eightfold.ai/careers/job/1001")
        list_mock = _list_response([stub])
        call_count = 0

        def counting_get(url, **kwargs):
            nonlocal call_count
            call_count += 1
            return list_mock

        with patch("requests.get", side_effect=counting_get):
            jobs = fetch_jobs("mlp.com", "London", seen_urls={"https://mlp.eightfold.ai/careers/job/1001"})

        assert jobs == []
        assert call_count == 1  # only the list call

    def test_http_error_returns_empty(self):
        import requests
        with patch("requests.get", side_effect=requests.RequestException("timeout")):
            jobs = fetch_jobs("mlp.com", "London")

        assert jobs == []

    def test_all_required_fields_present(self):
        stub = _stub(1001, "Systematic Trading Analyst", "https://mlp.eightfold.ai/careers/job/1001")
        with patch("requests.get", side_effect=[_list_response([stub]), _detail_response("Risk role.")]):
            jobs = fetch_jobs("mlp.com", "London")

        assert len(jobs) == 1
        for field in ("title", "url", "location", "department", "content"):
            assert field in jobs[0]

    def test_pagination(self):
        stubs_p1 = [_stub(i, f"Quant Developer {i}", f"https://mlp.eightfold.ai/careers/job/{i}") for i in range(3)]
        stubs_p2 = [_stub(i, f"Quant Developer {i}", f"https://mlp.eightfold.ai/careers/job/{i}") for i in range(3, 5)]

        page1 = _list_response(stubs_p1, count=5)
        page2 = _list_response(stubs_p2, count=5)
        details = [_detail_response(f"Description {i}") for i in range(5)]

        with patch("requests.get", side_effect=[page1, page2] + details):
            jobs = fetch_jobs("mlp.com", "London")

        assert len(jobs) == 5

    def test_content_truncated_at_6000(self):
        stub = _stub(1001, "Algo Trading Developer", "https://mlp.eightfold.ai/careers/job/1001")
        long_desc = "<p>" + "x" * 8000 + "</p>"
        with patch("requests.get", side_effect=[_list_response([stub]), _detail_response(long_desc)]):
            jobs = fetch_jobs("mlp.com", "London")

        assert len(jobs[0]["content"]) == 6000


    def test_irrelevant_title_filtered_out(self):
        stub = _stub(9001, "Product Manager", "https://mlp.eightfold.ai/careers/job/9001")
        with patch("requests.get", side_effect=[_list_response([stub])]):
            jobs = fetch_jobs("mlp.com", "London")
        assert jobs == []

    def test_blocklisted_title_filtered_out(self):
        stub = _stub(9002, "Graduate Quant Researcher", "https://mlp.eightfold.ai/careers/job/9002")
        with patch("requests.get", side_effect=[_list_response([stub])]):
            jobs = fetch_jobs("mlp.com", "London")
        assert jobs == []


class TestFetchContent:
    def test_strips_html(self):
        mock = _detail_response("<p>Hello <strong>world</strong></p>")
        with patch("requests.get", return_value=mock):
            result = _fetch_content("https://mlp.eightfold.ai/api/apply/v2/jobs", "mlp.com", 1001)
        assert "<p>" not in result
        assert "Hello" in result

    def test_http_error_returns_empty(self):
        import requests
        with patch("requests.get", side_effect=requests.RequestException("timeout")):
            result = _fetch_content("https://mlp.eightfold.ai/api/apply/v2/jobs", "mlp.com", 1001)
        assert result == ""

    def test_missing_description_returns_empty(self):
        mock = MagicMock()
        mock.json.return_value = {}
        with patch("requests.get", return_value=mock):
            result = _fetch_content("https://mlp.eightfold.ai/api/apply/v2/jobs", "mlp.com", 1001)
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
