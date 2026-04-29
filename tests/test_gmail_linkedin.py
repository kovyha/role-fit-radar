import pytest
from unittest.mock import patch, AsyncMock

from sources.gmail_linkedin import _parse_email_for_jobs


class TestParseEmailForJobs:
    """Tests for _parse_email_for_jobs() — pure parsing without mocking."""

    def test_parse_email_finds_jobs(self, create_email_message, linkedin_email_html):
        """LinkedIn job URLs are extracted from email HTML."""
        msg = create_email_message(linkedin_email_html)

        jobs = _parse_email_for_jobs(msg)

        assert len(jobs) == 3
        urls = [j['url'] for j in jobs]
        assert "https://www.linkedin.com/jobs/view/123456/" in urls
        assert "https://www.linkedin.com/jobs/view/789012/" in urls
        assert "https://www.linkedin.com/jobs/view/345678/" in urls

    def test_parse_email_strips_query_params(self, create_email_message, linkedin_email_html):
        """Query parameters are stripped from job URLs."""
        msg = create_email_message(linkedin_email_html)

        jobs = _parse_email_for_jobs(msg)

        # URLs should not contain trackingId parameter
        for job in jobs:
            assert "trackingId" not in job['url']
            assert "?" not in job['url']

    def test_parse_email_no_linkedin_links(self, create_email_message, linkedin_email_no_jobs_html):
        """Email without LinkedIn job links returns empty list."""
        msg = create_email_message(linkedin_email_no_jobs_html)

        jobs = _parse_email_for_jobs(msg)

        assert jobs == []

    def test_parse_email_multipart(self, create_email_message, linkedin_email_html):
        """Multipart email with text and HTML picks the HTML part."""
        msg = create_email_message(linkedin_email_html, is_multipart=True)

        jobs = _parse_email_for_jobs(msg)

        # Should extract jobs from HTML, not fail on multipart
        assert len(jobs) == 3

    def test_parse_email_extracts_title(self, create_email_message, linkedin_email_html):
        """Job title is extracted from link text."""
        msg = create_email_message(linkedin_email_html)

        jobs = _parse_email_for_jobs(msg)

        assert any(j['title'] == "Senior Software Engineer" for j in jobs)
        assert any(j['title'] == "Product Manager" for j in jobs)

    def test_parse_email_extracts_company(self, create_email_message, linkedin_email_html):
        """Company name is extracted from email card."""
        msg = create_email_message(linkedin_email_html)

        jobs = _parse_email_for_jobs(msg)

        assert any(j['company'] == "Google" for j in jobs)
        assert any(j['company'] == "Microsoft" for j in jobs)

    def test_parse_email_extracts_location(self, create_email_message, linkedin_email_html):
        """Location is extracted from email card."""
        msg = create_email_message(linkedin_email_html)

        jobs = _parse_email_for_jobs(msg)

        locations = [j['location'] for j in jobs]
        assert "London, UK" in locations
        assert "San Francisco, CA" in locations

    def test_parse_email_requires_linkedin_url(self, create_email_message):
        """Only links matching linkedin.com/jobs/view/ are considered job links."""
        html = """
        <html>
        <body>
            <a href="https://www.linkedin.com/jobs/view/123/">Valid Job</a>
            <a href="https://www.linkedin.com/feed/">Not a Job</a>
            <a href="https://www.google.com/">External Link</a>
        </body>
        </html>
        """
        msg = create_email_message(html)

        jobs = _parse_email_for_jobs(msg)

        assert len(jobs) == 1
        assert "view/123/" in jobs[0]['url']

    def test_parse_email_strips_middle_dot_from_title(self, create_email_message):
        """LinkedIn emails sometimes concatenate 'Title · Company · Location' without line breaks."""
        html = """
        <html><body>
            <div><a href="https://www.linkedin.com/jobs/view/555/">Senior Quant Dev · Goldman Sachs · London</a></div>
        </body></html>
        """
        msg = create_email_message(html)

        jobs = _parse_email_for_jobs(msg)

        assert len(jobs) == 1
        assert jobs[0]["title"] == "Senior Quant Dev"


FAKE_ENV = {"GMAIL_USER": "test@gmail.com", "GMAIL_APP_PASSWORD": "testpassword"}


