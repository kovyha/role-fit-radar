from unittest.mock import patch, MagicMock
import requests

from sources.tes import fetch_jobs, _parse_listing_page, _fetch_content


# ── HTML fixtures ─────────────────────────────────────────────────────────────

# TES job cards: <a href="/jobs/vacancy/..."> wrapping title + org + location
_LISTING_HTML = """
<html><body>
  <div class="search-results">
    <a href="/jobs/vacancy/eal-teacher-london-1001">
      <h3>EAL Teacher</h3>
      <img alt="St Mary's School logo" src="/logo.png"/>
      <p>St Mary's School</p>
      <p>London, UK</p>
      <p>£28,000 per year</p>
      <span>Part Time</span>
      <span>Today</span>
    </a>
    <a href="/jobs/vacancy/english-tutor-manchester-1002">
      <h3>English Language Tutor</h3>
      <img alt="TutorNet logo" src="/logo2.png"/>
      <p>TutorNet</p>
      <p>Manchester</p>
      <span>Part Time</span>
    </a>
    <a href="/jobs/vacancy/science-teacher-oxford-1003">
      <h3>Science Teacher</h3>
      <p>Oxford Academy</p>
      <p>Oxford</p>
      <span>Full Time</span>
    </a>
  </div>
  <a href="/jobs/search?title=eal&contract=part_time&page=2">Next page</a>
</body></html>
"""

_LISTING_HTML_NO_NEXT = """
<html><body>
  <a href="/jobs/vacancy/eal-teacher-london-1001">
    <h3>EAL Teacher</h3>
    <img alt="St Mary's School logo" src="/logo.png"/>
    <p>St Mary's School</p>
    <p>London, UK</p>
    <span>Part Time</span>
  </a>
</body></html>
"""

_DETAIL_HTML = """
<html><body>
  <main>
    <h1>EAL Teacher</h1>
    <p>St Mary's School is seeking a part-time EAL teacher.</p>
    <p>CELTA or QTS required. 12 hours per week. Remote delivery considered.</p>
  </main>
</body></html>
"""


def _make_get(listing_html=_LISTING_HTML, detail_html=_DETAIL_HTML):
    def side_effect(url, **kwargs):
        mock = MagicMock()
        mock.raise_for_status = MagicMock()
        if "/jobs/vacancy/" in url:
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
        assert "EAL Teacher" in titles
        assert "English Language Tutor" in titles

    def test_extracts_correct_job_urls(self):
        jobs, _ = _parse_listing_page(_LISTING_HTML)
        eal = next(j for j in jobs if "EAL" in j[0])
        assert eal[1] == "https://www.tes.com/jobs/vacancy/eal-teacher-london-1001"

    def test_extracts_company_from_img_alt(self):
        jobs, _ = _parse_listing_page(_LISTING_HTML)
        eal = next(j for j in jobs if "EAL" in j[0])
        assert "St Mary" in eal[2]  # company; alt="St Mary's School logo" → "St Mary's School"

    def test_extracts_location(self):
        jobs, _ = _parse_listing_page(_LISTING_HTML)
        eal = next(j for j in jobs if "EAL" in j[0])
        assert "London" in eal[3]  # location

    def test_extracts_next_page_url(self):
        _, next_url = _parse_listing_page(_LISTING_HTML)
        assert next_url is not None
        assert "page=2" in next_url

    def test_no_next_page_returns_none(self):
        _, next_url = _parse_listing_page(_LISTING_HTML_NO_NEXT)
        assert next_url is None

    def test_deduplicates_same_vacancy_url(self):
        html = """
        <html><body>
          <a href="/jobs/vacancy/eal-teacher-london-1001"><h3>EAL Teacher</h3></a>
          <a href="/jobs/vacancy/eal-teacher-london-1001"><h3>EAL Teacher</h3></a>
        </body></html>
        """
        jobs, _ = _parse_listing_page(html)
        assert len(jobs) == 1

    def test_returns_three_jobs(self):
        jobs, _ = _parse_listing_page(_LISTING_HTML)
        assert len(jobs) == 3


# ── fetch_jobs ────────────────────────────────────────────────────────────────

