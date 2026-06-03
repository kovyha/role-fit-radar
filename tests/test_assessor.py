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
    "unmet_required_quals": [],
    "fit_score": 9,
    "key_strengths": "18 years in algo execution. Production VWAP and ML models at Credit Suisse.",
    "key_gaps": "No pure alpha research background.",
    "recommendation": "Apply",
    "reasoning": "Strong execution engineering fit across all three roles.",
}


@pytest.fixture(autouse=True)
def fake_api_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")


def _make_mock_response(response_text: str):
    mock_message = MagicMock()
    mock_message.content = [MagicMock(text=response_text)]
    return mock_message


def _get_system_text(call_args) -> str:
    system_blocks = call_args.kwargs["system"]
    return " ".join(b["text"] for b in system_blocks)


@patch("assessor._client")
def test_prompt_contains_anchor(mock_client):
    mock_client.messages.create.return_value = _make_mock_response(json.dumps(VALID_RESPONSE))

    from assessor import assess_fit
    assess_fit(SAMPLE_JOB, SAMPLE_PROFILE)

    system = _get_system_text(mock_client.messages.create.call_args)
    assert "complete career history" in system, "Profile anchor instruction missing from system"
    assert "ALL listed roles" in system, "Profile anchor missing 'ALL listed roles' instruction"


@patch("assessor._client")
def test_prompt_contains_full_profile(mock_client):
    mock_client.messages.create.return_value = _make_mock_response(json.dumps(VALID_RESPONSE))

    from assessor import assess_fit
    assess_fit(SAMPLE_JOB, SAMPLE_PROFILE)

    system = _get_system_text(mock_client.messages.create.call_args)
    assert "Credit Suisse" in system, "Credit Suisse role missing from system"
    assert "K-means" in system, "Adaptive VWAP / K-means detail missing from system"
    assert "Random Forest" in system, "Random Forest detail missing from system"
    assert "Citigroup" in system, "Citigroup role missing from system"


@patch("assessor._client")
def test_returns_parsed_fit_result(mock_client):
    mock_client.messages.create.return_value = _make_mock_response(json.dumps(VALID_RESPONSE))

    from assessor import assess_fit
    result = assess_fit(SAMPLE_JOB, SAMPLE_PROFILE)

    assert result["fit_score"] == 9
    assert result["recommendation"] == "Apply"


@patch("assessor._client")
def test_strips_markdown_fences(mock_client):
    fenced = f"```json\n{json.dumps(VALID_RESPONSE)}\n```"
    mock_client.messages.create.return_value = _make_mock_response(fenced)

    from assessor import assess_fit
    result = assess_fit(SAMPLE_JOB, SAMPLE_PROFILE)

    assert result["fit_score"] == 9


@patch("assessor._client")
def test_returns_failure_dict_on_bad_json(mock_client):
    mock_client.messages.create.return_value = _make_mock_response("not valid json {{")

    from assessor import assess_fit
    result = assess_fit(SAMPLE_JOB, SAMPLE_PROFILE)

    assert result["fit_score"] == 0
    assert result["recommendation"] == "Manual review needed"


@patch("assessor._client")
def test_ai_role_hint_injected(mock_client):
    mock_client.messages.create.return_value = _make_mock_response(json.dumps(VALID_RESPONSE))

    from assessor import assess_fit
    ai_job = {**SAMPLE_JOB, "title": "Senior AI Engineer"}
    assess_fit(ai_job, SAMPLE_PROFILE)

    prompt = mock_client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "ASSESSMENT NOTE" in prompt
    assert "financial industry background" in prompt


@patch("assessor._client")
def test_non_ai_role_no_hint(mock_client):
    mock_client.messages.create.return_value = _make_mock_response(json.dumps(VALID_RESPONSE))

    from assessor import assess_fit
    assess_fit(SAMPLE_JOB, SAMPLE_PROFILE)

    prompt = mock_client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "ASSESSMENT NOTE" not in prompt


@patch("assessor._client")
def test_prompt_contains_required_quals_rubric(mock_client):
    mock_client.messages.create.return_value = _make_mock_response(json.dumps(VALID_RESPONSE))

    from assessor import assess_fit
    assess_fit(SAMPLE_JOB, SAMPLE_PROFILE)

    prompt = mock_client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "SCORING RUBRIC" in prompt, "Required-quals rubric block missing from prompt"
    assert "unmet_required_quals" in prompt, "unmet_required_quals field missing from rubric"
    assert "1 unmet" in prompt, "Single-miss cap reference missing from rubric"
    assert "2+ unmet" in prompt, "Double-miss cap reference missing from rubric"


@patch("assessor._client")
def test_cap_enforced_one_unmet(mock_client):
    response = {**VALID_RESPONSE, "unmet_required_quals": ["Must have C++ experience"], "fit_score": 8}
    mock_client.messages.create.return_value = _make_mock_response(json.dumps(response))

    from assessor import assess_fit
    result = assess_fit(SAMPLE_JOB, SAMPLE_PROFILE)

    assert result["fit_score"] == 6, "Score should be capped at 6 for one unmet required qual"
    assert result["unmet_required_quals"] == ["Must have C++ experience"]


@patch("assessor._client")
def test_cap_enforced_two_unmet(mock_client):
    response = {
        **VALID_RESPONSE,
        "unmet_required_quals": ["Must have C++ experience", "Fixed-income domain required"],
        "fit_score": 7,
    }
    mock_client.messages.create.return_value = _make_mock_response(json.dumps(response))

    from assessor import assess_fit
    result = assess_fit(SAMPLE_JOB, SAMPLE_PROFILE)

    assert result["fit_score"] == 4, "Score should be capped at 4 for two+ unmet required quals"


@patch("assessor._client")
def test_no_cap_when_no_unmet(mock_client):
    response = {**VALID_RESPONSE, "unmet_required_quals": [], "fit_score": 9}
    mock_client.messages.create.return_value = _make_mock_response(json.dumps(response))

    from assessor import assess_fit
    result = assess_fit(SAMPLE_JOB, SAMPLE_PROFILE)

    assert result["fit_score"] == 9, "Score should be unchanged when no unmet required quals"
