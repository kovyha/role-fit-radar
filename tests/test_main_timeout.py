"""
Tests for SIGTERM-triggered partial flush in main.main().

Simulates GitHub Actions hitting its runner timeout by sending SIGTERM to the
current process from within a mocked source fetch. This exercises the exact
signal → _ScanTimeout → _write_and_notify path that fires in production.
"""
import os
import signal
from unittest.mock import patch


def _job(title, company, url):
    return {"title": title, "company": company, "url": url,
            "location": "London", "department": "", "content": "JD text"}


def _assessment():
    return {"fit_score": 7, "key_strengths": "s", "key_gaps": "g",
            "recommendation": "Maybe", "reasoning": "r"}


_FAST = {"name": "FastCorp", "source": "greenhouse", "board": "fastcorp"}
_SLOW = {"name": "SlowCorp", "source": "efinancialcareers",
         "local_allowlist": frozenset(), "local_blocklist": frozenset()}
_THIRD = {"name": "ThirdCorp", "source": "ashby", "org": "thirdcorp"}


class TestSigtermFlush:

    def test_sigterm_mid_source_flushes_completed_marks_pending(self):
        """SIGTERM during SlowCorp: FastCorp's jobs written, SlowCorp+ThirdCorp pending."""
        def slow_fetch(*args, **kwargs):
            os.kill(os.getpid(), signal.SIGTERM)
            return []  # unreachable

        with patch("main.COMPANIES", [_FAST, _SLOW, _THIRD]), \
             patch("main.get_seen_urls", return_value=set()), \
             patch("main.get_seen_title_company_keys", return_value={}), \
             patch("main.get_profile", return_value="profile"), \
             patch("main.greenhouse_fetch", return_value=[_job("Quant", "FastCorp", "https://gh.io/1")]), \
             patch("main.efinancial_fetch", side_effect=slow_fetch), \
             patch("main.assess_fit", return_value=_assessment()), \
             patch("main.append_jobs", return_value=["https://sheet/1"]) as mock_append, \
             patch("main.send_summary") as mock_send:
            from main import main
            main()

        written = mock_append.call_args[0][0]
        assert len(written) == 1
        assert written[0]["company"] == "FastCorp"

        pending_names = [c["name"] for c in mock_send.call_args[1]["pending_companies"]]
        assert pending_names == ["SlowCorp", "ThirdCorp"]

    def test_sigterm_before_any_jobs_sends_empty_email_with_all_pending(self):
        """SIGTERM during the first source before it returns: no jobs written, all companies pending."""
        def fast_fetch(*args, **kwargs):
            os.kill(os.getpid(), signal.SIGTERM)
            return []

        with patch("main.COMPANIES", [_FAST, _SLOW]), \
             patch("main.get_seen_urls", return_value=set()), \
             patch("main.get_seen_title_company_keys", return_value={}), \
             patch("main.get_profile", return_value="profile"), \
             patch("main.greenhouse_fetch", side_effect=fast_fetch), \
             patch("main.assess_fit", return_value=_assessment()), \
             patch("main.append_jobs") as mock_append, \
             patch("main.send_summary") as mock_send:
            from main import main
            main()

        mock_append.assert_not_called()
        pending_names = [c["name"] for c in mock_send.call_args[1]["pending_companies"]]
        assert "FastCorp" in pending_names
        assert "SlowCorp" in pending_names

    def test_no_sigterm_produces_no_pending(self):
        """Sanity: normal completion passes pending_companies=[] to send_summary."""
        with patch("main.COMPANIES", [_FAST]), \
             patch("main.get_seen_urls", return_value=set()), \
             patch("main.get_seen_title_company_keys", return_value={}), \
             patch("main.get_profile", return_value="profile"), \
             patch("main.greenhouse_fetch", return_value=[_job("Quant", "FastCorp", "https://gh.io/1")]), \
             patch("main.assess_fit", return_value=_assessment()), \
             patch("main.append_jobs", return_value=["https://sheet/1"]), \
             patch("main.send_summary") as mock_send:
            from main import main
            main()

        assert mock_send.call_args[1]["pending_companies"] == []
