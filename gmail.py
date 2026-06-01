# gmail.py
# Sends a summary email via Gmail SMTP using an App Password.
# Simpler and more reliable than the Gmail API for this use case.
# App Password setup: Google Account → Security → 2-Step Verification → App Passwords

import os
import smtplib
import urllib.parse
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from collections import Counter
from datetime import date

from config import CV_AI_KEYWORDS, CV_QUANT_KEYWORDS, CV_VARIANTS, EMAIL_RECIPIENT, EMAIL_SENDER


def _select_cv_variant(job: dict) -> str:
    """Pick the most relevant CV variant based on keywords in the job."""
    text = " ".join([
        job.get("title", ""),
        job.get("department", ""),
        job.get("content", ""),
    ]).lower()
    if CV_AI_KEYWORDS and any(kw in text for kw in CV_AI_KEYWORDS):
        return "ai" if "ai" in CV_VARIANTS else "main"
    if CV_QUANT_KEYWORDS and any(kw in text for kw in CV_QUANT_KEYWORDS):
        return "quant" if "quant" in CV_VARIANTS else "main"
    return "main"


def _ask_ai_url(job: dict, variant_key: str) -> str:
    """Build a claude.ai/new URL with the job context pre-filled as the opening prompt."""
    cv_file = CV_VARIANTS[variant_key]
    prompt = (
        f"I'm preparing my application for the following role and need your help.\n\n"
        f"Please fetch and read my CV from Google Drive: **{cv_file}**\n\n"
        f"Once you have it, help me with whatever I ask next (cover letter, fit assessment, "
        f"interview prep, etc.).\n\n"
        f"---\n"
        f"JOB TITLE: {job.get('title', '')}\n"
        f"COMPANY: {job.get('company', '')}\n"
        f"LOCATION: {job.get('location', '')}\n\n"
        f"JOB DESCRIPTION:\n{job.get('content', '')}"
    )
    return f"https://claude.ai/new?q={urllib.parse.quote(prompt)}"


def send_summary(jobs: list[dict], pending_companies: list[dict] | None = None) -> None:
    """
    Send an HTML email summarising newly found roles and their fit assessments.
    If no jobs found, sends a status email confirming the scan ran.

    Args:
        jobs: List of job dicts, each containing assessment fields from assessor.py
        pending_companies: Companies not scanned because the time budget was reached.
                           When provided, the email is flagged as a partial run.
    """
    pending_companies = pending_companies or []
    html = _build_html(jobs, pending_companies)
    plain = _build_plain(jobs, pending_companies)

    if jobs:
        counts = Counter(j.get("recommendation", "") for j in jobs)
        n_apply = counts.get("Apply", 0)
        n_maybe = counts.get("Maybe", 0)
        n_skip  = counts.get("Skip", 0)
        today   = date.today().strftime("%Y-%m-%d")

        # Lead with actionable counts when there's something worth acting on
        if n_apply or n_maybe:
            parts = []
            if n_apply:
                parts.append(f"{n_apply} Apply")
            if n_maybe:
                parts.append(f"{n_maybe} Maybe")
            prefix = " + ".join(parts)
            subject = f"[{prefix}] Role Fit Radar — {today}"
            if n_skip:
                subject += f" ({n_skip} Skip)"
        else:
            subject = f"Role Fit Radar — {n_skip} Skip — {today}"
    else:
        subject = f"Role Fit Radar — No new roles — {date.today().strftime('%Y-%m-%d')}"

    if pending_companies:
        subject = f"[PARTIAL] {subject}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = EMAIL_SENDER
    msg["To"] = EMAIL_RECIPIENT

    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html, "html"))

    password = os.environ["GMAIL_APP_PASSWORD"]

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_SENDER, password)
            server.sendmail(EMAIL_SENDER, EMAIL_RECIPIENT, msg.as_string())
        print(f"[gmail] Summary email sent — {len(jobs)} role(s)")
    except Exception as e:
        print(f"[gmail] Failed to send email: {e}")


