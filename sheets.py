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
        first_row = worksheet.row_values(1)
        if not first_row or first_row[0] != JOBS_COLUMNS[0]:
            worksheet.insert_row(JOBS_COLUMNS, index=1)
        worksheet.set_basic_filter()
        # URL is now column G (1-based, after Source column was added)
        urls = worksheet.col_values(7)  # gspread uses 1-based column index
        return set(urls[1:])            # skip header row
    except gspread.exceptions.WorksheetNotFound:
        # First run — create the Jobs tab with headers
        worksheet = spreadsheet.add_worksheet(title=JOBS_TAB, rows=1000, cols=len(JOBS_COLUMNS))
        worksheet.append_row(JOBS_COLUMNS)
        worksheet.set_basic_filter()
        return set()


def get_seen_title_company_keys() -> dict[str, str]:
    """
    Return a mapping of normalised 'title|company' key -> original URL for rows
    already recorded in the Jobs tab.  The URL enables audit trails on dup rows.
    Reads from a dedicated 'Dedup Key' column for a single API call per run.
    Self-healing: adds the column header and back-populates existing rows on first call.
    """
    spreadsheet = _get_sheet()

    try:
        worksheet = spreadsheet.worksheet(JOBS_TAB)
        all_rows = worksheet.get_all_values()
        if not all_rows:
            return {}

        header = all_rows[0]
        try:
            title_col   = header.index("Title")    # 0-based
            company_col = header.index("Company")  # 0-based
            url_col     = header.index("URL")       # 0-based
        except ValueError:
            return {}

        if "Dedup Key" in header:
            dedup_col  = header.index("Dedup Key")
            col_exists = True
        else:
            dedup_col  = len(header)  # new column at end
            col_exists = False
            worksheet.update_cell(1, dedup_col + 1, "Dedup Key")  # 1-based

        seen           = {}   # key -> url
        cells_to_write = []

        for i, row in enumerate(all_rows[1:], start=2):  # row 2 = first data row (1-based)
            url      = row[url_col]     if url_col     < len(row) else ""
            existing = row[dedup_col]   if (col_exists and dedup_col < len(row)) else ""
            if existing:
                seen[existing] = url
            else:
                title   = row[title_col]   if title_col   < len(row) else ""
                company = row[company_col] if company_col < len(row) else ""
                if title and company:
                    computed = f"{title.lower()}|{company.lower()}"
                    seen[computed] = url
                    cells_to_write.append(gspread.Cell(i, dedup_col + 1, computed))

        if cells_to_write:
            worksheet.update_cells(cells_to_write)
            print(f"[sheets] Back-populated Dedup Key for {len(cells_to_write)} existing row(s)")

        return seen

    except gspread.exceptions.WorksheetNotFound:
        return {}


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
    today = datetime.today().strftime("%Y-%m-%d %H:%M")

    rows = []
    for job in jobs:
        title   = job.get("title", "")
        company = job.get("company", "")
        row = [
            today,
            company,
            job.get("source", ""),
            title,
            job.get("location", ""),
            job.get("department", ""),
            job.get("url", ""),
            job.get("fit_score", ""),
            job.get("key_strengths", ""),
            job.get("key_gaps", ""),
            job.get("recommendation", ""),
            job.get("reasoning", ""),
            f"{title.lower()}|{company.lower()}",
        ]
        rows.append(row)

    worksheet.append_rows(rows, value_input_option="RAW")
    print(f"[sheets] Appended {len(rows)} row(s)")
