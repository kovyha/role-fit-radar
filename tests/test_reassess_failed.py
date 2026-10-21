from unittest.mock import MagicMock, patch

from scripts import reassess_failed as rf

HEADER = ["Date Found", "Company", "Source", "Title", "Location", "Department", "URL",
          "First Published", "Fit Score (1-10)", "Key Strengths", "Key Gaps",
          "Recommendation", "Reasoning", "Dedup Key"]

LONG_JD = "Build execution algos in C++. " * 20


def _row(title, source="greenhouse", rec="Manual review needed", url=None):
    url = url or f"https://example.com/{title}"
    return ["2026-10-01 12:00", "Acme", source, title, "London", "Markets", url,
            "", "0", "Assessment failed", "Assessment failed", rec, "Unterminated string", "k"]


def _worksheet(rows):
    ws = MagicMock()
    ws.get_all_values.return_value = [HEADER, *rows]
    return ws


GOOD = {"fit_score": 7, "key_strengths": "S", "key_gaps": "G", "recommendation": "Maybe", "reasoning": "R"}


class TestFindFailedRows:
    def test_returns_only_failed_with_sheet_row_numbers(self):
        rows = [HEADER, _row("a", rec="Apply"), _row("b"), _row("c", rec="Skip"), _row("d")]
        assert [n for n, _ in rf.find_failed_rows(rows)] == [3, 5]

    def test_ignores_short_rows(self):
        assert rf.find_failed_rows([HEADER, ["2026-10-01", "Acme"]]) == []


class TestFetchContent:
    @patch("scripts.reassess_failed.gmail_linkedin._fetch_job_description", return_value={"content": "li jd"})
    def test_linkedin_uses_source_fetcher(self, mock_fetch):
        assert rf.fetch_content("linkedin_email", "https://linkedin.com/jobs/view/1") == "li jd"

    @patch("scripts.reassess_failed.greenhouse._fetch_content", return_value="gh jd")
    def test_greenhouse_parses_board_and_id(self, mock_fetch):
        url = "https://job-boards.greenhouse.io/anthropic/jobs/5405710008"
        assert rf.fetch_content("greenhouse", url) == "gh jd"
        mock_fetch.assert_called_once_with("anthropic", 5405710008)

    @patch("scripts.reassess_failed._fetch_efc_async")
    def test_efc_uses_source_fetcher(self, mock_fetch):
        async def _ret(url):
            return "efc jd"
        mock_fetch.side_effect = _ret
        assert rf.fetch_content("efinancialcareers", "https://efinancialcareers.co.uk/x") == "efc jd"

    @patch("scripts.reassess_failed._fetch_generic_async")
    def test_other_sources_use_generic_fetch(self, mock_fetch):
        async def _ret(url):
            return "generic jd"
        mock_fetch.side_effect = _ret
        assert rf.fetch_content("oracle_hcm", "https://jpmc.fa.oraclecloud.com/job/1") == "generic jd"

    @patch("scripts.reassess_failed.gmail_linkedin._fetch_job_description", side_effect=RuntimeError("boom"))
    def test_exception_returns_empty(self, mock_fetch):
        assert rf.fetch_content("linkedin_email", "https://linkedin.com/jobs/view/1") == ""


class TestFetchWithRetry:
    @patch("scripts.reassess_failed.fetch_content", side_effect=["", LONG_JD])
    def test_retries_once_on_empty(self, mock_fetch):
        assert rf.fetch_with_retry("linkedin_email", "u") == LONG_JD
        assert mock_fetch.call_count == 2

    @patch("scripts.reassess_failed.fetch_content", return_value="too short")
    def test_gives_up_after_attempts(self, mock_fetch):
        assert rf.fetch_with_retry("linkedin_email", "u") == ""
        assert mock_fetch.call_count == rf.FETCH_ATTEMPTS


@patch("scripts.reassess_failed.check_posting", new=MagicMock(return_value=(rf.POSTING_OPEN, 200)))
class TestReassess:
    @patch("scripts.reassess_failed.assess_fit", return_value=GOOD)
    @patch("scripts.reassess_failed.fetch_with_retry", return_value=LONG_JD)
    def test_updates_assessment_columns_in_place(self, mock_fetch, mock_assess):
        ws = _worksheet([_row("ok", rec="Apply"), _row("failed")])
        outcome = rf.reassess(ws, "profile")

        ws.update.assert_called_once_with(
            values=[[7, "S", "G", "Maybe", "R"]], range_name="I3:M3", value_input_option="RAW"
        )
        assert len(outcome["fixed"]) == 1
        job = mock_assess.call_args.args[0]
        assert job["title"] == "failed" and job["content"] == LONG_JD and job["department"] == "Markets"

    @patch("scripts.reassess_failed.assess_fit", return_value=GOOD)
    @patch("scripts.reassess_failed.fetch_with_retry", return_value=LONG_JD)
    def test_dry_run_does_not_write(self, mock_fetch, mock_assess):
        ws = _worksheet([_row("failed")])
        outcome = rf.reassess(ws, "profile", dry_run=True)
        ws.update.assert_not_called()
        assert len(outcome["fixed"]) == 1

    @patch("scripts.reassess_failed.assess_fit")
    @patch("scripts.reassess_failed.fetch_with_retry", return_value="")
    def test_unfetchable_row_skipped_without_api_call(self, mock_fetch, mock_assess):
        ws = _worksheet([_row("failed")])
        outcome = rf.reassess(ws, "profile")
        mock_assess.assert_not_called()
        ws.update.assert_not_called()
        assert len(outcome["unfetchable"]) == 1

    @patch("scripts.reassess_failed.assess_fit", return_value={"assessment_failed": True, "reasoning": "truncated"})
    @patch("scripts.reassess_failed.fetch_with_retry", return_value=LONG_JD)
    def test_repeat_failure_leaves_row_untouched(self, mock_fetch, mock_assess):
        ws = _worksheet([_row("failed")])
        outcome = rf.reassess(ws, "profile")
        ws.update.assert_not_called()
        assert outcome["still_failed"][0][1] == "truncated"


