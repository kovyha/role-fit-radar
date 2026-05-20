import pytest
from unittest.mock import patch, AsyncMock

from sources.oracle_hcm import (
    fetch_jobs,
    _extract_content,
    _strip_html,
    _discover_location_id,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

_FACETS_DATA = {
    "items": [{
        "TotalJobsCount": 808,
        "locationsFacet": [
            {"Id": 300000057005324, "Name": "LONDON, United Kingdom", "TotalCount": 498},
            {"Id": 300000057007721, "Name": "LONDON, LONDON, United Kingdom", "TotalCount": 310},
            {"Id": 300000000289738, "Name": "United States", "TotalCount": 5127},
        ],
        "requisitionList": [],
    }]
}

_LIST_DATA = {
    "items": [{
        "TotalJobsCount": 1,
        "requisitionList": [{
            "Id": "210123456",
            "Title": "Algo Trading Engineer",
            "PrimaryLocation": "LONDON, United Kingdom",
            "Department": "Electronic Trading",
        }],
    }]
}

_DETAIL_DATA = {
    "items": [{
        "ExternalDescriptionStr": "<p>Build execution algos.</p>",
        "ExternalResponsibilitiesStr": "<p>Own the trading stack.</p>",
        "ExternalQualificationsStr": "<p>5+ years C++.</p>",
    }]
}


def _make_mock_context(facets_resp, list_resp, detail_resp):
    """Return a context mock whose request.get returns responses in sequence."""
    def make_resp(data):
        r = AsyncMock()
        r.ok = True
        r.status = 200
        r.json = AsyncMock(return_value=data)
        return r

    mock_context = AsyncMock()
    mock_context.request.get = AsyncMock(side_effect=[
        make_resp(facets_resp),
        make_resp(list_resp),
        make_resp(detail_resp),
    ])
    return mock_context


def _make_pw_mock(context):
    mock_page = AsyncMock()
    mock_browser = AsyncMock()
    mock_browser.new_context = AsyncMock(return_value=context)
    context.new_page = AsyncMock(return_value=mock_page)

    mock_p = AsyncMock()
    mock_p.chromium.launch = AsyncMock(return_value=mock_browser)
    return mock_p


# ── Unit tests for pure helpers ───────────────────────────────────────────────

class TestExtractContent:
    def test_combines_desc_responsibilities_qualifications(self):
        data = {
            "items": [{
                "ExternalDescriptionStr": "<p>Build algos.</p>",
                "ExternalResponsibilitiesStr": "<p>Own the stack.</p>",
                "ExternalQualificationsStr": "<p>5+ years C++.</p>",
            }]
        }
        result = _extract_content(data)
        assert "Build algos" in result
        assert "Own the stack" in result
        assert "5+ years C++" in result
        assert "<p>" not in result

    def test_missing_fields_returns_available(self):
        data = {"items": [{"ExternalDescriptionStr": "<p>Hello.</p>"}]}
        assert "Hello" in _extract_content(data)

    def test_empty_items_returns_empty(self):
        assert _extract_content({"items": []}) == ""

    def test_none_fields_ignored(self):
        data = {"items": [{"ExternalDescriptionStr": None, "ExternalResponsibilitiesStr": "<p>Resp.</p>"}]}
        assert "Resp" in _extract_content(data)

    def test_truncates_at_6000(self):
        data = {"items": [{"ExternalDescriptionStr": "<p>" + "x" * 8000 + "</p>"}]}
        assert len(_extract_content(data)) == 6000


class TestDiscoverLocationId:
    @pytest.mark.asyncio
    async def test_finds_city_level_parent(self):
        mock_context = AsyncMock()
        resp = AsyncMock()
        resp.ok = True
        resp.json = AsyncMock(return_value=_FACETS_DATA)
        mock_context.request.get = AsyncMock(return_value=resp)

        result = await _discover_location_id(mock_context, "https://x.com/api", "CX_1001", "London")
        assert result == "300000057005324"  # fewest parts = LONDON, United Kingdom

    @pytest.mark.asyncio
    async def test_case_insensitive(self):
        mock_context = AsyncMock()
        resp = AsyncMock()
        resp.ok = True
        resp.json = AsyncMock(return_value=_FACETS_DATA)
        mock_context.request.get = AsyncMock(return_value=resp)

        result = await _discover_location_id(mock_context, "https://x.com/api", "CX_1001", "london")
        assert result == "300000057005324"

    @pytest.mark.asyncio
    async def test_no_match_returns_none(self):
        mock_context = AsyncMock()
        resp = AsyncMock()
        resp.ok = True
        resp.json = AsyncMock(return_value=_FACETS_DATA)
        mock_context.request.get = AsyncMock(return_value=resp)

        result = await _discover_location_id(mock_context, "https://x.com/api", "CX_1001", "Tokyo")
        assert result is None

    @pytest.mark.asyncio
    async def test_api_error_returns_none(self):
        mock_context = AsyncMock()
        resp = AsyncMock()
        resp.ok = False
        mock_context.request.get = AsyncMock(return_value=resp)

        result = await _discover_location_id(mock_context, "https://x.com/api", "CX_1001", "London")
        assert result is None

    @pytest.mark.asyncio
    async def test_network_exception_returns_none(self):
        mock_context = AsyncMock()
        mock_context.request.get = AsyncMock(side_effect=Exception("timeout"))

        result = await _discover_location_id(mock_context, "https://x.com/api", "CX_1001", "London")
        assert result is None


class TestStripHtml:
    def test_strips_tags(self):
        assert "<p>" not in _strip_html("<p>Hello</p>")
        assert "Hello" in _strip_html("<p>Hello</p>")

    def test_handles_entity_encoded_html(self):
        assert "Hello" in _strip_html("&lt;p&gt;Hello&lt;/p&gt;")

    def test_empty_string(self):
        assert _strip_html("") == ""

    def test_none(self):
        assert _strip_html(None) == ""


# ── Integration tests (Playwright path) ──────────────────────────────────────

class TestFetchJobsAsync:
    @pytest.mark.asyncio
    async def test_returns_filtered_jobs_with_content(self):
        mock_context = _make_mock_context(_FACETS_DATA, _LIST_DATA, _DETAIL_DATA)
        mock_p = _make_pw_mock(mock_context)

        with patch("sources.oracle_hcm.async_playwright") as pw:
            pw.return_value.__aenter__ = AsyncMock(return_value=mock_p)
            pw.return_value.__aexit__ = AsyncMock(return_value=False)
            from sources.oracle_hcm import _fetch_jobs_async
            jobs = await _fetch_jobs_async(
                "jpmc.fa.oraclecloud.com", "CX_1001", "London", set(),
                frozenset(["algo"]), frozenset(),
            )

        assert len(jobs) == 1
        assert jobs[0]["title"] == "Algo Trading Engineer"
        assert "Build execution algos" in jobs[0]["content"]
        assert "<p>" not in jobs[0]["content"]

    @pytest.mark.asyncio
    async def test_all_required_fields_present(self):
        mock_context = _make_mock_context(_FACETS_DATA, _LIST_DATA, _DETAIL_DATA)
        mock_p = _make_pw_mock(mock_context)

        with patch("sources.oracle_hcm.async_playwright") as pw:
            pw.return_value.__aenter__ = AsyncMock(return_value=mock_p)
            pw.return_value.__aexit__ = AsyncMock(return_value=False)
            from sources.oracle_hcm import _fetch_jobs_async
            jobs = await _fetch_jobs_async(
                "jpmc.fa.oraclecloud.com", "CX_1001", "London", set(),
                frozenset(["algo"]), frozenset(),
            )

        assert len(jobs) == 1
        for field in ("title", "url", "location", "department", "content"):
            assert field in jobs[0]

    @pytest.mark.asyncio
    async def test_seen_url_skips_detail_fetch(self):
        mock_context = _make_mock_context(_FACETS_DATA, _LIST_DATA, _DETAIL_DATA)
        mock_p = _make_pw_mock(mock_context)
        seen = {"https://jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/job/210123456"}

        with patch("sources.oracle_hcm.async_playwright") as pw:
            pw.return_value.__aenter__ = AsyncMock(return_value=mock_p)
            pw.return_value.__aexit__ = AsyncMock(return_value=False)
            from sources.oracle_hcm import _fetch_jobs_async
            jobs = await _fetch_jobs_async(
                "jpmc.fa.oraclecloud.com", "CX_1001", "London", seen,
                frozenset(["algo"]), frozenset(),
            )

        assert jobs == []
        assert mock_context.request.get.call_count == 2  # facets + list; no detail

    @pytest.mark.asyncio
    async def test_irrelevant_title_filtered_out(self):
        mock_context = _make_mock_context(_FACETS_DATA, _LIST_DATA, _DETAIL_DATA)
        mock_p = _make_pw_mock(mock_context)

        with patch("sources.oracle_hcm.async_playwright") as pw:
            pw.return_value.__aenter__ = AsyncMock(return_value=mock_p)
            pw.return_value.__aexit__ = AsyncMock(return_value=False)
            from sources.oracle_hcm import _fetch_jobs_async
            jobs = await _fetch_jobs_async(
                "jpmc.fa.oraclecloud.com", "CX_1001", "London", set(),
                frozenset(["quant"]),   # "algo" doesn't match "quant" allowlist
                frozenset(),
            )

        assert jobs == []
        assert mock_context.request.get.call_count == 2  # no detail call

    @pytest.mark.asyncio
    async def test_blocklisted_title_filtered_out(self):
        mock_context = _make_mock_context(_FACETS_DATA, _LIST_DATA, _DETAIL_DATA)
        mock_p = _make_pw_mock(mock_context)

        with patch("sources.oracle_hcm.async_playwright") as pw:
            pw.return_value.__aenter__ = AsyncMock(return_value=mock_p)
            pw.return_value.__aexit__ = AsyncMock(return_value=False)
            from sources.oracle_hcm import _fetch_jobs_async
            jobs = await _fetch_jobs_async(
                "jpmc.fa.oraclecloud.com", "CX_1001", "London", set(),
                frozenset(["algo"]), frozenset(["engineer"]),  # blocklist matches title
            )

        assert jobs == []

    @pytest.mark.asyncio
    async def test_no_location_match_returns_empty(self):
        facets_no_match = {"items": [{"TotalJobsCount": 0, "locationsFacet": [], "requisitionList": []}]}
        mock_context = _make_mock_context(facets_no_match, {}, {})
        mock_p = _make_pw_mock(mock_context)

        with patch("sources.oracle_hcm.async_playwright") as pw:
            pw.return_value.__aenter__ = AsyncMock(return_value=mock_p)
            pw.return_value.__aexit__ = AsyncMock(return_value=False)
            from sources.oracle_hcm import _fetch_jobs_async
            jobs = await _fetch_jobs_async(
                "jpmc.fa.oraclecloud.com", "CX_1001", "Tokyo", set(),
                frozenset(["algo"]), frozenset(),
            )

        assert jobs == []

    @pytest.mark.asyncio
    async def test_careers_page_error_returns_empty(self):
        mock_page = AsyncMock()
        mock_page.goto.side_effect = Exception("Navigation timeout")
        mock_context = AsyncMock()
        mock_context.new_page = AsyncMock(return_value=mock_page)
        mock_browser = AsyncMock()
        mock_browser.new_context = AsyncMock(return_value=mock_context)
        mock_p = AsyncMock()
        mock_p.chromium.launch = AsyncMock(return_value=mock_browser)

        with patch("sources.oracle_hcm.async_playwright") as pw:
            pw.return_value.__aenter__ = AsyncMock(return_value=mock_p)
            pw.return_value.__aexit__ = AsyncMock(return_value=False)
            from sources.oracle_hcm import _fetch_jobs_async
            jobs = await _fetch_jobs_async(
                "jpmc.fa.oraclecloud.com", "CX_1001", "London", set(),
                frozenset(["algo"]), frozenset(),
            )

        assert jobs == []

    @pytest.mark.asyncio
    async def test_list_api_error_returns_empty(self):
        def make_resp(ok, data=None):
            r = AsyncMock()
            r.ok = ok
            r.status = 200 if ok else 403
            if data is not None:
                r.json = AsyncMock(return_value=data)
            return r

        mock_context = AsyncMock()
        mock_context.request.get = AsyncMock(side_effect=[
            make_resp(True, _FACETS_DATA),   # facets OK
            make_resp(False),                 # list fails
        ])
        mock_p = _make_pw_mock(mock_context)

        with patch("sources.oracle_hcm.async_playwright") as pw:
            pw.return_value.__aenter__ = AsyncMock(return_value=mock_p)
            pw.return_value.__aexit__ = AsyncMock(return_value=False)
            from sources.oracle_hcm import _fetch_jobs_async
            jobs = await _fetch_jobs_async(
                "jpmc.fa.oraclecloud.com", "CX_1001", "London", set(),
                frozenset(["algo"]), frozenset(),
            )

        assert jobs == []

    def test_fetch_jobs_sync_wrapper(self):
        with patch("sources.oracle_hcm._fetch_jobs_async") as mock_async:
            mock_async.return_value = []
            fetch_jobs("jpmc.fa.oraclecloud.com", "CX_1001", "London")
            mock_async.assert_called_once()
