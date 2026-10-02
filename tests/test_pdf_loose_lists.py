"""
Nightly debug run: build_pdf / build_markdown crashed on two more loose LLM
shapes, at the very end of generation after every LLM pass had run, so the
student got "Processing failed" (credit refunded, guide lost) and
/api/rehydrate answered 500 rebuild_failed:
  - "objectives": null (TypeError: 'NoneType' object is not iterable)
  - a table row that is a bare value, e.g. "rows": [["1", "2"], 4]
(build_markdown crashed on the bare row too.)
And "objectives": "one string" printed one character per line.
"""
import io

from pypdf import PdfReader

import app as appmod


def _guide(**over):
    g = {
        "title": "Inflation", "subtitle": "Macro",
        "objectives": ["Understand CPI"],
        "sections": [{"title": "Measuring prices", "slide_nums": [1],
                      "bullets": ["CPI tracks a basket of goods"]}],
        "keywords": [{"term": "CPI", "definition": "Consumer price index"}],
        "flashcards": [{"q": "What is CPI?", "a": "A price index"}],
        "mcqs": [],
    }
    g.update(over)
    return g


def _pdf_text(guide, lang="en"):
    pdf = appmod.build_pdf(guide, lang)
    return "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(pdf.getvalue())).pages)


def test_null_objectives_build_pdf_and_markdown():
    text = _pdf_text(_guide(objectives=None))
    assert "Measuring prices" in text
    md = appmod.build_markdown(_guide(objectives=None))
    assert "Measuring prices" in md


def test_string_objectives_is_one_objective_not_one_per_character():
    text = _pdf_text(_guide(objectives="Understand inflation"))
    assert "Understand inflation" in text
    md = appmod.build_markdown(_guide(objectives="Understand inflation"))
    assert "- Understand inflation" in md
    assert "\n- U\n" not in md


def test_scalar_table_row_does_not_crash_pdf():
    sec = {"title": "Rates", "slide_nums": [1], "bullets": ["b"],
           "table": {"headers": ["Year", "Rate"], "rows": [["2020", "1.2%"], 4]}}
    text = _pdf_text(_guide(sections=[sec]))
    assert "2020" in text and "1.2%" in text
    md = appmod.build_markdown(_guide(sections=[sec]))
    assert "| 2020 | 1.2% |" in md and "| 4 |" in md


def test_null_objectives_arabic_pdf():
    _pdf_text(_guide(objectives=None, title="التضخم"), "ar")
