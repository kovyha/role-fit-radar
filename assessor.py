# assessor.py
# Uses the Claude API to assess fit between a job and the user's profile.
# Returns structured JSON: fit score, strengths, gaps, recommendation, reasoning.

import os
import json
import anthropic


def assess_fit(job: dict, profile: str) -> dict:
    """
    Ask Claude to assess how well a job matches the user's profile.

    Args:
        job:     Job dict with keys: title, url, location, department, content
        profile: User profile as plain text read from the Profile sheet tab

    Returns:
        Dict with keys: fit_score, key_strengths, key_gaps, recommendation, reasoning
    """
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    prompt = f"""You are assessing the fit between a candidate profile and a job description.
Be direct and adversarial — surface real gaps, not just positives. Do not pad.

CANDIDATE PROFILE:
{profile}

JOB TITLE: {job['title']}
DEPARTMENT: {job['department']}
LOCATION: {job['location']}

JOB DESCRIPTION:
{job['content']}

Assess the fit and respond ONLY with a JSON object. No preamble, no markdown, no backticks.
Use exactly this structure:
{{
  "fit_score": <integer 1-10>,
  "key_strengths": "<2-3 sentences on strongest matches>",
  "key_gaps": "<2-3 sentences on most significant gaps or risks>",
  "recommendation": "<one of: Apply / Maybe / Skip>",
  "reasoning": "<1-2 sentences overall verdict>"
}}"""

    try:
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}]
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
        print(f"[assessor] Failed to assess {job['title']}: {e}")
        return {
            "fit_score": 0,
            "key_strengths": "Assessment failed",
            "key_gaps": "Assessment failed",
            "recommendation": "Manual review needed",
            "reasoning": str(e)
        }
