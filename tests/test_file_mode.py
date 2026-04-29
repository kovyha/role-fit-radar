import pytest
import requests as req
from unittest.mock import patch, MagicMock

from sources.file_mode import (
    _google_doc_export_url,
    _extract_pdf,
    _extract_docx,
    _extract_xlsx,
    load_from_url,
    load_from_file,
    load_from_directory,
    load_jd,
)


class TestGoogleDocExportUrl:

    def test_valid_google_doc_url(self):
        url = "https://docs.google.com/document/d/abc123XYZ/edit"
        result = _google_doc_export_url(url)
        assert result == "https://docs.google.com/document/d/abc123XYZ/export?format=txt"

    def test_non_google_doc_url(self):
        assert _google_doc_export_url("https://example.com/doc") is None

    def test_google_spreadsheet_url_not_matched(self):
        assert _google_doc_export_url("https://docs.google.com/spreadsheets/d/abc123/edit") is None


class TestLoadFromUrl:

    def test_google_doc_dispatches_to_export_url(self):
        url = "https://docs.google.com/document/d/abc123/edit"
        mock_resp = MagicMock()
        mock_resp.text = "Job description text"
        with patch("requests.get", return_value=mock_resp):
            name, text = load_from_url(url)
        assert name == "google_doc"
        assert text == "Job description text"

    def test_pdf_by_content_type(self):
        mock_resp = MagicMock()
        mock_resp.headers = {"Content-Type": "application/pdf"}
        mock_resp.content = b"%PDF fake"
        mock_resp.url = "https://example.com/job.pdf"
        with patch("requests.get", return_value=mock_resp), \
             patch("sources.file_mode._extract_pdf", return_value="pdf text"):
            name, text = load_from_url("https://example.com/job.pdf")
        assert text == "pdf text"

    def test_docx_by_content_type(self):
        mock_resp = MagicMock()
        mock_resp.headers = {"Content-Type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
        mock_resp.content = b"fake docx bytes"
        mock_resp.url = "https://example.com/job.docx"
        with patch("requests.get", return_value=mock_resp), \
             patch("sources.file_mode._extract_docx", return_value="docx text"):
            name, text = load_from_url("https://example.com/job.docx")
        assert text == "docx text"

    def test_xlsx_by_content_type(self):
        mock_resp = MagicMock()
        mock_resp.headers = {"Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
        mock_resp.content = b"fake xlsx bytes"
        mock_resp.url = "https://example.com/jobs.xlsx"
        with patch("requests.get", return_value=mock_resp), \
             patch("sources.file_mode._extract_xlsx", return_value="xlsx text"):
            name, text = load_from_url("https://example.com/jobs.xlsx")
        assert text == "xlsx text"

    def test_unknown_content_type_falls_back_to_text(self):
        mock_resp = MagicMock()
        mock_resp.headers = {"Content-Type": "text/html"}
        mock_resp.text = "plain text content"
        mock_resp.url = "https://example.com/job"
        with patch("requests.get", return_value=mock_resp):
            name, text = load_from_url("https://example.com/job")
        assert text == "plain text content"

    def test_http_error_raises(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = req.HTTPError("404")
        with patch("requests.get", return_value=mock_resp):
            with pytest.raises(req.HTTPError):
                load_from_url("https://example.com/missing")


class TestLoadFromFile:

    def test_txt_file_returns_name_and_text(self, tmp_path):
        f = tmp_path / "senior_engineer.txt"
        f.write_text("Senior Engineer role at Acme Corp")
        name, text = load_from_file(str(f))
        assert name == "senior_engineer"
        assert text == "Senior Engineer role at Acme Corp"

    def test_file_not_found_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_from_file(str(tmp_path / "missing.txt"))

    def test_unsupported_extension_raises(self, tmp_path):
        f = tmp_path / "job.html"
        f.write_bytes(b"<html/>")
        with pytest.raises(ValueError, match="Unsupported file type"):
            load_from_file(str(f))

    def test_pdf_file_delegates_to_extract(self, tmp_path):
        f = tmp_path / "job.pdf"
        f.write_bytes(b"%PDF-1.4 fake")
        with patch("sources.file_mode._extract_pdf", return_value="extracted pdf text"):
            name, text = load_from_file(str(f))
        assert name == "job"
        assert text == "extracted pdf text"

    def test_docx_file_delegates_to_extract(self, tmp_path):
        f = tmp_path / "role.docx"
        f.write_bytes(b"fake docx bytes")
        with patch("sources.file_mode._extract_docx", return_value="extracted docx text"):
            name, text = load_from_file(str(f))
        assert name == "role"
        assert text == "extracted docx text"

    def test_xlsx_file_delegates_to_extract(self, tmp_path):
        f = tmp_path / "roles.xlsx"
        f.write_bytes(b"fake xlsx bytes")
        with patch("sources.file_mode._extract_xlsx", return_value="extracted xlsx text"):
            name, text = load_from_file(str(f))
        assert name == "roles"
        assert text == "extracted xlsx text"


class TestLoadFromDirectory:

    def test_returns_supported_files(self, tmp_path):
        (tmp_path / "role1.txt").write_text("Role one")
        (tmp_path / "role2.txt").write_text("Role two")
        results = load_from_directory(str(tmp_path))
        assert len(results) == 2
        names = [r[0] for r in results]
        assert "role1" in names
        assert "role2" in names

    def test_skips_unsupported_extensions(self, tmp_path):
        (tmp_path / "role.txt").write_text("Role")
        (tmp_path / "notes.html").write_bytes(b"<html/>")
        results = load_from_directory(str(tmp_path))
        assert len(results) == 1
        assert results[0][0] == "role"

    def test_empty_directory_returns_empty_list(self, tmp_path):
        assert load_from_directory(str(tmp_path)) == []

    def test_not_a_directory_raises(self, tmp_path):
        f = tmp_path / "file.txt"
        f.write_text("text")
        with pytest.raises(NotADirectoryError):
            load_from_directory(str(f))

    def test_erroring_file_is_skipped(self, tmp_path):
        (tmp_path / "good.txt").write_text("good content")
        (tmp_path / "bad.pdf").write_bytes(b"not a real pdf")
        with patch("sources.file_mode._extract_pdf", side_effect=Exception("parse error")):
            results = load_from_directory(str(tmp_path))
        assert len(results) == 1
        assert results[0][0] == "good"


class TestLoadJd:

    def test_http_url_dispatches_to_load_from_url(self):
        with patch("sources.file_mode.load_from_url", return_value=("doc", "text")) as m:
            result = load_jd("http://example.com/job")
        m.assert_called_once_with("http://example.com/job")
        assert result == [("doc", "text")]

    def test_https_url_dispatches_to_load_from_url(self):
        with patch("sources.file_mode.load_from_url", return_value=("doc", "text")) as m:
            result = load_jd("https://example.com/job")
        m.assert_called_once()
        assert result == [("doc", "text")]

    def test_directory_dispatches_to_load_from_directory(self, tmp_path):
        with patch("sources.file_mode.load_from_directory", return_value=[("f", "t")]) as m:
            result = load_jd(str(tmp_path))
        m.assert_called_once_with(str(tmp_path))
        assert result == [("f", "t")]

    def test_file_dispatches_to_load_from_file(self, tmp_path):
        f = tmp_path / "job.txt"
        f.write_text("content")
        with patch("sources.file_mode.load_from_file", return_value=("job", "content")) as m:
            result = load_jd(str(f))
        m.assert_called_once_with(str(f))
        assert result == [("job", "content")]


class TestExtractFunctions:

    def test_extract_pdf_reads_all_pages(self):
        mock_page1 = MagicMock()
        mock_page1.extract_text.return_value = "first page"
        mock_page2 = MagicMock()
        mock_page2.extract_text.return_value = "second page"
        mock_reader = MagicMock()
        mock_reader.pages = [mock_page1, mock_page2]
        with patch("pypdf.PdfReader", return_value=mock_reader):
            result = _extract_pdf(b"fake pdf bytes")
        assert result == "first page\nsecond page"

    def test_extract_pdf_handles_none_page_text(self):
        mock_page = MagicMock()
        mock_page.extract_text.return_value = None
        mock_reader = MagicMock()
        mock_reader.pages = [mock_page]
        with patch("pypdf.PdfReader", return_value=mock_reader):
            result = _extract_pdf(b"fake pdf bytes")
        assert result == ""

    def test_extract_docx_joins_non_empty_paragraphs(self):
        mock_para1 = MagicMock()
        mock_para1.text = "First paragraph"
        mock_para2 = MagicMock()
        mock_para2.text = "   "  # whitespace-only — skipped by the if p.text.strip() guard
        mock_para3 = MagicMock()
        mock_para3.text = "Second paragraph"
        mock_doc = MagicMock()
        mock_doc.paragraphs = [mock_para1, mock_para2, mock_para3]
        with patch("docx.Document", return_value=mock_doc):
            result = _extract_docx(b"fake docx bytes")
        assert result == "First paragraph\nSecond paragraph"

    def test_extract_xlsx_formats_rows_as_pipe_separated(self):
        mock_ws = MagicMock()
        mock_ws.iter_rows.return_value = [
            ("Job Title", "London", None),   # None filtered out
            ("  ", "Acme Corp", "£100k"),    # whitespace-only cell filtered out
        ]
        mock_wb = MagicMock()
        mock_wb.worksheets = [mock_ws]
        with patch("openpyxl.load_workbook", return_value=mock_wb):
            result = _extract_xlsx(b"fake xlsx bytes")
        assert "Job Title | London" in result
        assert "Acme Corp | £100k" in result

    def test_extract_xlsx_skips_all_null_rows(self):
        mock_ws = MagicMock()
        mock_ws.iter_rows.return_value = [
            (None, None),
            ("content",),
        ]
        mock_wb = MagicMock()
        mock_wb.worksheets = [mock_ws]
        with patch("openpyxl.load_workbook", return_value=mock_wb):
            result = _extract_xlsx(b"fake xlsx bytes")
        assert result == "content"
