"""Extracts plain text from PDF and Word (.docx) files."""

import re
from pathlib import Path

import pdfplumber
from docx import Document


class UnsupportedFileTypeError(Exception):
    pass


def parse_document(file_path: str | Path) -> str:
    """Return the full text of a PDF or Word document.

    Raises UnsupportedFileTypeError for any other extension.
    """
    path = Path(file_path)
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        return _parse_pdf(path)
    elif suffix in (".docx", ".doc"):
        return _parse_docx(path)
    else:
        raise UnsupportedFileTypeError(
            f"Unsupported file type '{suffix}'. Only .pdf and .docx are supported."
        )


def _parse_pdf(path: Path) -> str:
    pages: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                pages.append(text)
    return _clean("\n\n".join(pages))


def _parse_docx(path: Path) -> str:
    doc = Document(path)
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    # Also extract text from tables
    for table in doc.tables:
        for row in table.rows:
            row_text = "  |  ".join(cell.text.strip() for cell in row.cells if cell.text.strip())
            if row_text:
                paragraphs.append(row_text)
    return _clean("\n".join(paragraphs))


def _clean(text: str) -> str:
    # Collapse runs of 3+ newlines into 2
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
