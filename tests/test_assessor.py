import json
import pytest
from unittest.mock import MagicMock, patch


SAMPLE_PROFILE = """Name: Ivy Yip
Role 1: Morgan Stanley — Executive Director (Nov 2021 – Apr 2026): EMEA Head of Benchmark Execution Services.
Role 2: Credit Suisse — Vice President (Sept 2013 – Nov 2021): Head of EMEA Algorithmic Execution Services Quant Development. Built Random Forest algo selection and Adaptive VWAP with K-means clustering, both in production.
Role 3: Citigroup — AVP (Aug 2006 – Apr 2013): Algorithmic Trading Product Strategist (APAC) / Senior Developer (EMEA)."""

SAMPLE_JOB = {
    "title": "Quant Developer — Execution Algos",
    "department": "Electronic Trading",
    "location": "London",
    "content": "Looking for a quant developer to build and enhance VWAP/TWAP execution algorithms in C++.",
    "url": "https://example.com/job/123",
    "company": "Test Bank",
    "source": "test",
}

VALID_RESPONSE = {
    "fit_score": 9,
    "key_strengths": "18 years in algo execution. Production VWAP and ML models at Credit Suisse.",
    "key_gaps": "No pure alpha research background.",
    "recommendation": "Apply",
    "reasoning": "Strong execution engineering fit across all three roles.",
}


@pytest.fixture(autouse=True)
def fake_api_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")


def _make_mock_client(response_text: str):
    mock_message = MagicMock()
    mock_message.content = [MagicMock(text=response_text)]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_message
    return mock_client


@patch("assessor.anthropic.Anthropic")
def test_prompt_contains_anchor(mock_anthropic_cls):
    mock_anthropic_cls.return_value = _make_mock_client(json.dumps(VALID_RESPONSE))

    from assessor import assess_fit
    assess_fit(SAMPLE_JOB, SAMPLE_PROFILE)

    call_args = mock_anthropic_cls.return_value.messages.create.call_args
    prompt = call_args.kwargs["messages"][0]["content"]
    assert "complete career history" in prompt, "Profile anchor instruction missing from prompt"
    assert "ALL listed roles" in prompt, "Profile anchor missing 'ALL listed roles' instruction"


@patch("assessor.anthropic.Anthropic")
def test_prompt_contains_full_profile(mock_anthropic_cls):
    mock_anthropic_cls.return_value = _make_mock_client(json.dumps(VALID_RESPONSE))

    from assessor import assess_fit
    assess_fit(SAMPLE_JOB, SAMPLE_PROFILE)

    call_args = mock_anthropic_cls.return_value.messages.create.call_args
    prompt = call_args.kwargs["messages"][0]["content"]
    assert "Credit Suisse" in prompt, "Credit Suisse role missing from prompt"
    assert "K-means" in prompt, "Adaptive VWAP / K-means detail missing from prompt"
    assert "Random Forest" in prompt, "Random Forest detail missing from prompt"
    assert "Citigroup" in prompt, "Citigroup role missing from prompt"


@patch("assessor.anthropic.Anthropic")
def test_returns_parsed_fit_result(mock_anthropic_cls):
    mock_anthropic_cls.return_value = _make_mock_client(json.dumps(VALID_RESPONSE))

    from assessor import assess_fit
    result = assess_fit(SAMPLE_JOB, SAMPLE_PROFILE)

    assert result["fit_score"] == 9
    assert result["recommendation"] == "Apply"


@patch("assessor.anthropic.Anthropic")
def test_strips_markdown_fences(mock_anthropic_cls):
    fenced = f"```json\n{json.dumps(VALID_RESPONSE)}\n```"
    mock_anthropic_cls.return_value = _make_mock_client(fenced)

    from assessor import assess_fit
    result = assess_fit(SAMPLE_JOB, SAMPLE_PROFILE)

    assert result["fit_score"] == 9


@patch("assessor.anthropic.Anthropic")
def test_returns_failure_dict_on_bad_json(mock_anthropic_cls):
    mock_anthropic_cls.return_value = _make_mock_client("not valid json {{")

    from assessor import assess_fit
    result = assess_fit(SAMPLE_JOB, SAMPLE_PROFILE)

    assert result["fit_score"] == 0
    assert result["recommendation"] == "Manual review needed"


@patch("assessor.anthropic.Anthropic")
def test_ai_role_hint_injected(mock_anthropic_cls):
    mock_anthropic_cls.return_value = _make_mock_client(json.dumps(VALID_RESPONSE))

    from assessor import assess_fit
    ai_job = {**SAMPLE_JOB, "title": "Senior AI Engineer"}
    assess_fit(ai_job, SAMPLE_PROFILE)

    prompt = mock_anthropic_cls.return_value.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "ASSESSMENT NOTE" in prompt
    assert "financial industry background" in prompt


@patch("assessor.anthropic.Anthropic")
def test_non_ai_role_no_hint(mock_anthropic_cls):
    mock_anthropic_cls.return_value = _make_mock_client(json.dumps(VALID_RESPONSE))

    from assessor import assess_fit
    assess_fit(SAMPLE_JOB, SAMPLE_PROFILE)

    prompt = mock_anthropic_cls.return_value.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "ASSESSMENT NOTE" not in prompt
