# sheets.py
# Handles all Google Sheets interactions:
#   - Reading seen job URLs (for deduplication)
#   - Reading the user profile from the Profile tab
#   - Appending new job rows to the Jobs tab

import os
import json
from datetime import datetime

import gspread
from google.oauth2.service_account import Credentials

from config import JOBS_TAB, PROFILE_TAB, JOBS_COLUMNS


SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]


def _get_sheet():
    """Authenticate and return the main spreadsheet."""
    creds_json = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]
    creds_dict = json.loads(creds_json)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    client = gspread.authorize(creds)
    sheet_id = os.environ["SHEET_ID"]
    return client.open_by_key(sheet_id)


def get_seen_urls() -> set[str]:
    """
    Return the set of job URLs already recorded in the Jobs tab.
    Used to deduplicate — we only process roles not already in the sheet.
    """
    spreadsheet = _get_sheet()

    try:
        worksheet = spreadsheet.worksheet(JOBS_TAB)
        # URL is column F (index 5, 0-based)
        urls = worksheet.col_values(6)  # gspread uses 1-based column index
        return set(urls[1:])            # skip header row
    except gspread.exceptions.WorksheetNotFound:
        # First run — create the Jobs tab with headers
        worksheet = spreadsheet.add_worksheet(title=JOBS_TAB, rows=1000, cols=len(JOBS_COLUMNS))
        worksheet.append_row(JOBS_COLUMNS)
        return set()


def get_profile() -> str:
    """
    Read the user profile from the Profile tab.
    Expects the profile to be written as plain text in cell A1,
    or as key-value rows (Field | Value) starting from row 1.
    Returns a single string for the LLM.
    """
    spreadsheet = _get_sheet()

    try:
        worksheet = spreadsheet.worksheet(PROFILE_TAB)
        all_values = worksheet.get_all_values()

        if not all_values:
            return ""

        # If single cell, return as-is
        if len(all_values[0]) == 1:
            return "\n".join(row[0] for row in all_values if row[0])

        # If key-value rows, format as "Key: Value"
        lines = []
        for row in all_values:
            if len(row) >= 2 and row[0]:
                lines.append(f"{row[0]}: {row[1]}")
        return "\n".join(lines)

    except gspread.exceptions.WorksheetNotFound:
        print("[sheets] Profile tab not found — returning empty profile")
        return ""


def append_jobs(jobs: list[dict]) -> None:
    """
    Append new job rows to the Jobs tab.
    Each job dict must contain keys from assess_fit() merged with fetch_jobs().
    """
    spreadsheet = _get_sheet()
    worksheet = spreadsheet.worksheet(JOBS_TAB)
    today = datetime.today().strftime("%Y-%m-%d")

    rows = []
    for job in jobs:
        row = [
            today,
            job.get("company", ""),
            job.get("title", ""),
            job.get("location", ""),
            job.get("department", ""),
            job.get("url", ""),
            job.get("fit_score", ""),
            job.get("key_strengths", ""),
            job.get("key_gaps", ""),
            job.get("recommendation", ""),
            job.get("reasoning", "")
        ]
        rows.append(row)

    worksheet.append_rows(rows, value_input_option="RAW")
    print(f"[sheets] Appended {len(rows)} row(s)")
