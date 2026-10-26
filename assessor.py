# assessor.py
# Uses the Claude API to assess fit between a job and the user's profile.
# Returns structured JSON: fit score, strengths, gaps, recommendation, reasoning.

import os
import json
import logging
import anthropic
from config import (
    CLAUDE_MODEL, ASSESSOR_MAX_TOKENS, ASSESSOR_EFFORT, KEYWORD_ASSESS_HINTS,
    UNMET_REQUIRED_SCORE_CAPS, RECOMMENDATION_THRESHOLDS,
)

_client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))

_LABEL_RANK = {"Skip": 0, "Maybe": 1, "Apply": 2}
# The Profile tab asks the model to start the reasoning with this marker for roles that
# mirror the Morgan Stanley role, and to keep them at Maybe or better for manual review.
MS_MIRROR_PREFIX = "MS-MIRROR:"


def _label_for_score(score: int) -> str:
    for threshold, label in RECOMMENDATION_THRESHOLDS:
        if score >= threshold:
            return label
    return "Skip"


def _final_recommendation(result: dict) -> str:
    """Lower of the model's label and the capped score's band, floored at Maybe for MS-MIRROR roles."""
    label = _label_for_score(result.get("fit_score", 0))
    model_label = result.get("recommendation")
    if model_label in _LABEL_RANK:
        label = min(label, model_label, key=_LABEL_RANK.get)
    if result.get("reasoning", "").startswith(MS_MIRROR_PREFIX) and _LABEL_RANK[label] < _LABEL_RANK["Maybe"]:
        label = "Maybe"
    return label


