from unittest.mock import MagicMock, patch
import gspread

from sheets import get_seen_title_company_keys, append_jobs


# ── helpers ──────────────────────────────────────────────────────────────────

_HEADER_WITH_DEDUP = [
    "Date Found", "Company", "Source", "Title", "Location", "Department",
    "URL", "Fit Score (1-10)", "Key Strengths", "Key Gaps", "Recommendation",
    "Reasoning", "Dedup Key",
]
_HEADER_WITHOUT_DEDUP = _HEADER_WITH_DEDUP[:-1]

DEDUP_COL_1BASED = 13  # "Dedup Key" is the 13th column (1-based)


def _row(company, title, dedup_key=""):
    """Return a sheet data row with the given company, title, and dedup key."""
    return [
        "2026-01-01", company, "greenhouse", title, "London", "Eng",
        f"https://example.com/{title}", "8", "s", "g", "Apply", "r", dedup_key,
    ]


def _make_ws(all_rows):
    ws = MagicMock()
    ws.get_all_values.return_value = all_rows
    return ws


def _patch_sheet(ws):
    spreadsheet = MagicMock()
    spreadsheet.worksheet.return_value = ws
    return patch("sheets._get_sheet", return_value=spreadsheet)


# ── get_seen_title_company_keys ───────────────────────────────────────────────

class TestGetSeenTitleCompanyKeys:

    def test_returns_key_to_url_mapping_when_column_fully_populated(self):
        rows = [
            _HEADER_WITH_DEDUP,
            _row("Anthropic", "Senior SWE", "senior swe|anthropic"),
            _row("OpenAI", "Product Manager", "product manager|openai"),
        ]
        ws = _make_ws(rows)
        with _patch_sheet(ws):
            seen = get_seen_title_company_keys()

        assert set(seen.keys()) == {"senior swe|anthropic", "product manager|openai"}
        assert seen["senior swe|anthropic"]    == "https://example.com/Senior SWE"
        assert seen["product manager|openai"]  == "https://example.com/Product Manager"
        ws.update_cells.assert_not_called()

    def test_back_populates_rows_missing_dedup_key(self):
        rows = [
            _HEADER_WITH_DEDUP,
            _row("Anthropic", "Senior SWE", "senior swe|anthropic"),
            _row("OpenAI", "Product Manager", ""),  # missing
        ]
        ws = _make_ws(rows)
        with _patch_sheet(ws):
            seen = get_seen_title_company_keys()

        assert set(seen.keys()) == {"senior swe|anthropic", "product manager|openai"}
        ws.update_cells.assert_called_once()
        cells = ws.update_cells.call_args[0][0]
        assert len(cells) == 1
        assert cells[0].row == 3  # second data row = sheet row 3
        assert cells[0].col == DEDUP_COL_1BASED
        assert cells[0].value == "product manager|openai"

    def test_adds_column_header_and_back_populates_when_column_absent(self):
        # Rows have only 12 columns — no Dedup Key column yet
        rows = [
            _HEADER_WITHOUT_DEDUP,
            _row("Anthropic", "Senior SWE")[:-1],  # strip the dedup col
        ]
        ws = _make_ws(rows)
        with _patch_sheet(ws):
            seen = get_seen_title_company_keys()

        ws.update_cell.assert_called_once_with(1, DEDUP_COL_1BASED, "Dedup Key")
        assert set(seen.keys()) == {"senior swe|anthropic"}
        ws.update_cells.assert_called_once()

    def test_rows_with_no_title_or_company_are_skipped(self):
        rows = [
            _HEADER_WITH_DEDUP,
            ["2026-01-01", "", "greenhouse", "", "London", "Eng", "url", "8", "", "", "", "", ""],
        ]
        ws = _make_ws(rows)
        with _patch_sheet(ws):
            seen = get_seen_title_company_keys()

        assert seen == {}
        ws.update_cells.assert_not_called()

    def test_empty_sheet_returns_empty_dict(self):
        ws = _make_ws([])
        with _patch_sheet(ws):
            assert get_seen_title_company_keys() == {}

    def test_worksheet_not_found_returns_empty_dict(self):
        spreadsheet = MagicMock()
        spreadsheet.worksheet.side_effect = gspread.exceptions.WorksheetNotFound
        with patch("sheets._get_sheet", return_value=spreadsheet):
            assert get_seen_title_company_keys() == {}


# ── append_jobs ───────────────────────────────────────────────────────────────

class TestAppendJobsWritesDedupKey:

    def test_dedup_key_written_as_last_column(self):
        ws = MagicMock()
        spreadsheet = MagicMock()
        spreadsheet.worksheet.return_value = ws

        jobs = [
            {
                "company": "Anthropic",
                "source": "greenhouse",
                "title": "Senior SWE",
                "location": "London",
                "department": "Engineering",
                "url": "https://example.com/1",
                "fit_score": 8,
                "key_strengths": "Python",
                "key_gaps": "None",
                "recommendation": "Apply",
                "reasoning": "Good fit",
            }
        ]

        with patch("sheets._get_sheet", return_value=spreadsheet):
            append_jobs(jobs)

        written_rows = ws.append_rows.call_args[0][0]
        assert len(written_rows) == 1
        assert written_rows[0][-1] == "senior swe|anthropic"

    def test_dedup_key_normalised_to_lowercase(self):
        ws = MagicMock()
        spreadsheet = MagicMock()
        spreadsheet.worksheet.return_value = ws

        jobs = [{"company": "OpenAI", "title": "HEAD OF PRODUCT", "source": "ashby",
                 "location": "London", "department": "", "url": "u",
                 "fit_score": 7, "key_strengths": "", "key_gaps": "", "recommendation": "", "reasoning": ""}]

        with patch("sheets._get_sheet", return_value=spreadsheet):
            append_jobs(jobs)

        written_rows = ws.append_rows.call_args[0][0]
        assert written_rows[0][-1] == "head of product|openai"
