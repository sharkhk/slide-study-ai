"""The last line of an Arabic guide PDF (the brand line) is Arabic; English guides keep the English line."""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pypdf import PdfReader

import app as appmod


def _pdf_text(language):
    guide = {"title": "Cell basics", "language": language,
             "sections": [{"title": "Cell basics", "bullets": ["Cells are the unit of life"]}]}
    pdf = appmod.build_pdf(guide, language, "t")
    data = pdf.read() if hasattr(pdf, "read") else pdf
    return "".join(p.extract_text() for p in PdfReader(io.BytesIO(data)).pages)


def test_arabic_pdf_brand_line_is_not_english():
    text = _pdf_text("ar")
    assert "turn any lecture into a study guide" not in text
    assert "alimne.app" in text


def test_english_pdf_brand_line_unchanged():
    assert "turn any lecture into a study guide" in _pdf_text("en")
