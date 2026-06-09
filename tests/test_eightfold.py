import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from sources.eightfold import fetch_jobs, _fetch_content, _strip_html, _parse_stubs, _parse_description


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
        stub = _stub(1001, "Systematic Trading Developer", "https://mlp.eightfold.ai/careers/job/1001")
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


class TestSharedParsers:
    def test_parse_stubs_extracts_fields(self):
        data = {"positions": [{"id": 1, "name": "Quant Dev", "canonicalPositionUrl": "https://x.com/1",
                                "location": "London", "department": "Tech"}], "count": 1}
        stubs, total = _parse_stubs(data)
        assert total == 1
        assert stubs[0] == {"id": 1, "title": "Quant Dev", "url": "https://x.com/1",
                             "location": "London", "department": "Tech", "first_published": None}

    def test_parse_stubs_empty_positions(self):
        stubs, total = _parse_stubs({"positions": [], "count": 0})
        assert stubs == []
        assert total == 0

    def test_parse_description_strips_html_and_truncates(self):
        detail = {"job_description": "<p>" + "x" * 8000 + "</p>"}
        result = _parse_description(detail)
        assert len(result) == 6000
        assert "<p>" not in result

    def test_parse_description_missing_key(self):
        assert _parse_description({}) == ""

    def test_parse_description_none_value(self):
        assert _parse_description({"job_description": None}) == ""


def _make_pw_mock(list_data: dict, detail_data: dict):
    """Build a minimal async_playwright mock for eightfold Playwright path tests."""
    list_resp = AsyncMock()
    list_resp.ok = True
    list_resp.json = AsyncMock(return_value=list_data)

    detail_resp = AsyncMock()
    detail_resp.ok = True
    detail_resp.json = AsyncMock(return_value=detail_data)

    mock_request = AsyncMock()
    # First call = list, subsequent = detail
    mock_request.get = AsyncMock(side_effect=[list_resp, detail_resp])

    mock_page = AsyncMock()
    mock_context = AsyncMock()
    mock_context.request = mock_request
    mock_context.new_page = AsyncMock(return_value=mock_page)

    mock_browser = AsyncMock()
    mock_browser.new_context = AsyncMock(return_value=mock_context)

    mock_p = AsyncMock()
    mock_p.chromium.launch = AsyncMock(return_value=mock_browser)

    return mock_p, mock_request


def _pcsx_list(positions: list, count: int | None = None) -> dict:
    """Wrap positions in the pcsx/search response envelope."""
    return {"data": {"positions": positions, "count": count if count is not None else len(positions)}}


def _pcsx_detail(description: str) -> dict:
    """Wrap a job description in the pcsx/position_details response envelope."""
    return {"data": {"jobDescription": description}}


def _pcsx_pos(job_id: int, name: str, url_path: str = None, locations: list = None, department: str = "Tech") -> dict:
    return {
        "id": job_id,
        "name": name,
        "positionUrl": url_path or f"/careers/job/{job_id}",
        "locations": locations or ["London, United Kingdom"],
        "department": department,
    }


