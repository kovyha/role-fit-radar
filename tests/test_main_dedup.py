"""
Tests for cross-platform deduplication logic in main.main().
Verifies that jobs with the same normalised title+company are assessed only once,
both within a single run and across runs (via seen_title_keys loaded from the sheet).
"""
from unittest.mock import patch


def _job(title, company, url):
    return {"title": title, "company": company, "url": url,
            "location": "London", "department": "", "content": "JD text"}


def _assessment():
    return {"fit_score": 8, "key_strengths": "s", "key_gaps": "g",
            "recommendation": "Apply", "reasoning": "r"}


# Minimal COMPANIES entries used across tests.
_GH_ANTHROPIC    = {"name": "Anthropic", "source": "greenhouse", "board": "anthropic"}
_ASHBY_ANTHROPIC = {"name": "Anthropic", "source": "ashby",      "org":   "anthropic"}
_ASHBY_OPENAI    = {"name": "OpenAI",    "source": "ashby",      "org":   "openai"}

# Convenience aliases for single-source tests
_ADZUNA_FRIEND = {"name": "Adzuna (friend)", "source": "adzuna", "search_terms": frozenset(["quant"])}

_GH_COMPANY    = _GH_ANTHROPIC
_ASHBY_COMPANY = _ASHBY_OPENAI


def _run(companies, jobs_by_key=None, seen_urls=None, seen_title_keys=None, adzuna_jobs=None):
    """
    Run main.main() with a patched COMPANIES list and minimal other mocks.

    jobs_by_key: dict mapping (source, board_or_org) -> list[dict].
      greenhouse: key is board slug, e.g. ("greenhouse", "anthropic")
      ashby:      key is org slug,   e.g. ("ashby", "openai")
      Falls back to [] for any unspecified key.
    adzuna_jobs: list[dict] returned by adzuna_fetch (all Adzuna companies share one mock).
    """
    jobs_by_key = jobs_by_key or {}

    def gh_effect(board, loc, seen_urls, **kwargs):
        return jobs_by_key.get(("greenhouse", board), [])

    def ashby_effect(org, loc, seen_urls, **kwargs):
        return jobs_by_key.get(("ashby", org), [])

    with patch("main.COMPANIES",                   companies), \
         patch("main.get_seen_urls",               return_value=seen_urls or set()), \
         patch("main.get_seen_title_company_keys", return_value=seen_title_keys if seen_title_keys is not None else {}), \
         patch("main.get_profile",                 return_value="profile"), \
         patch("main.greenhouse_fetch",            side_effect=gh_effect), \
         patch("main.ashby_fetch",                 side_effect=ashby_effect), \
         patch("main.adzuna_fetch",                return_value=adzuna_jobs or []), \
         patch("main.linkedin_fetch",              return_value=[]), \
         patch("main.efinancial_fetch",            return_value=[]), \
         patch("main.eightfold_fetch",             return_value=[]), \
         patch("main.scraper_fetch",               return_value=[]), \
         patch("main.assess_fit",                  return_value=_assessment()) as mock_assess, \
         patch("main.append_jobs")                 as mock_append, \
         patch("main.send_summary"):
        from main import main
        main()

    return mock_assess, mock_append