def _partial_banner_html(pending_companies: list[dict]) -> str:
    if not pending_companies:
        return ""
    items = "".join(
        f"<li>{c['name']} ({c.get('source', '?')})</li>"
        for c in pending_companies
    )
    return f"""
        <div style="background:#fff8e1;border:1px solid #f9a825;border-radius:4px;padding:12px 16px;margin-bottom:20px;">
            <strong style="color:#e65100;">Partial Run — Time Limit Reached</strong>
            <p style="margin:8px 0 4px;">
                The scan hit the 60-minute GitHub Actions limit.
                The following <strong>{len(pending_companies)} source(s)</strong> were not scanned:
            </p>
            <ul style="margin:4px 0 8px;padding-left:20px;">{items}</ul>
            <p style="margin:0;font-size:12px;color:#666;">
                Results above reflect only the sources that completed.
                Skipped sources will be re-scanned in the next run.
            </p>
        </div>"""


def _build_html(jobs: list[dict], pending_companies: list[dict] | None = None) -> str:
    """Build an HTML email body with 3 separate tables (Apply, Maybe, Skip)."""
    pending_companies = pending_companies or []
    banner = _partial_banner_html(pending_companies)

    if not jobs:
        no_roles_msg = (
            "Scan ran but no new matching roles were found in the sources that completed."
            if pending_companies
            else "Scan completed successfully. No new matching roles were found today."
        )
        return f"""
    <html><body style="font-family:Arial,sans-serif;color:#1a1a1a;max-width:900px;margin:0 auto;">
        <h2 style="border-bottom:2px solid #333;padding-bottom:8px;">
            Role Fit Radar — No New Roles Found
        </h2>
        {banner}
        <p style="color:#666;font-size:14px;">{no_roles_msg}</p>
        <p style="color:#999;font-size:12px;margin-top:24px;">
            Generated by role-fit-radar · Assessed by Claude
        </p>
    </body></html>"""

    groups = {"Apply": [], "Maybe": [], "Skip": []}
    for job in jobs:
        rec = job.get("recommendation", "")
        if rec in groups:
            groups[rec].append(job)

    def _table_html(recommendation: str, job_list: list[dict]) -> str:
        if not job_list:
            return ""

        colour = {"Apply": "#2e7d32", "Maybe": "#0277bd", "Skip": "#757575"}.get(recommendation, "#333")
        rows = ""
        for job in job_list:
            sheet_url = job.get("sheet_url", "")
            sheet_link = (
                f' &nbsp;<a href="{sheet_url}" style="font-size:11px;color:#888;">sheet ↗</a>'
                if sheet_url and recommendation == "Apply" else ""
            )

            ask_ai_html = ""
            if recommendation in ("Apply", "Maybe"):
                auto_key = _select_cv_variant(job)
                auto_label = {"main": "main CV", "ai": "AI CV", "quant": "quant CV"}[auto_key]
                override_keys = [k for k in CV_VARIANTS if k != auto_key]
                override_links = " · ".join(
                    f'<a href="{_ask_ai_url(job, k)}" style="color:#888;">{k}</a>'
                    for k in override_keys
                )
                ask_ai_html = (
                    f'&nbsp;&nbsp;<a href="{_ask_ai_url(job, auto_key)}" '
                    f'style="font-size:11px;background:#6200ea;color:#fff;padding:2px 7px;'
                    f'border-radius:3px;text-decoration:none;">Ask AI ({auto_label}) ↗</a>'
                    f'&nbsp;<small style="color:#aaa;">or: {override_links}</small>'
                )

            rows += f"""
        <tr>
            <td style="padding:8px;border-bottom:1px solid #eee;">
                <a href="{job.get('url', '')}" style="font-weight:bold;color:#1a1a1a;">{job.get('title', '')}</a>{sheet_link}{ask_ai_html}<br>
                <small style="color:#666;">{job.get('company', '')} · {job.get('department', '')} · {job.get('location', '')} · {job.get('source', '')}</small>
            </td>
            <td style="padding:8px;border-bottom:1px solid #eee;text-align:center;">
                <strong>{job.get('fit_score', '')}/10</strong>
            </td>
            <td style="padding:8px;border-bottom:1px solid #eee;text-align:center;color:{colour};">
                <strong>{recommendation}</strong>
            </td>
            <td style="padding:8px;border-bottom:1px solid #eee;font-size:13px;">
                <strong>Strengths:</strong> {job.get('key_strengths', '')}<br><br>
                <strong>Gaps:</strong> {job.get('key_gaps', '')}<br><br>
                <em>{job.get('reasoning', '')}</em>
            </td>
        </tr>"""

        return f"""
        <h3 style="color:{colour};margin-top:24px;margin-bottom:12px;">
            {recommendation} ({len(job_list)})
        </h3>
        <table style="width:100%;border-collapse:collapse;">
            <thead>
                <tr style="background:#f5f5f5;">
                    <th style="padding:8px;text-align:left;">Role</th>
                    <th style="padding:8px;">Fit Score</th>
                    <th style="padding:8px;">Recommendation</th>
                    <th style="padding:8px;text-align:left;">Assessment</th>
                </tr>
            </thead>
            <tbody>{rows}</tbody>
        </table>"""

    tables = _table_html("Apply", groups["Apply"]) + \
             _table_html("Maybe", groups["Maybe"]) + \
             _table_html("Skip", groups["Skip"])

    return f"""
    <html><body style="font-family:Arial,sans-serif;color:#1a1a1a;max-width:900px;margin:0 auto;">
        <h2 style="border-bottom:2px solid #333;padding-bottom:8px;">
            Role Fit Radar — {len(jobs)} New Role{"s" if len(jobs) > 1 else ""} Found
        </h2>
        {banner}
        {tables}
        <p style="color:#999;font-size:12px;margin-top:24px;">
            Generated by role-fit-radar · Assessed by Claude
        </p>
    </body></html>"""


