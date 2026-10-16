"""
Nightly debug run: the model sometimes answers a JSON null for a field (a title,
subtitle, section title, definition, flash-card side, table cell or bullet). The
PDF and Markdown exports printed those as the word "None" (e.g. "# None", a
CONTENTS line "1. None", a flash card "Q. None"). A null is now treated as
missing: the usual default or an empty cell, never the text "None".
"""
from pypdf import PdfReader

import app as appmod


def _guide():
    return {
        "title": None, "subtitle": None, "objectives": ["Know the cell", None],
        "sections": [{"title": None, "bullets": ["Cells divide", None],
                      "table": {"headers": ["Organelle", None], "rows": [["Nucleus", None]]}}],
        "keywords": [{"term": "Mitosis", "definition": None}],
        "flashcards": [{"q": None, "a": "Prophase"}],
        "mcqs": [{"q": "Which?", "options": ["A) x", None], "answer": "A", "explanation": None}],
        "language": "en",
    }


def test_markdown_has_no_none():
    md = appmod.build_markdown(_guide())
    assert "None" not in md, md
    assert md.startswith("# Study Guide")
    assert "Cells divide" in md and "| Nucleus |  |" in md


def test_pdf_has_no_none():
    text = "".join(p.extract_text() for p in PdfReader(appmod.build_pdf(_guide(), "en")).pages)
    assert "None" not in text and "NONE" not in text, text
    assert "Cells divide" in text and "Prophase" in text and "Nucleus" in text


def test_real_text_none_is_kept():
    g = _guide()
    g["sections"][0]["bullets"] = ["None of the above is correct"]
    assert "None of the above is correct" in appmod.build_markdown(g)
