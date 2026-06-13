from unittest.mock import patch, MagicMock
import requests

from sources.wfh_hub import fetch_jobs, _parse_listing_page, _fetch_content


# ── HTML fixtures ─────────────────────────────────────────────────────────────

_LISTING_HTML = """
<html><body>
  <article>
    <h2><a href="/jobs/eal-teacher-remote-abc">EAL Teacher (Remote)</a></h2>
    <a href="/jobs/category/Fully+Remote">Fully Remote</a>
    <a href="/jobs/category/Part+Time">Part Time</a>
    <p>Employer: Learning Academy</p>
  </article>
  <article>
    <h2><a href="/jobs/admin-coordinator-xyz">Admin Coordinator</a></h2>
    <a href="/jobs/category/Remote+First">Remote First</a>
    <a href="/jobs/category/Part+Time">Part Time</a>
    <p>Employer: Office Solutions Ltd</p>
  </article>
  <article>
    <h2><a href="/jobs/sales-manager-def">Sales Manager</a></h2>
    <a href="/jobs/category/Fully+Remote">Fully Remote</a>
    <a href="/jobs/category/Part+Time">Part Time</a>
    <p>Employer: Sales Corp</p>
  </article>
  <article>
    <h2><a href="/jobs/english-tutor-hybrid-ghi">English Tutor</a></h2>
    <a href="/jobs/category/Hybrid">Hybrid</a>
    <a href="/jobs/category/Part+Time">Part Time</a>
    <p>Employer: TutorCo</p>
  </article>
  <a href="/jobs?offset=9999&category=Part+Time">Older Posts</a>
</body></html>
"""

_LISTING_HTML_NO_NEXT = """
<html><body>
  <article>
    <h2><a href="/jobs/eal-teacher-remote-abc">EAL Teacher (Remote)</a></h2>
    <a href="/jobs/category/Fully+Remote">Fully Remote</a>
    <a href="/jobs/category/Part+Time">Part Time</a>
    <p>Employer: Learning Academy</p>
  </article>
</body></html>
"""

_DETAIL_HTML = """
<html><body>
  <div class="entry-content">
    <h1>EAL Teacher (Remote)</h1>
    <p>Employer: Learning Academy</p>
    <p>We are looking for a part-time EAL teacher to join our remote team.</p>
    <p>CELTA or equivalent required. Flexible hours, 15h/week.</p>
  </div>
</body></html>
"""


def _make_get(listing_html=_LISTING_HTML, detail_html=_DETAIL_HTML, fail_on=None):
    """Return a requests.get side_effect that serves listing or detail HTML by URL."""
    def side_effect(url, **kwargs):
        if fail_on and fail_on in url:
            raise requests.RequestException("HTTP error")
        mock = MagicMock()
        mock.raise_for_status = MagicMock()
        if "/jobs/eal-" in url or "/jobs/admin-" in url or "/jobs/english-" in url or "/jobs/sales-" in url:
            mock.text = detail_html
        else:
            mock.text = listing_html
        return mock
    return side_effect


# ── _parse_listing_page ───────────────────────────────────────────────────────

class TestParseListingPage:

    def test_extracts_fully_remote_jobs(self):
        jobs, _ = _parse_listing_page(_LISTING_HTML)
        titles = [j[0] for j in jobs]
        assert "EAL Teacher (Remote)" in titles
        assert "Admin Coordinator" in titles

    def test_extracts_remote_first_jobs(self):
        jobs, _ = _parse_listing_page(_LISTING_HTML)
        admin = next(j for j in jobs if "Admin" in j[0])
        assert "remote first" in admin[2]  # categories list

    def test_hybrid_job_present_in_parse_but_filtered_later(self):
        # _parse_listing_page returns ALL jobs; category filtering is in _collect_stubs
        jobs, _ = _parse_listing_page(_LISTING_HTML)
        titles = [j[0] for j in jobs]
        assert "English Tutor" in titles

    def test_extracts_company_name(self):
        jobs, _ = _parse_listing_page(_LISTING_HTML)
        eal = next(j for j in jobs if "EAL" in j[0])
        assert "Learning Academy" in eal[3]  # company

    def test_extracts_next_page_url(self):
        _, next_url = _parse_listing_page(_LISTING_HTML)
        assert next_url is not None
        assert "offset=9999" in next_url

    def test_no_next_page_returns_none(self):
        _, next_url = _parse_listing_page(_LISTING_HTML_NO_NEXT)
        assert next_url is None

    def test_extracts_correct_job_url(self):
        jobs, _ = _parse_listing_page(_LISTING_HTML)
        eal = next(j for j in jobs if "EAL" in j[0])
        assert eal[1] == "https://www.theworkfromhomehub.co.uk/jobs/eal-teacher-remote-abc"


