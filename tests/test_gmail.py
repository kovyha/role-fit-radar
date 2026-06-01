import urllib.parse


from config import CV_VARIANTS
from gmail import _ask_ai_url, _select_cv_variant


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
