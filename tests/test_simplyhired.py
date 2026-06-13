from unittest.mock import patch, MagicMock
import requests

from sources.simplyhired import fetch_jobs, _parse_listing_page, _fetch_content


# ── HTML fixtures ─────────────────────────────────────────────────────────────

_LISTING_HTML = """
<html><body>
  <div class="results">
    <div class="job-card">
      <a href="/job/abc123XYZ">EAL Teacher Part Time</a>
      <span>Language School Ltd</span>
      <span>London, UK</span>
    </div>
    <div class="job-card">
      <a href="/job/def456ABC">Admin Coordinator Remote</a>
      <span>Remote Office Co</span>
      <span>Remote</span>
    </div>
    <div class="job-card">
      <a href="/job/ghi789DEF">Sales Executive</a>
      <span>Sales Corp</span>
      <span>Manchester</span>
    </div>
  </div>
  <a href="/search?q=eal&l=uk&cursor=ABCDEF123">Next</a>
</body></html>
"""

_LISTING_HTML_NO_NEXT = """
<html><body>
  <div class="job-card">
    <a href="/job/abc123XYZ">EAL Teacher Part Time</a>
    <span>Language School Ltd</span>
    <span>London, UK</span>
  </div>
</body></html>
"""

_DETAIL_HTML = """
<html><body>
  <div class="job-description">
    <h1>EAL Teacher Part Time</h1>
    <p>We are seeking an experienced EAL teacher for part-time remote work.</p>
    <p>CELTA or equivalent required. 15 hours per week.</p>
  </div>
</body></html>
"""


def _make_get(listing_html=_LISTING_HTML, detail_html=_DETAIL_HTML):
    def side_effect(url, **kwargs):
        mock = MagicMock()
        mock.raise_for_status = MagicMock()
        if "/job/" in url and "search" not in url:
            mock.text = detail_html
        else:
            mock.text = listing_html
        return mock
    return side_effect


# ── _parse_listing_page ───────────────────────────────────────────────────────

class TestParseListingPage:

    def test_extracts_job_titles(self):
        jobs, _ = _parse_listing_page(_LISTING_HTML)
        titles = [j[0] for j in jobs]
        assert "EAL Teacher Part Time" in titles
        assert "Admin Coordinator Remote" in titles

    def test_extracts_correct_job_urls(self):
        jobs, _ = _parse_listing_page(_LISTING_HTML)
        eal = next(j for j in jobs if "EAL" in j[0])
        assert eal[1] == "https://www.simplyhired.co.uk/job/abc123XYZ"

    def test_extracts_next_page_url_with_cursor(self):
        _, next_url = _parse_listing_page(_LISTING_HTML)
        assert next_url is not None
        assert "cursor=ABCDEF123" in next_url

    def test_no_next_page_returns_none(self):
        _, next_url = _parse_listing_page(_LISTING_HTML_NO_NEXT)
        assert next_url is None

    def test_returns_three_jobs(self):
        jobs, _ = _parse_listing_page(_LISTING_HTML)
        assert len(jobs) == 3

    def test_deduplicates_same_href(self):
        html = """
        <html><body>
          <a href="/job/abc123XYZ">EAL Teacher</a>
          <a href="/job/abc123XYZ">EAL Teacher</a>
        </body></html>
        """
        jobs, _ = _parse_listing_page(html)
        assert len(jobs) == 1


# ── fetch_jobs ────────────────────────────────────────────────────────────────

class TestFetchJobs:

    def test_returns_matching_jobs(self):
        with patch("requests.get", side_effect=_make_get(_LISTING_HTML_NO_NEXT)):
            jobs = fetch_jobs("uk", search_terms=frozenset(["eal"]), allowlist=frozenset(["eal"]))
        assert len(jobs) == 1
        assert jobs[0]["title"] == "EAL Teacher Part Time"

    def test_title_blocklist_filters_out_sales(self):
        _sales_only_html = """
        <html><body>
          <div class="job-card">
            <a href="/job/xyz999ABC">Sales Executive</a>
            <span>Sales Corp</span>
            <span>Manchester</span>
          </div>
        </body></html>
        """
        with patch("requests.get", side_effect=_make_get(_sales_only_html)):
            jobs = fetch_jobs(
                "uk",
                search_terms=frozenset(["sales"]),
                allowlist=frozenset(),
                blocklist=frozenset(["sales"]),
            )
        assert jobs == []

    def test_seen_url_skips_detail_fetch(self):
        seen = {"https://www.simplyhired.co.uk/job/abc123XYZ"}
        call_count = 0

        def counting_get(url, **kwargs):
            nonlocal call_count
            call_count += 1
            mock = MagicMock()
            mock.raise_for_status = MagicMock()
            mock.text = _LISTING_HTML_NO_NEXT
            return mock

        with patch("requests.get", side_effect=counting_get):
            jobs = fetch_jobs("uk", seen_urls=seen, search_terms=frozenset(["eal"]))

        assert jobs == []
        assert call_count == 1  # listing page only

    def test_http_error_returns_empty(self):
        with patch("requests.get", side_effect=requests.RequestException("timeout")):
            jobs = fetch_jobs("uk", search_terms=frozenset(["eal"]))
        assert jobs == []

    def test_all_required_fields_present(self):
        with patch("requests.get", side_effect=_make_get(_LISTING_HTML_NO_NEXT)):
            jobs = fetch_jobs("uk", search_terms=frozenset(["eal"]), allowlist=frozenset(["eal"]))
        assert len(jobs) == 1
        for field in ("title", "url", "company", "location", "department", "content"):
            assert field in jobs[0]

    def test_no_duplicate_across_search_terms(self):
        call_count = 0

        def counting_get(url, **kwargs):
            nonlocal call_count
            call_count += 1
            mock = MagicMock()
            mock.raise_for_status = MagicMock()
            if "/job/" in url and "search" not in url:
                mock.text = _DETAIL_HTML
            else:
                mock.text = _LISTING_HTML_NO_NEXT
            return mock

        with patch("requests.get", side_effect=counting_get):
            # Two terms that return the same job URL
            jobs = fetch_jobs("uk", search_terms=frozenset(["eal", "english"]), allowlist=frozenset(["eal"]))

        # Job should appear only once despite two search term pages
        assert len(jobs) == 1

    def test_content_from_detail_page(self):
        with patch("requests.get", side_effect=_make_get(_LISTING_HTML_NO_NEXT)):
            jobs = fetch_jobs("uk", search_terms=frozenset(["eal"]), allowlist=frozenset(["eal"]))
        assert "CELTA" in jobs[0]["content"]


# ── _fetch_content ────────────────────────────────────────────────────────────

class TestFetchContent:

    def test_returns_text_content(self):
        mock = MagicMock()
        mock.raise_for_status = MagicMock()
        mock.text = _DETAIL_HTML
        with patch("requests.get", return_value=mock):
            result = _fetch_content("https://www.simplyhired.co.uk/job/abc123XYZ")
        assert "EAL Teacher" in result
        assert "CELTA" in result
        assert "<p>" not in result

    def test_http_error_returns_empty_string(self):
        with patch("requests.get", side_effect=requests.RequestException("timeout")):
            result = _fetch_content("https://www.simplyhired.co.uk/job/abc123XYZ")
        assert result == ""

    def test_content_truncated_at_max(self):
        long_html = f"<div class='job-description'>{'word ' * 5000}</div>"
        mock = MagicMock()
        mock.raise_for_status = MagicMock()
        mock.text = long_html
        with patch("requests.get", return_value=mock):
            result = _fetch_content("https://www.simplyhired.co.uk/job/xyz")
        assert len(result) <= 6000
