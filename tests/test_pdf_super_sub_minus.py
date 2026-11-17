"""
Guard: superscript/subscript minus (U+207B ⁻, U+208B ₋) has no WinAnsi or Symbol
glyph and its decomposition (U+2212) has none either, so the PDF DROPPED it and
the meaning changed: "10⁻⁵" printed as "105", "m⁻²" (per square metre) as "m²",
"SO₄²⁻" lost its charge, "x⁻¹" became "x¹". Superscript/subscript letters and
digits that Helvetica lacks (⁴, ⁿ) were flattened onto the line ("x⁴" → "x4").
English PDFs now draw them raised (<super>); every PDF keeps a minus sign.
Subscripts stay flat (H₂O → H2O, as before).
"""
import io
import re

from pypdf import PdfReader

import app as appmod


def _plain(markup):
    return re.sub(r"</?(?:super|font[^>]*)>", "", markup)


def test_super_and_subscript_minus_survive_in_the_markup():
    cases = {"10⁻⁵": "10-5", "m⁻²": "m-²", "x⁻¹": "x-¹", "SO₄²⁻": "SO4²-",
             "a₋₁": "a-1", "Ca²⁺": "Ca²+", "2⁻ⁿ": "2-n"}
    for src, want in cases.items():
        got = _plain(appmod._pdf_latin_markup(src))
        assert got == want, (src, got)


def test_undrawable_superscripts_stay_raised():
    assert appmod._pdf_latin_markup("10⁻⁵") == "10<super>-</super><super>5</super>"
    assert appmod._pdf_latin_markup("x⁴") == "x<super>4</super>"
    assert appmod._pdf_latin_markup("H₂O") == "H2O"          # subscripts stay flat
    # characters Helvetica already draws are untouched
    assert appmod._pdf_latin_markup("x² + y³ & z") == "x² + y³ &amp; z"


def test_arabic_pdf_fallback_keeps_the_minus():
    # the Arabic PDF draws such characters as plain text (_ar_pdf_text)
    assert appmod._pdf_winansi_alt("⁻") == "-"
    assert appmod._pdf_winansi_alt("₋") == "-"


def test_english_pdf_prints_the_negative_exponent():
    g = {"title": "Chem", "sections": [{"title": "Rates", "bullets": [
        "k = 3.2 × 10⁻⁵ s⁻¹ in mol m⁻³"]}],
         "keywords": [], "flashcards": [], "mcqs": [], "language": "en"}
    pdf = appmod.build_pdf(g, "en", "t").read()
    text = "".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages)
    assert "■" not in text
    flat = re.sub(r"\s+", "", text)
    assert "10-5" in flat and "s-¹" in flat and "m-³" in flat, text
