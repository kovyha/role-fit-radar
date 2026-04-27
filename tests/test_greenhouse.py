from unittest.mock import patch, MagicMock
from sources.greenhouse import fetch_jobs, _strip_html


class TestFetchJobs:
    """Tests for greenhouse.fetch_jobs()"""

    def test_fetch_jobs_location_match(self, greenhouse_api_response):
        """Jobs matching location filter are returned."""
        with patch('requests.get') as mock_get:
            mock_response = MagicMock()
            mock_response.json.return_value = greenhouse_api_response
            mock_get.return_value = mock_response

            jobs = fetch_jobs("anthropic", "London")

            assert len(jobs) == 1
            assert jobs[0]['title'] == "Senior Software Engineer"
            assert jobs[0]['location'] == "London, UK"
            assert jobs[0]['url'] == "https://www.anthropic.com/careers/1001"

    def test_fetch_jobs_location_no_match(self, greenhouse_api_response):
        """Jobs in non-matching location are filtered out."""
        with patch('requests.get') as mock_get:
            mock_response = MagicMock()
            mock_response.json.return_value = greenhouse_api_response
            mock_get.return_value = mock_response

            jobs = fetch_jobs("anthropic", "Tokyo")

            assert len(jobs) == 0

    def test_fetch_jobs_empty_response(self, greenhouse_api_empty):
        """Empty jobs array returns empty list."""
        with patch('requests.get') as mock_get:
            mock_response = MagicMock()
            mock_response.json.return_value = greenhouse_api_empty
            mock_get.return_value = mock_response

            jobs = fetch_jobs("anthropic", "London")

            assert jobs == []

    def test_fetch_jobs_http_error(self):
        """HTTP error returns empty list."""
        with patch('requests.get') as mock_get:
            import requests
            mock_get.side_effect = requests.RequestException("Connection error")

            jobs = fetch_jobs("anthropic", "London")

            assert jobs == []

    def test_fetch_jobs_html_stripped(self, greenhouse_api_response):
        """HTML tags removed from job content."""
        with patch('requests.get') as mock_get:
            mock_response = MagicMock()
            mock_response.json.return_value = greenhouse_api_response
            mock_get.return_value = mock_response

            jobs = fetch_jobs("anthropic", "London")

            assert len(jobs) == 1
            # Content should not contain HTML tags
            assert "<p>" not in jobs[0]['content']
            assert "<strong>" not in jobs[0]['content']
            # But should contain the text
            assert "senior engineer" in jobs[0]['content'].lower()

    def test_fetch_jobs_content_truncated(self, greenhouse_api_long_content):
        """Content exceeding 6000 chars is capped."""
        with patch('requests.get') as mock_get:
            mock_response = MagicMock()
            mock_response.json.return_value = greenhouse_api_long_content
            mock_get.return_value = mock_response

            jobs = fetch_jobs("anthropic", "London")

            assert len(jobs) == 1
            assert len(jobs[0]['content']) == 6000

    def test_fetch_jobs_no_departments(self, greenhouse_api_no_departments):
        """Empty departments list defaults to 'Unknown'."""
        with patch('requests.get') as mock_get:
            mock_response = MagicMock()
            mock_response.json.return_value = greenhouse_api_no_departments
            mock_get.return_value = mock_response

            jobs = fetch_jobs("anthropic", "London")

            assert len(jobs) == 1
            assert jobs[0]['department'] == "Unknown"

    def test_strip_html_direct(self):
        """Test _strip_html() directly."""
        html = "<p>Hello <strong>World</strong>!</p><p>Second paragraph.</p>"
        result = _strip_html(html)

        assert "<p>" not in result
        assert "<strong>" not in result
        assert "Hello" in result
        assert "World" in result
        assert "Second paragraph" in result

    def test_strip_html_empty_string(self):
        """_strip_html() handles empty string."""
        result = _strip_html("")
        assert result == ""

    def test_strip_html_none_value(self):
        """_strip_html() handles None gracefully."""
        result = _strip_html(None)
        assert result == ""

    def test_fetch_jobs_correct_fields(self, greenhouse_api_response):
        """Fetched job has all required fields."""
        with patch('requests.get') as mock_get:
            mock_response = MagicMock()
            mock_response.json.return_value = greenhouse_api_response
            mock_get.return_value = mock_response

            jobs = fetch_jobs("anthropic", "London")

            assert len(jobs) == 1
            job = jobs[0]
            assert 'title' in job
            assert 'url' in job
            assert 'location' in job
            assert 'department' in job
            assert 'content' in job
