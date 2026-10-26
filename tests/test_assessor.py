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
    mock_message.content = [MagicMock(type="text", text=response_text)]
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

    system = _get_system_text(mock_client.messages.create.call_args)
    assert "SCORING RUBRIC" in system, "Required-quals rubric block missing from prompt"
    assert "unmet_required_quals" in system, "unmet_required_quals field missing from rubric"
    assert "1 unmet" in system, "Single-miss cap reference missing from rubric"
    assert "2+ unmet" in system, "Double-miss cap reference missing from rubric"


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


_THRESHOLDS = patch("assessor.RECOMMENDATION_THRESHOLDS", [(7, "Apply"), (4, "Maybe")])


def _assess_with(mock_client, **overrides):
    mock_client.messages.create.return_value = _make_mock_response(json.dumps({**VALID_RESPONSE, **overrides}))
    from assessor import assess_fit
    with _THRESHOLDS:
        return assess_fit(SAMPLE_JOB, SAMPLE_PROFILE)


@patch("assessor._client")
def test_capped_score_downgrades_model_apply(mock_client):
    result = _assess_with(mock_client, fit_score=8, recommendation="Apply",
                          unmet_required_quals=["Must have C++", "Fixed-income domain required"])

    assert result["fit_score"] == 4
    assert result["recommendation"] == "Maybe", "A capped 4/10 must not stay Apply"


@patch("assessor._client")
def test_score_below_lowest_threshold_is_skip(mock_client):
    result = _assess_with(mock_client, fit_score=3, recommendation="Maybe")

    assert result["recommendation"] == "Skip"


@patch("assessor._client")
def test_score_band_never_raises_model_label(mock_client):
    # e.g. a strong fit the model Skipped because the role is outside London
    result = _assess_with(mock_client, fit_score=9, recommendation="Skip")

    assert result["recommendation"] == "Skip"


@patch("assessor._client")
def test_unrecognised_model_label_uses_score_band(mock_client):
    result = _assess_with(mock_client, fit_score=7, recommendation="Strong yes")

    assert result["recommendation"] == "Apply"


@patch("assessor._client")
def test_ms_mirror_floored_at_maybe(mock_client):
    result = _assess_with(mock_client, fit_score=8, recommendation="Skip",
                          unmet_required_quals=["Must have C++", "Fixed-income domain required", "PhD"],
                          reasoning="MS-MIRROR: Head of EMEA benchmark execution, same scope as MS.")

    assert result["fit_score"] == 4
    assert result["recommendation"] == "Maybe"


@patch("assessor._client")
def test_ms_mirror_does_not_lower_apply(mock_client):
    result = _assess_with(mock_client, fit_score=9, recommendation="Apply",
                          reasoning="MS-MIRROR: Global head of execution technology.")

    assert result["recommendation"] == "Apply"


@patch("assessor._client")
def test_schema_requests_required_quals_evidence(mock_client):
    _assess_with(mock_client)

    system = _get_system_text(mock_client.messages.create.call_args)
    assert '"required_quals_evidence"' in system
    assert '"last_hands_on_year"' in system
    assert "review/oversight" in system


@patch("assessor._client")
def test_prompt_bans_praise_and_requires_strength_citations(mock_client):
    _assess_with(mock_client)

    system = _get_system_text(mock_client.messages.create.call_args)
    assert "no praising or intensifying adjectives" in system
    assert "exceptional" in system, "The observed offender should be named in the ban list"
    assert "every strength claim must cite the profile row" in system
    assert "[profile row] citation" in system, "key_strengths schema should require citations"


@patch("assessor._client")
def test_required_quals_evidence_passed_through(mock_client):
    evidence = [{"requirement": "Production C++", "evidence": "none", "last_hands_on_year": "none", "mode": "none"}]
    result = _assess_with(mock_client, required_quals_evidence=evidence)

    assert result["required_quals_evidence"] == evidence


def _make_truncated_response(response_text: str):
    mock_message = _make_mock_response(response_text)
    mock_message.stop_reason = "max_tokens"
    return mock_message


@patch("assessor._client")
def test_flags_failure_on_truncation_without_retry(mock_client):
    mock_client.messages.create.return_value = _make_truncated_response('{"key_gaps": "cut off')

    from assessor import assess_fit
    result = assess_fit(SAMPLE_JOB, SAMPLE_PROFILE)

    assert mock_client.messages.create.call_count == 1
    assert result["assessment_failed"] is True
    assert result["fit_score"] == 0
    assert "truncated" in result["reasoning"]


