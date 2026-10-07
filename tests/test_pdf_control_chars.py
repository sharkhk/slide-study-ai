"""
Nightly debug run: an ASCII control character (NUL, SOH, ESC, DEL...) in guide
text - which slide/PDF text extraction can carry into model output - is
cp1252-encodable, so _pdf_latin_markup passed it to Helvetica, which has no glyph
for it: the English PDF showed a ■ missing-glyph box. Control characters are now
dropped (tab/newline are kept) before reaching the PDF.
"""
import io

import pytest
from pypdf import PdfReader

import app as appmod


@pytest.mark.parametrize("ch", ["\x00", "\x01", "\x08", "\x1b", "\x7f"])
def test_control_char_never_boxes(ch):
    s = f"Cell{ch}membrane"
    g = {"title": s, "objectives": [s],
         "sections": [{"title": s, "bullets": [s]}],
         "keywords": [{"term": s, "definition": s}],
         "flashcards": [{"q": s, "a": s}]}
    data = appmod.build_pdf(g, "en").read()
    text = "".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(data)).pages)
    assert "■" not in text
    assert "Cellmembrane" in text


def test_markup_drops_controls_keeps_whitespace():
    assert appmod._pdf_latin_markup("a\x00b\x1bc\x7fd") == "abcd"
    assert appmod._pdf_latin_markup("a\tb\nc") == "a\tb\nc"
    assert appmod._pdf_latin_markup("R&D <x> π") == 'R&amp;D &lt;x&gt; <font face="Symbol">π</font>'