def _build_plain(jobs: list[dict], pending_companies: list[dict] | None = None) -> str:
    """Build a plain text fallback email body."""
    pending_companies = pending_companies or []

    partial_notice = ""
    if pending_companies:
        names = ", ".join(c["name"] for c in pending_companies)
        partial_notice = (
            f"\n[PARTIAL RUN — Time limit reached]\n"
            f"{len(pending_companies)} source(s) not scanned: {names}\n"
            "These sources will be re-scanned in the next run.\n"
        )

    if not jobs:
        no_roles_msg = (
            "Scan ran but no new matching roles were found in the sources that completed."
            if pending_companies
            else "Scan completed successfully. No new matching roles were found today."
        )
        return f"Role Fit Radar — No new roles found\n{partial_notice}\n{no_roles_msg}\n"

    lines = [f"Role Fit Radar — {len(jobs)} new role(s) found\n{partial_notice}"]
    for job in jobs:
        entry = [
            f"{'='*60}",
            f"Role:           {job.get('title', '')}",
            f"Company:        {job.get('company', '')}",
            f"Department:     {job.get('department', '')}",
            f"Location:       {job.get('location', '')}",
            f"Source:         {job.get('source', '')}",
            f"URL:            {job.get('url', '')}",
            f"Fit Score:      {job.get('fit_score', '')}/10",
            f"Recommendation: {job.get('recommendation', '')}",
            f"Strengths:      {job.get('key_strengths', '')}",
            f"Gaps:           {job.get('key_gaps', '')}",
            f"Verdict:        {job.get('reasoning', '')}",
        ]
        if job.get("recommendation") == "Apply" and job.get("sheet_url"):
            entry.append(f"Sheet row:      {job['sheet_url']}")
        entry.append("")
        lines += entry
    return "\n".join(lines)