@patch("assessor._client")
def test_reads_answer_after_thinking_block(mock_client):
    message = _make_mock_response(json.dumps(VALID_RESPONSE))
    message.content = [MagicMock(type="thinking", thinking=""), *message.content]
    mock_client.messages.create.return_value = message

    from assessor import assess_fit
    result = assess_fit(SAMPLE_JOB, SAMPLE_PROFILE)

    assert "assessment_failed" not in result
    assert result["fit_score"] == VALID_RESPONSE["fit_score"]


@patch("assessor._client")
def test_thinking_only_response_flags_failure(mock_client):
    message = _make_mock_response("")
    message.content = [MagicMock(type="thinking", thinking="")]
    mock_client.messages.create.return_value = message

    from assessor import assess_fit
    result = assess_fit(SAMPLE_JOB, SAMPLE_PROFILE)

    assert result["assessment_failed"] is True
    assert "no text block" in result["reasoning"]


@patch("assessor._client")
def test_refusal_flags_failure_with_category(mock_client):
    message = _make_mock_response("")
    message.content = []
    message.stop_reason = "refusal"
    message.stop_details = MagicMock(category="frontier_llm")
    mock_client.messages.create.return_value = message

    from assessor import assess_fit
    result = assess_fit(SAMPLE_JOB, SAMPLE_PROFILE)

    assert result["assessment_failed"] is True
    assert result["recommendation"] == "Manual review needed", "Declines must stay visible to reassess_failed"
    assert "Declined by model safety classifier (category: frontier_llm)" == result["reasoning"]


@patch("assessor._client")
def test_effort_sent_when_configured(mock_client):
    mock_client.messages.create.return_value = _make_mock_response(json.dumps(VALID_RESPONSE))

    from assessor import assess_fit
    with patch("assessor.ASSESSOR_EFFORT", "high"):
        assess_fit(SAMPLE_JOB, SAMPLE_PROFILE)

    assert mock_client.messages.create.call_args.kwargs["output_config"] == {"effort": "high"}


@patch("assessor._client")
def test_effort_omitted_when_unset(mock_client):
    mock_client.messages.create.return_value = _make_mock_response(json.dumps(VALID_RESPONSE))

    from assessor import assess_fit
    with patch("assessor.ASSESSOR_EFFORT", None):
        assess_fit(SAMPLE_JOB, SAMPLE_PROFILE)

    assert "output_config" not in mock_client.messages.create.call_args.kwargs


@patch("assessor._client")
def test_bad_json_flags_assessment_failed(mock_client):
    mock_client.messages.create.return_value = _make_mock_response("not valid json {{")

    from assessor import assess_fit
    result = assess_fit(SAMPLE_JOB, SAMPLE_PROFILE)

    assert result["assessment_failed"] is True


@patch("assessor._client")
def test_schema_requests_role_summary(mock_client):
    mock_client.messages.create.return_value = _make_mock_response(json.dumps(VALID_RESPONSE))

    from assessor import assess_fit
    assess_fit(SAMPLE_JOB, SAMPLE_PROFILE)

    system = _get_system_text(mock_client.messages.create.call_args)
    assert '"role_summary"' in system


@patch("assessor._client")
def test_role_summary_passed_through(mock_client):
    response = {**VALID_RESPONSE, "role_summary": "Builds VWAP/TWAP algos in C++ for the equities desk."}
    mock_client.messages.create.return_value = _make_mock_response(json.dumps(response))

    from assessor import assess_fit
    result = assess_fit(SAMPLE_JOB, SAMPLE_PROFILE)

    assert result["role_summary"] == response["role_summary"]


@patch("assessor._client")
def test_rubric_treats_uk_integrated_masters_as_masters(mock_client):
    mock_client.messages.create.return_value = _make_mock_response(json.dumps(VALID_RESPONSE))

    from assessor import assess_fit
    assess_fit(SAMPLE_JOB, SAMPLE_PROFILE)

    system = _get_system_text(mock_client.messages.create.call_args)
    assert "MEng" in system and "Master's-level" in system, "UK integrated Master's equivalence missing"
    assert "or related field" in system, "'or related field' allowance missing"
    assert "PhD requirement is not met by a Master's" in system, "PhD guard missing"
