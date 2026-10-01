"""
Guard: English PDFs use Helvetica (WinAnsi only). Any character outside it used
to render as a solid black box — e.g. the model's non-breaking hyphen U+2011 in
"client‑side" (reported by HK 2026-10-01). Every character that reaches the PDF
must be WinAnsi (Helvetica) or drawn with the Symbol font.
"""
import io

from pypdf import PdfReader

import app as appmod

_TEXTS = [
    "client\u2011side, air\u2010gapped, AES\u2011256\u2011GCM, CVE\u20112024\u20113094",
    "third\u2011party\u202fservices\u200b and soft\u00adhyphen",
    "\u03b1, \u03b2, \u0394G \u2264 0, x \u2192 \u221e, \u221a2 \u2248 1.41",
    "H\u2082O, CO\u2082, caf\u00e9, \u0101, \u2714 done \U0001F680",
]


def _guide():
    return {
        "title": "Glyphs \u2011 test", "subtitle": "sub\u2011title",
        "objectives": [_TEXTS[0]],
        "sections": [{"title": "R&D \u2011 " + _TEXTS[2], "bullets": _TEXTS,
                      "table": {"headers": ["A\u2011B", "C"], "rows": [[_TEXTS[1], _TEXTS[3]]]}}],
        "keywords": [{"term": "Air\u2011gapped", "definition": _TEXTS[1]}],
        "flashcards": [{"q": _TEXTS[0], "a": _TEXTS[3]}],
        "mcqs": [], "language": "en",
    }


def test_latin_markup_only_emits_drawable_characters():
    for t in _TEXTS:
        m = appmod._pdf_latin_markup(t)
        plain = m.replace('<font face="Symbol">', "").replace("</font>", "")
        for ch in plain:
            assert appmod._enc_ok(ch, "cp1252") or appmod._enc_ok(ch, "symbol"), (t, ch)
    assert appmod._pdf_latin_markup("client\u2011side") == "client-side"
    assert appmod._pdf_latin_markup("H\u2082O") == "H2O"
    assert appmod._pdf_latin_markup("a < b & c") == "a &lt; b &amp; c"
    assert '<font face="Symbol">\u03b1</font>' in appmod._pdf_latin_markup("\u03b1")


def test_english_pdf_has_no_missing_glyph_boxes():
    pdf = appmod.build_pdf(_guide(), "en", "t").read()
    text = "".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages)
    assert "\u25a0" not in text
    for probe in ("client-side", "AES-256-GCM", "CVE-2024-3094", "third-party", "H2O", "Air-gapped",
                  "R&D - "):
        assert probe in text, probe
    for ch in text:
        assert appmod._enc_ok(ch, "cp1252") or appmod._enc_ok(ch, "symbol"), repr(ch)


def test_arabic_pdf_still_builds_with_latin_hyphen():
    g = {"title": "\u0627\u062e\u062a\u0628\u0627\u0631", "sections": [{"title": "\u0642\u0633\u0645",
         "bullets": ["\u0646\u0635 client\u2011side"]}], "keywords": [], "flashcards": [], "mcqs": [],
         "language": "ar"}
    assert len(appmod.build_pdf(g, "ar", "t").read()) > 1000