class TestFetchJobs:

    def test_returns_jobs_matching_allowlist(self):
        with patch("requests.get", side_effect=_make_get(_LISTING_HTML_NO_NEXT)):
            jobs = fetch_jobs("", search_terms=frozenset(["eal"]), allowlist=frozenset(["eal"]))
        assert len(jobs) == 1
        assert jobs[0]["title"] == "EAL Teacher"

    def test_irrelevant_title_filtered_out(self):
        _science_only_html = """
        <html><body>
          <a href="/jobs/vacancy/science-teacher-oxford-9001">
            <h3>Science Teacher</h3>
            <p>Oxford Academy</p>
            <p>Oxford</p>
          </a>
        </body></html>
        """
        with patch("requests.get", side_effect=_make_get(_science_only_html)):
            # "eal" allowlist: "Science Teacher" does not match → filtered out
            jobs = fetch_jobs(
                "",
                search_terms=frozenset(["science"]),
                allowlist=frozenset(["eal"]),
            )
        assert jobs == []

    def test_blocklist_title_filtered_out(self):
        with patch("requests.get", side_effect=_make_get(_LISTING_HTML_NO_NEXT)):
            jobs = fetch_jobs(
                "",
                search_terms=frozenset(["eal"]),
                allowlist=frozenset(),
                blocklist=frozenset(["teacher"]),
            )
        assert jobs == []

    def test_seen_url_skips_detail_fetch(self):
        seen = {"https://www.tes.com/jobs/vacancy/eal-teacher-london-1001"}
        call_count = 0

        def counting_get(url, **kwargs):
            nonlocal call_count
            call_count += 1
            mock = MagicMock()
            mock.raise_for_status = MagicMock()
            mock.text = _LISTING_HTML_NO_NEXT
            return mock

        with patch("requests.get", side_effect=counting_get):
            jobs = fetch_jobs("", seen_urls=seen, search_terms=frozenset(["eal"]))

        assert jobs == []
        assert call_count == 1  # listing page only; no detail fetches

    def test_http_error_returns_empty(self):
        with patch("requests.get", side_effect=requests.RequestException("timeout")):
            jobs = fetch_jobs("", search_terms=frozenset(["eal"]))
        assert jobs == []

    def test_all_required_fields_present(self):
        with patch("requests.get", side_effect=_make_get(_LISTING_HTML_NO_NEXT)):
            jobs = fetch_jobs("", search_terms=frozenset(["eal"]), allowlist=frozenset(["eal"]))
        assert len(jobs) == 1
        for field in ("title", "url", "company", "location", "department", "content"):
            assert field in jobs[0]

    def test_no_duplicate_across_search_terms(self):
        with patch("requests.get", side_effect=_make_get(_LISTING_HTML_NO_NEXT)):
            jobs = fetch_jobs(
                "",
                search_terms=frozenset(["eal", "english"]),
                allowlist=frozenset(["eal"]),
            )
        assert len(jobs) == 1  # same job returned by both terms; deduped

    def test_content_from_detail_page(self):
        with patch("requests.get", side_effect=_make_get(_LISTING_HTML_NO_NEXT)):
            jobs = fetch_jobs("", search_terms=frozenset(["eal"]), allowlist=frozenset(["eal"]))
        assert "CELTA" in jobs[0]["content"]


# ── _fetch_content ────────────────────────────────────────────────────────────

class TestFetchContent:

    def test_returns_text_content(self):
        mock = MagicMock()
        mock.raise_for_status = MagicMock()
        mock.text = _DETAIL_HTML
        with patch("requests.get", return_value=mock):
            result = _fetch_content("https://www.tes.com/jobs/vacancy/eal-teacher-london-1001")
        assert "EAL Teacher" in result
        assert "CELTA" in result
        assert "<p>" not in result

    def test_http_error_returns_empty_string(self):
        with patch("requests.get", side_effect=requests.RequestException("timeout")):
            result = _fetch_content("https://www.tes.com/jobs/vacancy/eal-teacher-london-1001")
        assert result == ""

    def test_content_truncated_at_max(self):
        long_html = f"<main>{'word ' * 5000}</main>"
        mock = MagicMock()
        mock.raise_for_status = MagicMock()
        mock.text = long_html
        with patch("requests.get", return_value=mock):
            result = _fetch_content("https://www.tes.com/jobs/vacancy/any")
        assert len(result) <= 6000