class TestClosedPostings:
    @patch("scripts.reassess_failed.assess_fit")
    @patch("scripts.reassess_failed.fetch_with_retry")
    @patch("scripts.reassess_failed.check_posting", return_value=(rf.POSTING_CLOSED, 410))
    def test_closed_row_marked_without_fetch_or_api_call(self, mock_closed, mock_fetch, mock_assess):
        ws = _worksheet([_row("gone")])
        outcome = rf.reassess(ws, "profile")

        mock_fetch.assert_not_called()
        mock_assess.assert_not_called()
        values = ws.update.call_args.kwargs["values"][0]
        assert values[:4] == ["", "", "", "Closed"]
        assert "Posting closed" in values[4]
        assert ws.update.call_args.kwargs["range_name"] == "I2:M2"
        assert len(outcome["closed"]) == 1

    @patch("scripts.reassess_failed.check_posting", return_value=(rf.POSTING_CLOSED, 410))
    def test_closed_row_not_written_on_dry_run(self, mock_closed):
        ws = _worksheet([_row("gone")])
        outcome = rf.reassess(ws, "profile", dry_run=True)
        ws.update.assert_not_called()
        assert len(outcome["closed"]) == 1

    @patch("scripts.reassess_failed._check_posting_async", side_effect=RuntimeError("browser crash"))
    def test_check_error_treated_as_open(self, mock_check):
        assert rf.check_posting("https://example.com/x") == (rf.POSTING_OPEN, None)

    @patch("scripts.reassess_failed.assess_fit")
    @patch("scripts.reassess_failed.fetch_with_retry")
    @patch("scripts.reassess_failed.check_posting", return_value=(rf.POSTING_BLOCKED, 403))
    def test_blocked_row_left_untouched(self, mock_check, mock_fetch, mock_assess):
        ws = _worksheet([_row("efc job", source="efinancialcareers")])
        outcome = rf.reassess(ws, "profile")

        ws.update.assert_not_called()
        mock_fetch.assert_not_called()
        mock_assess.assert_not_called()
        assert outcome["blocked"][0][1] == "HTTP 403"
        assert outcome["closed"] == []


class TestClassifyPosting:
    def test_gone_and_not_found_are_closed(self):
        assert rf.classify_posting(410, "") == rf.POSTING_CLOSED
        assert rf.classify_posting(404, "") == rf.POSTING_CLOSED

    def test_forbidden_rate_limited_and_server_errors_are_blocked(self):
        for status in (403, 429, 500, 503):
            assert rf.classify_posting(status, "") == rf.POSTING_BLOCKED, status

    def test_closed_marker_text_is_closed(self):
        assert rf.classify_posting(200, "Senior Engineer\nNo longer accepting applications.") == rf.POSTING_CLOSED

    def test_normal_page_is_open(self):
        assert rf.classify_posting(200, "We are hiring a senior engineer to build execution algos.") == rf.POSTING_OPEN
        assert rf.classify_posting(None, "Job description") == rf.POSTING_OPEN


class TestMain:
    @patch("scripts.reassess_failed.reassess", return_value={"fixed": [("row 2: x", "7/10 Maybe")],
                                                              "closed": [("row 5: w", "u")],
                                                              "blocked": [("row 6: v", "HTTP 403")],
                                                              "unfetchable": [("row 3: y", "u")],
                                                              "still_failed": [("row 4: z", "err")]})
    @patch("scripts.reassess_failed._get_sheet")
    @patch("scripts.reassess_failed.get_profile", return_value="profile")
    def test_dry_run_flag_passed_and_summary_printed(self, mock_profile, mock_sheet, mock_reassess, capsys):
        rf.main(["--dry-run"])
        assert mock_reassess.call_args.kwargs["dry_run"] is True
        out = capsys.readouterr().out
        assert "Would update 1 row(s)" in out
        assert "row 3: y" in out and "row 4: z" in out
        assert "1 row(s) would be marked 'Closed'" in out and "row 5: w" in out
        assert "Site blocked the request — 1 row(s)" in out and "row 6: v" in out

    @patch("scripts.reassess_failed.get_profile", return_value="")
    def test_aborts_on_empty_profile(self, mock_profile):
        import pytest
        with pytest.raises(SystemExit):
            rf.main([])