class TestPlaywrightPath:
    @pytest.mark.asyncio
    async def test_returns_job_with_content(self):
        list_data = _pcsx_list([_pcsx_pos(99, "Algo Trading Engineer", department="Markets")])
        detail_data = _pcsx_detail("<p>Exciting role.</p>")
        mock_p, _ = _make_pw_mock(list_data, detail_data)

        with patch("sources.eightfold.async_playwright") as pw:
            pw.return_value.__aenter__ = AsyncMock(return_value=mock_p)
            pw.return_value.__aexit__ = AsyncMock(return_value=False)
            from sources.eightfold import _fetch_jobs_playwright
            jobs = await _fetch_jobs_playwright("citi.com", "London", set(),
                                                frozenset(["algo"]), frozenset())

        assert len(jobs) == 1
        assert jobs[0]["title"] == "Algo Trading Engineer"
        assert "Exciting role" in jobs[0]["content"]
        assert "<p>" not in jobs[0]["content"]

    @pytest.mark.asyncio
    async def test_seen_url_skips_detail_fetch(self):
        list_data = _pcsx_list([_pcsx_pos(99, "Algo Trading Engineer")])
        mock_p, mock_request = _make_pw_mock(list_data, {})

        with patch("sources.eightfold.async_playwright") as pw:
            pw.return_value.__aenter__ = AsyncMock(return_value=mock_p)
            pw.return_value.__aexit__ = AsyncMock(return_value=False)
            from sources.eightfold import _fetch_jobs_playwright
            jobs = await _fetch_jobs_playwright(
                "citi.com", "London",
                {"https://citi.eightfold.ai/careers/job/99"},
                frozenset(["algo"]), frozenset(),
            )

        assert jobs == []
        assert mock_request.get.call_count == 1  # list only, no detail call

    @pytest.mark.asyncio
    async def test_irrelevant_title_filtered(self):
        list_data = _pcsx_list([_pcsx_pos(99, "Product Manager")])
        mock_p, mock_request = _make_pw_mock(list_data, {})

        with patch("sources.eightfold.async_playwright") as pw:
            pw.return_value.__aenter__ = AsyncMock(return_value=mock_p)
            pw.return_value.__aexit__ = AsyncMock(return_value=False)
            from sources.eightfold import _fetch_jobs_playwright
            jobs = await _fetch_jobs_playwright("citi.com", "London", set(),
                                                frozenset(["algo"]), frozenset())

        assert jobs == []
        assert mock_request.get.call_count == 1  # list only, no detail call

    @pytest.mark.asyncio
    async def test_blocklisted_title_filtered(self):
        list_data = _pcsx_list([_pcsx_pos(99, "Graduate Algo Analyst")])
        mock_p, mock_request = _make_pw_mock(list_data, {})

        with patch("sources.eightfold.async_playwright") as pw:
            pw.return_value.__aenter__ = AsyncMock(return_value=mock_p)
            pw.return_value.__aexit__ = AsyncMock(return_value=False)
            from sources.eightfold import _fetch_jobs_playwright
            jobs = await _fetch_jobs_playwright("citi.com", "London", set(),
                                                frozenset(["algo"]), frozenset(["graduate"]))

        assert jobs == []

    @pytest.mark.asyncio
    async def test_careers_page_error_returns_empty(self):
        mock_p = AsyncMock()
        mock_browser = AsyncMock()
        mock_context = AsyncMock()
        mock_page = AsyncMock()
        mock_page.goto.side_effect = Exception("Navigation timeout")
        mock_context.new_page = AsyncMock(return_value=mock_page)
        mock_browser.new_context = AsyncMock(return_value=mock_context)
        mock_p.chromium.launch = AsyncMock(return_value=mock_browser)

        with patch("sources.eightfold.async_playwright") as pw:
            pw.return_value.__aenter__ = AsyncMock(return_value=mock_p)
            pw.return_value.__aexit__ = AsyncMock(return_value=False)
            from sources.eightfold import _fetch_jobs_playwright
            jobs = await _fetch_jobs_playwright("citi.com", "London", set(),
                                                frozenset(["algo"]), frozenset())

        assert jobs == []

    @pytest.mark.asyncio
    async def test_api_non_ok_returns_empty(self):
        failed_resp = AsyncMock()
        failed_resp.ok = False
        failed_resp.status = 403

        mock_page = AsyncMock()
        mock_request = AsyncMock()
        mock_request.get = AsyncMock(return_value=failed_resp)
        mock_context = AsyncMock()
        mock_context.request = mock_request
        mock_context.new_page = AsyncMock(return_value=mock_page)
        mock_browser = AsyncMock()
        mock_browser.new_context = AsyncMock(return_value=mock_context)
        mock_p = AsyncMock()
        mock_p.chromium.launch = AsyncMock(return_value=mock_browser)

        with patch("sources.eightfold.async_playwright") as pw:
            pw.return_value.__aenter__ = AsyncMock(return_value=mock_p)
            pw.return_value.__aexit__ = AsyncMock(return_value=False)
            from sources.eightfold import _fetch_jobs_playwright
            jobs = await _fetch_jobs_playwright("citi.com", "London", set(),
                                                frozenset(["algo"]), frozenset())

        assert jobs == []

    @pytest.mark.asyncio
    async def test_all_required_fields_present(self):
        list_data = _pcsx_list([_pcsx_pos(42, "Execution Algo Engineer", department="Electronic Trading")])
        detail_data = _pcsx_detail("Responsible for execution algo.")
        mock_p, _ = _make_pw_mock(list_data, detail_data)

        with patch("sources.eightfold.async_playwright") as pw:
            pw.return_value.__aenter__ = AsyncMock(return_value=mock_p)
            pw.return_value.__aexit__ = AsyncMock(return_value=False)
            from sources.eightfold import _fetch_jobs_playwright
            jobs = await _fetch_jobs_playwright("citi.com", "London", set(),
                                                frozenset(["algo", "execution"]), frozenset())

        assert len(jobs) == 1
        for field in ("title", "url", "location", "department", "content"):
            assert field in jobs[0]

    def test_fetch_jobs_sync_wrapper_uses_playwright(self):
        """fetch_jobs(use_playwright=True) delegates to the Playwright async path."""
        with patch("sources.eightfold._fetch_jobs_playwright") as mock_async:
            mock_async.return_value = []
            fetch_jobs("citi.com", "London", use_playwright=True)
            mock_async.assert_called_once()
