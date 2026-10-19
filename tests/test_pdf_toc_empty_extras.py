"""
Nightly debug run: the PDF table of contents always listed KEY TERMS and FLASH
CARDS after the sections, even for a guide without key terms or flash cards, so
the CONTENTS pointed at pages that were never printed. Those two lines now
appear only when their part is in the PDF.
"""
import re

from pypdf import PdfReader

import app as appmod


def _guide(keywords=(), flashcards=(), language="en"):
    return {
        "title": "Cells", "language": language,
        "sections": [{"title": "Cell basics", "bullets": ["Cells divide"]}],
        "keywords": list(keywords), "flashcards": list(flashcards),
    }


def _text(guide):
    pdf = appmod.build_pdf(guide, guide["language"])
    return "".join(p.extract_text() for p in PdfReader(pdf).pages)


def _toc_numbers(text):
    # an Arabic CONTENTS line extracts as " . <title>N" (right-to-left)
    return re.findall(r"(?m)^ \. .*?([0-9])$", text)


def test_no_key_terms_or_flash_cards_in_toc_when_empty():
    text = _text(_guide())
    assert "KEY TERMS" not in text and "FLASH CARDS" not in text, text
    assert "Cell basics" in text


def test_only_present_parts_are_listed_and_numbered():
    text = _text(_guide(keywords=[{"term": "Mitosis", "definition": "Cell division"}]))
    assert "2.  KEY TERMS" in text or "2. KEY TERMS" in text, text
    assert "FLASH CARDS" not in text and "3." not in text

    text = _text(_guide(flashcards=[{"q": "What divides?", "a": "Cells"}]))
    assert "FLASH CARDS" in text and "KEY TERMS" not in text
    assert re.search(r"2\.\s+FLASH CARDS", text), text


def test_full_guide_toc_unchanged():
    text = _text(_guide(keywords=[{"term": "Mitosis", "definition": "Cell division"}],
                        flashcards=[{"q": "What divides?", "a": "Cells"}]))
    assert re.search(r"2\.\s+KEY TERMS", text) and re.search(r"3\.\s+FLASH CARDS", text), text


def test_arabic_toc_lists_only_the_sections():
    g = _guide(language="ar")
    g["sections"][0]["title"] = "أساسيات الخلية"
    assert _toc_numbers(_text(g)) == ["1"]
    g["flashcards"] = [{"q": "ما الذي ينقسم؟", "a": "الخلايا"}]
    assert _toc_numbers(_text(g)) == ["1", "2"]
    g["keywords"] = [{"term": "الانقسام", "definition": "انقسام الخلية"}]
    assert _toc_numbers(_text(g)) == ["1", "2", "3"]