def assess_fit(job: dict, profile: str) -> dict:
    """
    Ask Claude to assess how well a job matches the user's profile.

    Args:
        job:     Job dict with keys: title, url, location, department, content
        profile: User profile as plain text read from the Profile sheet tab

    Returns:
        Dict with keys: role_summary, required_quals_evidence, unmet_required_quals, fit_score,
        key_strengths, key_gaps, recommendation, reasoning
    """

    title_lower = job["title"].lower()
    hints = [
        hint
        for keywords, hint in KEYWORD_ASSESS_HINTS
        if any(kw in title_lower for kw in keywords)
    ]
    hint_block = ("\n\nASSESSMENT NOTE: " + " ".join(hints)) if hints else ""

    system_text = (
        "You are assessing the fit between a candidate profile and a job description. "
        "Be direct and adversarial — surface real gaps, not just positives. Do not pad.\n\n"
        "Tone: you are assessing fit, not reviewing a CV. Use no praising or intensifying adjectives "
        "(e.g. exceptional, outstanding, world-class, impressive, strong, deep, extensive, proven) in any field. "
        "State what the candidate did and what the role needs, and let the facts carry the weight.\n\n"
        "Evidence: every strength claim must cite the profile row it comes from in square brackets, using the "
        "row's label (e.g. [Role 2], [AI / LLM Engineering]), and name the JD requirement it matches. "
        "Leave out any strength you cannot cite.\n\n"
        "Read the complete career history in the candidate profile. Draw on ALL listed roles "
        "when assessing strengths — recent roles reflect current scope but earlier roles may "
        "contain the deepest domain expertise.\n\n"
        f"CANDIDATE PROFILE:\n{profile}\n\n"
        "SCORING RUBRIC:\n"
        "1. Identify all qualifications labeled Required, Must Have, Minimum Qualifications, or equivalent hard-requirement language.\n"
        "2. For each required qualification, add an entry to \"required_quals_evidence\": quote the profile line that "
        "meets it (or \"none\"), give the year the candidate last did it hands-on (from the role dates; \"none\" if "
        "never hands-on), and say whether the evidence is hands-on or review/oversight. Then decide whether the candidate "
        "meets it, and list every unmet one verbatim in \"unmet_required_quals\". Any requirement whose evidence is "
        "\"none\" is unmet.\n"
        "3. Preferred, Nice-to-Have, or Plus qualifications do not belong in \"unmet_required_quals\".\n"
        "   Degree equivalence: UK integrated Master's degrees (MEng, MSci, MMath, MPhys, MChem) are Master's-level "
        "qualifications (FHEQ Level 7), equivalent to an MS/MSc. They satisfy any Master's, MS, MSc, postgraduate or "
        "'advanced degree' level requirement — never describe such a candidate as lacking a Master's. Assess the "
        "subject separately: engineering, computer science, mathematics and physics count as quantitative STEM "
        "fields. Wording like 'or related field', 'or similar' or 'or equivalent' is satisfied by any adjacent STEM degree "
        "(e.g. an engineering or information-systems degree against a CS/Maths/Physics list). Only flag a subject gap "
        "when the JD requires a specific discipline with no such allowance (e.g. 'Master's in Finance'). "
        "A PhD requirement is not met by a Master's.\n"
        "4. Set fit_score freely based on overall fit, then it will be capped externally: 1 unmet → max 6, 2+ unmet → max 4.\n"
        "5. Call out any unmet required qualifications explicitly at the start of key_gaps.\n\n"
        "Respond ONLY with a JSON object. No preamble, no markdown, no backticks. Use exactly this structure:\n"
        "{\n"
        "  \"role_summary\": \"<max 40 words, neutral: what the role is — team/desk, core responsibilities, seniority, key tech or asset class. No fit judgement>\",\n"
        "  \"required_quals_evidence\": [{\"requirement\": \"<verbatim required qualification>\", "
        "\"evidence\": \"<profile line that meets it, or none>\", \"last_hands_on_year\": \"<YYYY or none>\", "
        "\"mode\": \"<hands-on / review/oversight / none>\"}, ...],\n"
        "  \"unmet_required_quals\": [\"<verbatim required qualification that is unmet>\", ...],\n"
        "  \"fit_score\": <integer 1-10>,\n"
        "  \"key_strengths\": \"<2-3 sentences on the closest matches, each claim ending with its [profile row] citation>\",\n"
        "  \"key_gaps\": \"<2-3 sentences on most significant gaps or risks>\",\n"
        "  \"recommendation\": \"<one of: Apply / Maybe / Skip>\",\n"
        "  \"reasoning\": \"<1-2 sentences overall verdict>\"\n"
        "}"
    )

    prompt = f"""Assess the fit for the following role.{hint_block}

JOB TITLE: {job['title']}
DEPARTMENT: {job['department']}
LOCATION: {job['location']}

JOB DESCRIPTION:
{job['content']}"""

    # Effort is only sent when configured: Haiku 4.5 rejects it, Haiku 5.5+ uses it to set thinking depth
    effort_kwargs = {"output_config": {"effort": ASSESSOR_EFFORT}} if ASSESSOR_EFFORT else {}

    try:
        message = _client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=ASSESSOR_MAX_TOKENS,
            system=[{"type": "text", "text": system_text, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": prompt}],
            **effort_kwargs,
        )

        # A truncated response leaves the JSON cut off mid-string; report that
        # directly rather than surfacing an opaque JSONDecodeError.
        if message.stop_reason == "max_tokens":
            raise ValueError(f"Response truncated at ASSESSOR_MAX_TOKENS={ASSESSOR_MAX_TOKENS} — JSON incomplete")
        if message.stop_reason == "refusal":
            category = getattr(getattr(message, "stop_details", None), "category", None)
            raise ValueError(f"Declined by model safety classifier (category: {category})")

        # Models that think return thinking blocks before the answer, so find the text block by type
        text = next((b.text for b in message.content if b.type == "text"), None)
        if text is None:
            raise ValueError("Response contained no text block")
        raw = text.strip()

        # Strip accidental markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        result = json.loads(raw)

        unmet = result.get("unmet_required_quals", [])
        n = min(len(unmet), max(UNMET_REQUIRED_SCORE_CAPS))
        if n in UNMET_REQUIRED_SCORE_CAPS:
            result["fit_score"] = min(result.get("fit_score", 0), UNMET_REQUIRED_SCORE_CAPS[n])
        result["recommendation"] = _final_recommendation(result)

        return result

    except Exception as e:
        logging.getLogger(__name__).error("[assessor] Failed to assess %s: %s", job['title'], e)
        return {
            "assessment_failed": True,
            "fit_score": 0,
            "key_strengths": "Assessment failed",
            "key_gaps": "Assessment failed",
            "recommendation": "Manual review needed",
            "reasoning": str(e)
        }