class TestFetchJobsIMAP:
    """Tests for fetch_jobs() IMAP flow with mocking."""

    @patch.dict('os.environ', FAKE_ENV)
    @patch('sources.gmail_linkedin.imaplib.IMAP4_SSL')
    @patch('sources.gmail_linkedin._fetch_job_description')
    def test_fetch_jobs_label_found(self, mock_fetch_desc, mock_imap_class, mock_imap_connection, linkedin_email_html, create_email_message):
        """Jobs are returned when label is found."""
        mock_imap = mock_imap_connection
        mock_imap_class.return_value = mock_imap

        test_msg = create_email_message(linkedin_email_html)
        msg_bytes = test_msg.as_bytes()
        mock_imap.fetch.return_value = ('OK', [(None, msg_bytes)])
        mock_fetch_desc.return_value = {"content": "Job description content", "company": "", "location": ""}

        from sources.gmail_linkedin import fetch_jobs
        jobs = fetch_jobs()

        assert len(jobs) > 0
        assert mock_imap.store.called

    @patch.dict('os.environ', FAKE_ENV)
    @patch('sources.gmail_linkedin.imaplib.IMAP4_SSL')
    def test_fetch_jobs_label_missing(self, mock_imap_class, mock_imap_connection):
        """Missing label returns empty list."""
        mock_imap = mock_imap_connection
        mock_imap.list.return_value = (
            'OK',
            [
                b'(\\All \\HasNoChildren) "/" "INBOX"',
                b'(\\HasNoChildren) "/" "[Gmail]/All Mail"'
            ]
        )
        mock_imap_class.return_value = mock_imap

        from sources.gmail_linkedin import fetch_jobs
        jobs = fetch_jobs()

        assert jobs == []
        assert mock_imap.close.called
        assert mock_imap.logout.called

    @patch.dict('os.environ', FAKE_ENV)
    @patch('sources.gmail_linkedin.imaplib.IMAP4_SSL')
    def test_fetch_jobs_no_messages(self, mock_imap_class, mock_imap_connection):
        """Empty search result returns empty list."""
        mock_imap = mock_imap_connection
        mock_imap.search.return_value = ('OK', [b''])
        mock_imap_class.return_value = mock_imap

        from sources.gmail_linkedin import fetch_jobs
        jobs = fetch_jobs()

        assert jobs == []

    @patch('sources.gmail_linkedin.imaplib.IMAP4_SSL')
    def test_fetch_jobs_imap_error(self, mock_imap_class):
        """IMAP connection error returns empty list."""
        mock_imap_class.side_effect = Exception("IMAP connection failed")

        from sources.gmail_linkedin import fetch_jobs
        jobs = fetch_jobs()

        assert jobs == []

    def test_fetch_jobs_missing_credentials(self):
        """Missing credentials returns empty list before connecting."""
        with patch.dict('os.environ', {}, clear=True):
            from sources.gmail_linkedin import fetch_jobs
            jobs = fetch_jobs()
            assert jobs == []

    @patch.dict('os.environ', {"GMAIL_USER": "test@gmail.com", "GMAIL_APP_PASSWORD": "abcd efgh ijkl mnop"})
    @patch('sources.gmail_linkedin.imaplib.IMAP4_SSL')
    def test_fetch_jobs_strips_spaces_from_app_password(self, mock_imap_class, mock_imap_connection):
        """App password spaces are stripped before IMAP login (Google formats them as 'xxxx xxxx xxxx xxxx')."""
        mock_imap = mock_imap_connection
        mock_imap_class.return_value = mock_imap
        mock_imap.search.return_value = ('OK', [b''])

        from sources.gmail_linkedin import fetch_jobs
        fetch_jobs()

        args, _ = mock_imap.login.call_args
        assert args[1] == "abcdefghijklmnop"

    @patch.dict('os.environ', FAKE_ENV)
    @patch('sources.gmail_linkedin.imaplib.IMAP4_SSL')
    def test_fetch_jobs_list_not_ok(self, mock_imap_class, mock_imap_connection):
        """mail.list() non-OK status closes connection and returns empty list."""
        mock_imap = mock_imap_connection
        mock_imap.list.return_value = ('FAIL', [])
        mock_imap_class.return_value = mock_imap

        from sources.gmail_linkedin import fetch_jobs
        jobs = fetch_jobs()

        assert jobs == []
        assert mock_imap.close.called
        assert mock_imap.logout.called

    @patch.dict('os.environ', FAKE_ENV)
    @patch('sources.gmail_linkedin.imaplib.IMAP4_SSL')
    def test_fetch_jobs_select_not_ok(self, mock_imap_class, mock_imap_connection):
        """mail.select() non-OK status closes connection and returns empty list."""
        mock_imap = mock_imap_connection
        mock_imap.select.return_value = ('FAIL', [])
        mock_imap_class.return_value = mock_imap

        from sources.gmail_linkedin import fetch_jobs
        jobs = fetch_jobs()

        assert jobs == []
        assert mock_imap.close.called
        assert mock_imap.logout.called

    @patch.dict('os.environ', FAKE_ENV)
    @patch('sources.gmail_linkedin.imaplib.IMAP4_SSL')
    @patch('sources.gmail_linkedin._fetch_job_description')
    def test_fetch_jobs_enriches_company_and_location(self, mock_fetch_desc, mock_imap_class, mock_imap_connection, linkedin_email_html, create_email_message):
        """Non-empty company/location from description fetch overwrite the email stub values."""
        mock_imap = mock_imap_connection
        mock_imap_class.return_value = mock_imap
        test_msg = create_email_message(linkedin_email_html)
        mock_imap.fetch.return_value = ('OK', [(None, test_msg.as_bytes())])
        mock_fetch_desc.return_value = {
            "content": "Full job description",
            "company": "DeepMind",
            "location": "Zurich",
        }

        from sources.gmail_linkedin import fetch_jobs
        jobs = fetch_jobs()

        assert len(jobs) > 0
        assert all(j["company"] == "DeepMind" for j in jobs)
        assert all(j["location"] == "Zurich" for j in jobs)


