import pytest
from unittest.mock import patch, AsyncMock


def _make_browser_mock():
    """Create a browser mock with context → page chain."""
    mock_page = AsyncMock()
    mock_context = AsyncMock()
    mock_browser = AsyncMock()
    mock_context.new_page.return_value = mock_page
    mock_browser.new_context.return_value = mock_context
    return mock_browser, mock_context, mock_page


class TestFetchJobsAsync:
    """Tests for sources.efinancialcareers.fetch_jobs()"""

    @pytest.mark.asyncio
    async def test_fetch_jobs_returns_results(self):
        """Jobs returned from page are formatted correctly."""
        with patch('sources.efinancialcareers.async_playwright') as mock_pw:
            mock_browser, mock_context, mock_page = _make_browser_mock()
            mock_p = AsyncMock()
            mock_pw.return_value.__aenter__.return_value = mock_p
            mock_p.chromium.launch.return_value = mock_browser

            mock_job_elem = AsyncMock()
            mock_page.query_selector_all.return_value = [mock_job_elem]

            async def mock_elem_evaluate(js_code):
                if "href" in js_code:
                    return "https://www.efinancialcareers.co.uk/jobs/123456"
                elif "company" in js_code:
                    return "Goldman Sachs"
                elif "location" in js_code:
                    return "London"
                elif "textContent" in js_code:
                    return "Senior Quant Developer"
                return ""

            mock_job_elem.evaluate.side_effect = mock_elem_evaluate
            mock_page.evaluate.return_value = "Job description text"

            from sources.efinancialcareers import _fetch_jobs_async
            jobs, _ = await _fetch_jobs_async("London", set())

            assert len(jobs) > 0
            job = jobs[0]
            assert job['title'] == "Senior Quant Developer"
            assert job['url'] == "https://www.efinancialcareers.co.uk/jobs/123456"
            assert job['company'] == "Goldman Sachs"
            assert job['location'] == "London"

    @pytest.mark.asyncio
    async def test_fetch_jobs_deduplicates_across_keywords(self):
        """Duplicate URLs from different keywords appear only once."""
        with patch('sources.efinancialcareers.async_playwright') as mock_pw:
            mock_browser, mock_context, mock_page = _make_browser_mock()
            mock_p = AsyncMock()
            mock_pw.return_value.__aenter__.return_value = mock_p
            mock_p.chromium.launch.return_value = mock_browser

            same_url = "https://www.efinancialcareers.co.uk/jobs/99999"

            mock_job_elem = AsyncMock()

            async def mock_elem_evaluate(js_code):
                if "href" in js_code:
                    return same_url
                elif "title" in js_code:
                    return "Quant Dev Role"
                return ""

            mock_job_elem.evaluate.side_effect = mock_elem_evaluate
            # Same element returned for every keyword
            mock_page.query_selector_all.return_value = [mock_job_elem]
            mock_page.evaluate.return_value = "Description"

            from sources.efinancialcareers import _fetch_jobs_async
            jobs, _ = await _fetch_jobs_async("London", set())

            assert len(jobs) == 1
            assert jobs[0]['url'] == same_url

    @pytest.mark.asyncio
    async def test_fetch_jobs_empty_page(self):
        """Empty page returns empty list."""
        with patch('sources.efinancialcareers.async_playwright') as mock_pw:
            mock_browser, mock_context, mock_page = _make_browser_mock()
            mock_p = AsyncMock()
            mock_pw.return_value.__aenter__.return_value = mock_p
            mock_p.chromium.launch.return_value = mock_browser

            mock_page.query_selector_all.return_value = []

            from sources.efinancialcareers import _fetch_jobs_async
            jobs, _ = await _fetch_jobs_async("London", set())

            assert jobs == []

    @pytest.mark.asyncio
    async def test_fetch_jobs_playwright_error(self):
        """Browser launch error returns empty list."""
        with patch('sources.efinancialcareers.async_playwright') as mock_pw:
            mock_pw.return_value.__aenter__.side_effect = Exception("Browser launch failed")

            from sources.efinancialcareers import _fetch_jobs_async
            jobs, _ = await _fetch_jobs_async("London", set())

            assert jobs == []

    @pytest.mark.asyncio
    async def test_fetch_jobs_url_uses_path_based_format(self):
        """eFC requires keyword in the URL path — ?keyword= is silently ignored by the SPA."""
        with patch('sources.efinancialcareers.async_playwright') as mock_pw:
            mock_browser, mock_context, mock_page = _make_browser_mock()
            mock_p = AsyncMock()
            mock_pw.return_value.__aenter__.return_value = mock_p
            mock_p.chromium.launch.return_value = mock_browser

            mock_page.query_selector_all.return_value = []

            from sources.efinancialcareers import _fetch_jobs_async
            from config import TITLE_TERMS
            await _fetch_jobs_async("London", set())

            first_url = mock_page.goto.call_args_list[0][0][0]
            # Keyword must appear in the URL path segment, not as a ?keyword= param
            assert "?keyword=" not in first_url
            assert "/jobs/" in first_url
            # q= param must contain a URL-encoded term from TITLE_TERMS
            assert any(f"q={term.replace(' ', '%20')}" in first_url for term in TITLE_TERMS)
            # Pagination starts at page 1
            assert "page=1" in first_url

    @pytest.mark.asyncio
    async def test_fetch_jobs_location_in_url(self):
        """location_filter is embedded in the navigated URL for each keyword."""
        with patch('sources.efinancialcareers.async_playwright') as mock_pw:
            mock_browser, mock_context, mock_page = _make_browser_mock()
            mock_p = AsyncMock()
            mock_pw.return_value.__aenter__.return_value = mock_p
            mock_p.chromium.launch.return_value = mock_browser

            mock_page.query_selector_all.return_value = []

            from sources.efinancialcareers import _fetch_jobs_async
            await _fetch_jobs_async("London", set())

            assert mock_page.goto.called
            url = mock_page.goto.call_args_list[0][0][0]
            assert "location=London" in url

    @pytest.mark.asyncio
    async def test_fetch_jobs_custom_location(self):
        """Custom location is used instead of default."""
        with patch('sources.efinancialcareers.async_playwright') as mock_pw:
            mock_browser, mock_context, mock_page = _make_browser_mock()
            mock_p = AsyncMock()
            mock_pw.return_value.__aenter__.return_value = mock_p
            mock_p.chromium.launch.return_value = mock_browser

            mock_page.query_selector_all.return_value = []

            from sources.efinancialcareers import _fetch_jobs_async
            await _fetch_jobs_async("Manchester", set())

            assert mock_page.goto.called
            url = mock_page.goto.call_args_list[0][0][0]
            assert "location=Manchester" in url
            assert "location=London" not in url

    @pytest.mark.asyncio
    async def test_fetch_jobs_url_encodes_keywords(self):
        """Keywords with spaces are percent-encoded in both the path and q= param."""
        with patch('sources.efinancialcareers.async_playwright') as mock_pw:
            mock_browser, mock_context, mock_page = _make_browser_mock()
            mock_p = AsyncMock()
            mock_pw.return_value.__aenter__.return_value = mock_p
            mock_p.chromium.launch.return_value = mock_browser

            mock_page.query_selector_all.return_value = []

            # Pass a multi-word term explicitly to test encoding
            from sources.efinancialcareers import _fetch_jobs_async
            await _fetch_jobs_async("London", set(), search_terms=frozenset(["low latency"]))

            first_url = mock_page.goto.call_args_list[0][0][0]
            assert "low-latency" in first_url       # path slug: spaces → hyphens
            assert "q=low%20latency" in first_url   # q= param: spaces → %20
            assert "low latency" not in first_url   # no raw spaces anywhere

    @pytest.mark.asyncio
    async def test_fetch_jobs_sets_user_agent_via_headers(self):
        """User-Agent is set via set_extra_http_headers rather than new_context(user_agent=...)."""
        with patch('sources.efinancialcareers.async_playwright') as mock_pw:
            mock_browser, mock_context, mock_page = _make_browser_mock()
            mock_p = AsyncMock()
            mock_pw.return_value.__aenter__.return_value = mock_p
            mock_p.chromium.launch.return_value = mock_browser

            mock_page.query_selector_all.return_value = []

            from sources.efinancialcareers import _fetch_jobs_async
            await _fetch_jobs_async("London", set())

            _, ctx_kwargs = mock_browser.new_context.call_args
            assert "user_agent" not in ctx_kwargs

            mock_page.set_extra_http_headers.assert_called()
            headers, _ = mock_page.set_extra_http_headers.call_args
            assert "User-Agent" in headers[0]

    def test_fetch_jobs_sync_wrapper(self):
        """fetch_jobs() wrapper runs async function and returns results."""
        expected_jobs = [
            {
                "title": "Quant Role",
                "url": "https://example.com/job1",
                "location": "London",
                "company": "Test Corp",
                "department": "",
                "content": "Description"
            }
        ]

        with patch('sources.efinancialcareers._fetch_jobs_async') as mock_async:
            mock_async.return_value = (expected_jobs, len(expected_jobs))

            from sources.efinancialcareers import fetch_jobs
            jobs = fetch_jobs("London")

            assert isinstance(jobs, list)
            assert len(jobs) == 1
            assert jobs[0]['title'] == "Quant Role"

    def test_fetch_jobs_handles_errors(self):
        """fetch_jobs() returns empty list on error."""
        with patch('sources.efinancialcareers._fetch_jobs_async') as mock_async:
            mock_async.side_effect = Exception("Test error")

            from sources.efinancialcareers import fetch_jobs
            jobs = fetch_jobs("London")

            assert jobs == []

    def test_all_zeros_populates_out_warnings(self):
        """fetch_jobs appends a warning when all search terms return 0 cards."""
        with patch('sources.efinancialcareers._fetch_jobs_async') as mock_async:
            mock_async.return_value = ([], 0)

            warnings: list[str] = []
            from sources.efinancialcareers import fetch_jobs
            jobs = fetch_jobs("London", search_terms=frozenset(["trading"]), out_warnings=warnings)

            assert jobs == []
            assert len(warnings) == 1
            assert "eFC" in warnings[0]

    def test_no_warning_when_cards_found(self):
        """fetch_jobs does not populate out_warnings when cards were fetched."""
        with patch('sources.efinancialcareers._fetch_jobs_async') as mock_async:
            mock_async.return_value = ([], 5)  # 5 cards found but all filtered/seen

            warnings: list[str] = []
            from sources.efinancialcareers import fetch_jobs
            fetch_jobs("London", search_terms=frozenset(["trading"]), out_warnings=warnings)

            assert warnings == []

    @pytest.mark.asyncio
    async def test_fetch_jobs_page_error_triggers_cleanup(self):
        """page.goto error closes page and context before breaking the keyword loop."""
        with patch('sources.efinancialcareers.async_playwright') as mock_pw:
            mock_browser, mock_context, mock_page = _make_browser_mock()
            mock_p = AsyncMock()
            mock_pw.return_value.__aenter__.return_value = mock_p
            mock_p.chromium.launch.return_value = mock_browser

            mock_page.goto.side_effect = Exception("Navigation timeout")

            from sources.efinancialcareers import _fetch_jobs_async
            jobs, _ = await _fetch_jobs_async("London", set())

            assert jobs == []
            mock_page.close.assert_called()
            mock_context.close.assert_called()
