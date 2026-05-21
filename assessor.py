# assessor.py
# Uses the Claude API to assess fit between a job and the user's profile.
# Returns structured JSON: fit score, strengths, gaps, recommendation, reasoning.

import os
import json
import logging
import anthropic
from config import CLAUDE_MODEL, ASSESSOR_MAX_TOKENS, KEYWORD_ASSESS_HINTS

_client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))


def assess_fit(job: dict, profile: str) -> dict:
    """
    Ask Claude to assess how well a job matches the user's profile.

    Args:
        job:     Job dict with keys: title, url, location, department, content
        profile: User profile as plain text read from the Profile sheet tab

    Returns:
        Dict with keys: fit_score, key_strengths, key_gaps, recommendation, reasoning
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
        "Read the complete career history in the candidate profile. Draw on ALL listed roles "
        "when assessing strengths — recent roles reflect current scope but earlier roles may "
        "contain the deepest domain expertise.\n\n"
        f"CANDIDATE PROFILE:\n{profile}"
    )

    prompt = f"""Assess the fit for the following role and respond ONLY with a JSON object. No preamble, no markdown, no backticks.{hint_block}

JOB TITLE: {job['title']}
DEPARTMENT: {job['department']}
LOCATION: {job['location']}

JOB DESCRIPTION:
{job['content']}

Use exactly this structure:
{{
  "fit_score": <integer 1-10>,
  "key_strengths": "<2-3 sentences on strongest matches>",
  "key_gaps": "<2-3 sentences on most significant gaps or risks>",
  "recommendation": "<one of: Apply / Maybe / Skip>",
  "reasoning": "<1-2 sentences overall verdict>"
}}"""

    try:
        message = _client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=ASSESSOR_MAX_TOKENS,
            system=[{"type": "text", "text": system_text, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": prompt}],
        )

        raw = message.content[0].text.strip()

        # Strip accidental markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        return json.loads(raw)

    except Exception as e:
        logging.getLogger(__name__).error("[assessor] Failed to assess %s: %s", job['title'], e)
        return {
            "fit_score": 0,
            "key_strengths": "Assessment failed",
            "key_gaps": "Assessment failed",
            "recommendation": "Manual review needed",
            "reasoning": str(e)
        }
