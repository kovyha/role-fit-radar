import logging
import re
import io
import requests
from pathlib import Path

logger = logging.getLogger(__name__.rsplit(".", 1)[-1])

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".doc", ".xlsx", ".xls", ".txt"}


def _extract_pdf(data: bytes) -> str:
    import pypdf
    reader = pypdf.PdfReader(io.BytesIO(data))
    return "\n".join(page.extract_text() or "" for page in reader.pages).strip()


def _extract_docx(data: bytes) -> str:
    import docx
    doc = docx.Document(io.BytesIO(data))
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


def _extract_xlsx(data: bytes) -> str:
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    parts = []
    for sheet in wb.worksheets:
        for row in sheet.iter_rows(values_only=True):
            cells = [str(c) for c in row if c is not None and str(c).strip()]
            if cells:
                parts.append(" | ".join(cells))
    return "\n".join(parts)


def _extract(data: bytes, ext: str) -> str:
    ext = ext.lower()
    if ext == ".pdf":
        return _extract_pdf(data)
    if ext in (".docx", ".doc"):
        return _extract_docx(data)
    if ext in (".xlsx", ".xls"):
        return _extract_xlsx(data)
    if ext == ".txt":
        return data.decode("utf-8", errors="replace")
    raise ValueError(f"Unsupported extension: {ext}")


def _google_doc_export_url(url: str) -> str | None:
    m = re.search(r"docs\.google\.com/document/d/([a-zA-Z0-9_-]+)", url)
    if m:
        return f"https://docs.google.com/document/d/{m.group(1)}/export?format=txt"
    return None


def load_from_url(url: str) -> tuple[str, str]:
    """Download and extract text from a URL. Returns (name, text)."""
    export_url = _google_doc_export_url(url)
    if export_url:
        r = requests.get(export_url, timeout=30)
        r.raise_for_status()
        return "google_doc", r.text

    r = requests.get(url, timeout=30, allow_redirects=True)
    r.raise_for_status()

    content_type = r.headers.get("Content-Type", "")
    url_path = url.split("?")[0]

    if "pdf" in content_type:
        ext = ".pdf"
    elif "wordprocessingml" in content_type or "msword" in content_type:
        ext = ".docx"
    elif "spreadsheetml" in content_type or "excel" in content_type:
        ext = ".xlsx"
    else:
        ext = Path(url_path).suffix.lower() or ".txt"

    name = Path(url_path).stem or "downloaded"
    if ext == ".txt" or ext not in SUPPORTED_EXTENSIONS:
        return name, r.text
    return name, _extract(r.content, ext)


def load_from_file(path: str) -> tuple[str, str]:
    """Load and extract text from a local file. Returns (name, text)."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"File not found: {path}")
    ext = p.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"Unsupported file type '{ext}'. Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )
    return p.stem, _extract(p.read_bytes(), ext)


def load_from_directory(dir_path: str) -> list[tuple[str, str]]:
    """Scan a directory for JD files. Returns list of (name, text)."""
    d = Path(dir_path)
    if not d.is_dir():
        raise NotADirectoryError(f"Not a directory: {dir_path}")
    results = []
    for p in sorted(d.iterdir()):
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS:
            try:
                name, text = load_from_file(str(p))
                results.append((name, text))
                logger.info(f"Loaded: {p.name}")
            except Exception as e:
                logger.warning(f"Skipping {p.name}: {e}")
    return results


def load_jd(input_str: str) -> list[tuple[str, str]]:
    """
    Dispatch based on input type (URL, directory, or file).
    Returns list of (name, text) pairs.
    """
    if input_str.startswith(("http://", "https://")):
        name, text = load_from_url(input_str)
        return [(name, text)]
    p = Path(input_str)
    if p.is_dir():
        return load_from_directory(input_str)
    name, text = load_from_file(input_str)
    return [(name, text)]