class TestFetchJobDescription:
    """Tests for _fetch_job_description() sync wrapper."""

    def test_returns_data_from_async(self):
        """Sync wrapper returns result from the async fetch."""
        with patch("sources.gmail_linkedin._fetch_description_async", new_callable=AsyncMock) as mock_async:
            mock_async.return_value = {"content": "Build algos.", "company": "HSBC", "location": "London"}
            from sources.gmail_linkedin import _fetch_job_description
            result = _fetch_job_description("https://www.linkedin.com/jobs/view/999/")
        assert result["content"] == "Build algos."
        assert result["company"] == "HSBC"

    def test_exception_returns_empty_dict(self):
        """Exception in async fetch returns safe empty dict without raising."""
        with patch("sources.gmail_linkedin._fetch_description_async", new_callable=AsyncMock) as mock_async:
            mock_async.side_effect = Exception("network error")
            from sources.gmail_linkedin import _fetch_job_description
            result = _fetch_job_description("https://www.linkedin.com/jobs/view/999/")
        assert result == {"content": "", "company": "", "location": ""}


class TestFetchDescriptionAsync:
    """Tests for _fetch_description_async() LinkedIn Playwright scraper."""

    def _make_playwright_mock(self):
        mock_browser = AsyncMock()
        mock_context = AsyncMock()
        mock_page = AsyncMock()
        mock_p = AsyncMock()
        mock_browser.new_context.return_value = mock_context
        mock_context.new_page.return_value = mock_page
        return mock_p, mock_browser, mock_context, mock_page

    @pytest.mark.asyncio
    async def test_returns_content_company_location(self):
        """Happy path: extracts description, company, and location from the page."""
        with patch("sources.gmail_linkedin.async_playwright") as mock_pw:
            mock_p, mock_browser, mock_context, mock_page = self._make_playwright_mock()
            mock_pw.return_value.__aenter__.return_value = mock_p
            mock_p.chromium.launch.return_value = mock_browser
            mock_page.evaluate.return_value = {
                "description": "Build execution algorithms.",
                "company": "Goldman Sachs",
                "location": "London",
            }

            from sources.gmail_linkedin import _fetch_description_async
            result = await _fetch_description_async("https://www.linkedin.com/jobs/view/123/")

        assert result["content"] == "Build execution algorithms."
        assert result["company"] == "Goldman Sachs"
        assert result["location"] == "London"

    @pytest.mark.asyncio
    async def test_playwright_error_returns_empty_dict(self):
        """Playwright launch failure returns safe empty dict without raising."""
        with patch("sources.gmail_linkedin.async_playwright") as mock_pw:
            mock_pw.return_value.__aenter__.side_effect = Exception("Browser launch failed")

            from sources.gmail_linkedin import _fetch_description_async
            result = await _fetch_description_async("https://www.linkedin.com/jobs/view/123/")

        assert result == {"content": "", "company": "", "location": ""}

    @pytest.mark.asyncio
    async def test_content_truncated_to_max_chars(self):
        """Description longer than JOB_CONTENT_MAX_CHARS is truncated."""
        with patch("sources.gmail_linkedin.async_playwright") as mock_pw:
            mock_p, mock_browser, mock_context, mock_page = self._make_playwright_mock()
            mock_pw.return_value.__aenter__.return_value = mock_p
            mock_p.chromium.launch.return_value = mock_browser
            mock_page.evaluate.return_value = {
                "description": "x" * 10000,
                "company": "",
                "location": "",
            }

            from sources.gmail_linkedin import _fetch_description_async
            result = await _fetch_description_async("https://www.linkedin.com/jobs/view/123/")

        assert len(result["content"]) == 6000