# ── fetch_jobs ────────────────────────────────────────────────────────────────

class TestFetchJobs:

    def test_returns_fully_remote_jobs(self):
        with patch("requests.get", side_effect=_make_get(_LISTING_HTML_NO_NEXT)):
            jobs = fetch_jobs("", allowlist=frozenset(["eal"]))
        assert len(jobs) == 1
        assert jobs[0]["title"] == "EAL Teacher (Remote)"

    def test_excludes_hybrid_jobs(self):
        with patch("requests.get", side_effect=_make_get(_LISTING_HTML_NO_NEXT)):
            jobs = fetch_jobs("", allowlist=frozenset())
        titles = [j["title"] for j in jobs]
        assert "English Tutor" not in titles  # Hybrid category — excluded

    def test_title_blocklist_removes_sales(self):
        with patch("requests.get", side_effect=_make_get(_LISTING_HTML_NO_NEXT)):
            jobs = fetch_jobs(
                "",
                allowlist=frozenset(),
                blocklist=frozenset(["sales"]),
            )
        titles = [j["title"] for j in jobs]
        assert not any("Sales" in t for t in titles)

    def test_seen_url_skips_detail_fetch(self):
        seen = {"https://www.theworkfromhomehub.co.uk/jobs/eal-teacher-remote-abc"}
        call_count = 0

        def counting_get(url, **kwargs):
            nonlocal call_count
            call_count += 1
            mock = MagicMock()
            mock.raise_for_status = MagicMock()
            mock.text = _LISTING_HTML_NO_NEXT
            return mock

        with patch("requests.get", side_effect=counting_get):
            jobs = fetch_jobs("", seen_urls=seen, allowlist=frozenset(["eal"]))

        assert jobs == []
        assert call_count == 1  # listing page only; no detail fetch

    def test_http_error_on_listing_returns_empty(self):
        with patch("requests.get", side_effect=requests.RequestException("timeout")):
            jobs = fetch_jobs("", allowlist=frozenset())
        assert jobs == []

    def test_all_required_fields_present(self):
        with patch("requests.get", side_effect=_make_get(_LISTING_HTML_NO_NEXT)):
            jobs = fetch_jobs("", allowlist=frozenset(["eal"]))
        assert len(jobs) == 1
        for field in ("title", "url", "company", "location", "department", "content"):
            assert field in jobs[0]

    def test_location_is_remote(self):
        with patch("requests.get", side_effect=_make_get(_LISTING_HTML_NO_NEXT)):
            jobs = fetch_jobs("", allowlist=frozenset(["eal"]))
        assert jobs[0]["location"] == "Remote"

    def test_content_fetched_from_detail_page(self):
        with patch("requests.get", side_effect=_make_get(_LISTING_HTML_NO_NEXT, _DETAIL_HTML)):
            jobs = fetch_jobs("", allowlist=frozenset(["eal"]))
        assert "CELTA" in jobs[0]["content"]


# ── _fetch_content ────────────────────────────────────────────────────────────

class TestFetchContent:

    def test_returns_text_from_entry_content(self):
        mock = MagicMock()
        mock.raise_for_status = MagicMock()
        mock.text = _DETAIL_HTML
        with patch("requests.get", return_value=mock):
            result = _fetch_content("https://www.theworkfromhomehub.co.uk/jobs/eal-teacher-remote-abc")
        assert "EAL Teacher" in result
        assert "CELTA" in result
        assert "<p>" not in result

    def test_http_error_returns_empty_string(self):
        with patch("requests.get", side_effect=requests.RequestException("timeout")):
            result = _fetch_content("https://www.theworkfromhomehub.co.uk/jobs/eal-teacher-remote-abc")
        assert result == ""

    def test_content_truncated_at_max(self):
        long_html = f"<div class='entry-content'>{'x ' * 5000}</div>"
        mock = MagicMock()
        mock.raise_for_status = MagicMock()
        mock.text = long_html
        with patch("requests.get", return_value=mock):
            result = _fetch_content("https://example.com/job")
        assert len(result) <= 6000
