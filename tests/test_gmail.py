import email
import email.header
import urllib.parse
from unittest.mock import patch


from config import CV_VARIANTS
from gmail import _ask_ai_url, _build_html, _build_plain, _select_cv_variant, send_summary


_BASE_JOB = {
    "title": "VP Electronic Trading",
    "company": "Acme Bank",
    "department": "Markets",
    "location": "London",
    "content": "Build low-latency execution infrastructure for equities and FX.",
}


def _make_job(**overrides) -> dict:
    return {**_BASE_JOB, **overrides}


class TestSelectCvVariant:
    def test_default_returns_main(self):
        assert _select_cv_variant(_make_job()) == "main"

    def test_ai_keyword_in_content(self):
        job = _make_job(content="Experience with large language models and LLM pipelines required.")
        assert _select_cv_variant(job) == "ai"

    def test_ai_keyword_in_title(self):
        job = _make_job(title="Director of Machine Learning")
        assert _select_cv_variant(job) == "ai"

    def test_ai_keyword_in_department(self):
        job = _make_job(department="Artificial Intelligence Research")
        assert _select_cv_variant(job) == "ai"

    def test_quant_keyword_in_content(self):
        job = _make_job(content="Develop quantitative risk models using Monte Carlo simulation.")
        assert _select_cv_variant(job) == "quant"

    def test_quant_keyword_in_title(self):
        job = _make_job(title="Quantitative Developer, Derivatives")
        assert _select_cv_variant(job) == "quant"

    def test_ai_takes_priority_over_quant(self):
        job = _make_job(
            content="Quant research team applying machine learning to derivatives pricing."
        )
        assert _select_cv_variant(job) == "ai"

    def test_case_insensitive(self):
        job = _make_job(content="DEEP LEARNING infrastructure for HFT.")
        assert _select_cv_variant(job) == "ai"


class TestAskAiUrl:
    def test_returns_claude_ai_base(self):
        url = _ask_ai_url(_BASE_JOB, "main")
        assert url.startswith("https://claude.ai/new?q=")

    def test_contains_cv_filename(self):
        for key, filename in CV_VARIANTS.items():
            url = _ask_ai_url(_BASE_JOB, key)
            decoded = urllib.parse.unquote(url)
            assert filename in decoded, f"Expected {filename} in URL for variant {key!r}"

    def test_contains_job_title(self):
        url = _ask_ai_url(_BASE_JOB, "main")
        decoded = urllib.parse.unquote(url)
        assert "VP Electronic Trading" in decoded

    def test_contains_job_content(self):
        url = _ask_ai_url(_BASE_JOB, "main")
        decoded = urllib.parse.unquote(url)
        assert "low-latency execution" in decoded

    def test_contains_company(self):
        url = _ask_ai_url(_BASE_JOB, "main")
        decoded = urllib.parse.unquote(url)
        assert "Acme Bank" in decoded

    def test_each_variant_produces_different_url(self):
        urls = {key: _ask_ai_url(_BASE_JOB, key) for key in CV_VARIANTS}
        assert len(set(urls.values())) == len(CV_VARIANTS)


_FAILED_JOB = {
    **_BASE_JOB,
    "title": "Head of Quantitative Research",
    "url": "https://example.com/job/failed",
    "sheet_url": "https://docs.google.com/spreadsheets/d/x/edit#gid=0&range=A10",
    "source": "greenhouse",
    "assessment_failed": True,
    "fit_score": 0,
    "recommendation": "Manual review needed",
    "reasoning": "Unterminated string starting at: line 12 column 16 (char 1893)",
}
_OK_JOB = {**_BASE_JOB, "url": "https://example.com/job/ok", "fit_score": 8, "recommendation": "Apply"}


def _sent_subject(mock_smtp) -> str:
    raw = mock_smtp.return_value.__enter__.return_value.sendmail.call_args.args[2]
    return str(email.header.make_header(email.header.decode_header(email.message_from_string(raw)["Subject"])))


class TestFailedAssessments:
    def test_html_banner_lists_failed_job(self):
        html = _build_html([_OK_JOB, _FAILED_JOB])
        assert "Assessment Failed" in html
        assert "1 Role(s) Need Manual Review" in html
        assert _FAILED_JOB["url"] in html
        assert _FAILED_JOB["sheet_url"] in html
        assert "Unterminated string" in html

    def test_html_no_banner_when_all_succeed(self):
        assert "Assessment Failed" not in _build_html([_OK_JOB])

    def test_plain_notice_lists_failed_job(self):
        plain = _build_plain([_OK_JOB, _FAILED_JOB])
        assert "ASSESSMENT FAILED — 1 role(s) need manual review" in plain
        assert _FAILED_JOB["url"] in plain

    def test_plain_no_notice_when_all_succeed(self):
        assert "ASSESSMENT FAILED" not in _build_plain([_OK_JOB])

    @patch("gmail.smtplib.SMTP_SSL")
    def test_subject_flags_failed_count(self, mock_smtp, monkeypatch):
        monkeypatch.setenv("GMAIL_APP_PASSWORD", "x")
        send_summary([_OK_JOB, _FAILED_JOB, {**_FAILED_JOB, "url": "https://example.com/job/f2"}])
        assert _sent_subject(mock_smtp).startswith("[2 ASSESS FAILED] ")

    @patch("gmail.smtplib.SMTP_SSL")
    def test_subject_unflagged_when_all_succeed(self, mock_smtp, monkeypatch):
        monkeypatch.setenv("GMAIL_APP_PASSWORD", "x")
        send_summary([_OK_JOB])
        assert "ASSESS FAILED" not in _sent_subject(mock_smtp)