class TestWithinRunDedup:

    def test_same_title_company_on_two_platforms_assessed_once(self):
        """
        Anthropic posts 'Senior SWE' on both Greenhouse and Ashby.
        LLM called once; second occurrence written to sheet as Dup.
        OpenAI's 'Senior SWE' is a different company and must not be affected.
        """
        mock_assess, mock_append = _run(
            companies=[_GH_ANTHROPIC, _ASHBY_ANTHROPIC, _ASHBY_OPENAI],
            jobs_by_key={
                ("greenhouse", "anthropic"): [_job("Senior SWE", "Anthropic", "https://greenhouse.io/1")],
                ("ashby",      "anthropic"): [_job("Senior SWE", "Anthropic", "https://ashby.io/99")],
                ("ashby",      "openai"):    [_job("Senior SWE", "OpenAI",    "https://ashby.io/2")],
            },
        )

        titles_companies = [
            (c.args[0]["title"], c.args[0].get("company", ""))
            for c in mock_assess.call_args_list
        ]
        assert titles_companies.count(("Senior SWE", "Anthropic")) == 1
        assert ("Senior SWE", "OpenAI") in titles_companies

        written_jobs = mock_append.call_args[0][0]
        dup_rows = [j for j in written_jobs if j.get("recommendation") == "Dup"]
        assert len(dup_rows) == 1
        assert dup_rows[0]["title"] == "Senior SWE"
        assert dup_rows[0]["company"] == "Anthropic"
        assert "https://greenhouse.io/1" in dup_rows[0]["reasoning"]

    def test_distinct_roles_at_same_company_both_assessed(self):
        """Two different titles at the same company are not collapsed."""
        mock_assess, _ = _run(
            companies=[_GH_COMPANY],
            jobs_by_key={
                ("greenhouse", "anthropic"): [
                    _job("Engineering Manager", "Anthropic", "https://greenhouse.io/1"),
                    _job("Senior SWE",          "Anthropic", "https://greenhouse.io/2"),
                ],
            },
        )

        assert mock_assess.call_count == 2


class TestCrossRunDedup:

    def test_role_in_seen_title_keys_is_not_assessed_but_written_as_dup(self):
        """A role whose key is already in the sheet → no LLM call; stub row written with Recommendation='Dup'
        and reasoning pointing at the original URL."""
        original_url = "https://greenhouse.io/original"
        mock_assess, mock_append = _run(
            companies=[_GH_COMPANY],
            jobs_by_key={
                ("greenhouse", "anthropic"): [_job("Product Manager", "Anthropic", "https://greenhouse.io/42")],
            },
            seen_title_keys={"product manager|anthropic": original_url},
        )

        mock_assess.assert_not_called()
        written_jobs = mock_append.call_args[0][0]
        assert len(written_jobs) == 1
        assert written_jobs[0]["recommendation"] == "Dup"
        assert original_url in written_jobs[0]["reasoning"]

    def test_role_not_in_seen_title_keys_is_assessed(self):
        """A role absent from seen_title_keys passes through normally."""
        mock_assess, _ = _run(
            companies=[_GH_COMPANY],
            jobs_by_key={
                ("greenhouse", "anthropic"): [_job("Product Manager", "Anthropic", "https://greenhouse.io/42")],
            },
            seen_title_keys={},
        )

        mock_assess.assert_called_once()


class TestSamePlatformMultiLocation:

    def test_adzuna_same_title_company_different_locations_both_assessed(self):
        """
        Adzuna returns the same role (same title, same company) in two cities.
        Both have distinct job IDs (distinct URLs) so they are genuinely different
        postings and must each be assessed — not collapsed into one Dup.
        """
        london_job    = {**_job("Quant Analyst", "Goldman Sachs", "https://www.adzuna.co.uk/jobs/details/1001"), "location": "London"}
        edinburgh_job = {**_job("Quant Analyst", "Goldman Sachs", "https://www.adzuna.co.uk/jobs/details/1002"), "location": "Edinburgh"}

        mock_assess, mock_append = _run(
            companies=[_ADZUNA_FRIEND],
            adzuna_jobs=[london_job, edinburgh_job],
        )

        assert mock_assess.call_count == 2
        written_jobs = mock_append.call_args[0][0]
        assert not any(j.get("recommendation") == "Dup" for j in written_jobs)

    def test_adzuna_cross_platform_dup_still_caught(self):
        """
        A role already in the sheet (from any previous source) is still marked Dup
        even when the current source is Adzuna.
        """
        original_url = "https://greenhouse.io/original"
        mock_assess, mock_append = _run(
            companies=[_ADZUNA_FRIEND],
            adzuna_jobs=[{**_job("Quant Analyst", "Goldman Sachs", "https://www.adzuna.co.uk/jobs/details/1001"), "location": "London"}],
            seen_title_keys={"quant analyst|goldman sachs": original_url},
        )

        mock_assess.assert_not_called()
        written_jobs = mock_append.call_args[0][0]
        assert written_jobs[0]["recommendation"] == "Dup"
        assert original_url in written_jobs[0]["reasoning"]
