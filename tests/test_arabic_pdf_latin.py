"""
Arabic PDF: Latin letters and symbols (reported 2026-10-01).

Arabic PDFs draw every paragraph in NotoNaskhArabic, and that font has no Latin
letters and almost no ASCII symbols: below U+0600 it only has space, "!", ",",
".", the digits, ":", NBSP and the guillemets. So any English term inside Arabic
text (DNA, ATP, H2O), "%", "-" (the hyphen _ar_shape keeps between Arabic words),
"(", ")", "?", the "·" of every section header ("1 · ..."), the em dash and the
whole "Made with alimne.app — ..." footer line printed as missing-glyph boxes
(pypdf reads them back as "\\x00").

Each Arabic line is now split into runs by whether the Arabic font has the
glyph; the runs it lacks are drawn in Helvetica through _pdf_latin_markup
(WinAnsi/Symbol only), and the wrap is measured with that same mixed markup.
English PDFs are unchanged.

pypdf's default extraction drops parts of mixed right-to-left lines (boxes
included), so the drawn text is read back in layout mode, which keeps every
glyph in drawing order.
"""
import io
import json

import pytest
from pypdf import PdfReader
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics

import app as appmod

MIXED = "الخلية DNA 95% (x) - تعمل"          # الخلية DNA 95% (x) - تعمل
AR_GUIDE = {
    "title": "بيولوجيا DNA",                                                 # no subtitle: "Exam Study Guide"
    "objectives": ["فهم " + "DNA 95% (x) -"],
    "sections": [{
        "title": "طاقة ATP?",                                               # header "1 · ..."
        "bullets": [
            MIXED,
            "الماء H₂O ضروري — للحياة",                     # H₂O, em dash
            "النمسا-المجر",                                          # padded " - " by _ar_shape
        ],
        "table": {"headers": ["المصطلح", "Term (EN)"],
                  "rows": [["ATP", "طاقة 100%"]]},
    }],
    "keywords": [{"term": "DNA", "definition": "الحمض النووي (DNA)"}],
    "flashcards": [{"q": "ما هو ATP?", "a": "جزيء الطاقة - 95%"}],
    "mcqs": [], "language": "ar",
}
WIDTH = 17.4 * cm - 24


def _pdf_texts(guide):
    pdf = appmod.build_pdf(json.loads(json.dumps(guide)), "ar", "t").read()
    pages = PdfReader(io.BytesIO(pdf)).pages
    layout = "\n".join(p.extract_text(extraction_mode="layout") for p in pages)
    plain = "\n".join(p.extract_text() for p in pages)
    return layout, plain


@pytest.fixture
def style():
    assert appmod._ensure_arabic_font()
    return ParagraphStyle("t", fontName=appmod._ARABIC_FONT, fontSize=9.5,
                          leading=16.5, alignment=TA_RIGHT)


def _frag_lines(para):
    """[(text, fontName, fontSize), ...] for each line a wrapped Paragraph draws."""
    out = []
    for line in para.blPara.lines:
        if isinstance(line, tuple):            # one-font paragraph: plain word lists
            out.append([(" ".join(line[1]), para.style.fontName, para.style.fontSize)])
        else:
            out.append([(f.text, f.fontName, f.fontSize) for f in line.words])
    return out


def _assert_every_glyph_drawable(para):
    cmap = pdfmetrics.getFont(appmod._ARABIC_FONT).face.charToGlyph
    for line in _frag_lines(para):
        for text, font, _size in line:
            for ch in text:
                if font == appmod._ARABIC_FONT:
                    ok = bool(cmap.get(ord(ch)))       # glyph 0 is the missing-glyph box
                elif font == "Helvetica":
                    ok = appmod._enc_ok(ch, "cp1252")
                elif font == "Symbol":
                    ok = appmod._enc_ok(ch, "symbol")
                else:
                    ok = False
                assert ok, (font, ch, text)


# ── the reported bug, end to end ──────────────────────────────────────────────

def test_arabic_pdf_has_no_missing_glyph_boxes():
    layout, plain = _pdf_texts(AR_GUIDE)
    assert "\x00" not in layout, "a character was drawn in a font that lacks it"
    assert "\x00" not in plain
    for probe in ("DNA", "ATP", "H2O", "95%", "(DNA)", "?", "—",
                  "Exam Study Guide", "Term (EN)"):
        assert probe in layout, probe


def test_section_header_dot_and_footer_are_drawn():
    layout, _ = _pdf_texts(AR_GUIDE)
    assert "·" in layout                         # "1 · ..." and the footer separators
    assert "Made with alimne.app — turn any lecture into a study guide" in layout


# ── the flowable ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("width", [WIDTH, WIDTH / 2, WIDTH / 4, 60])
def test_paragraph_draws_each_run_in_a_font_that_has_it(style, width):
    text = (MIXED + " ATP? H₂O α — · [R&D] <b>x</b> ￿\U0001F680 ") * 6
    p = appmod._ArabicParagraph(appmod._ar_shape(text), style)
    p.wrap(width, 10000)
    _assert_every_glyph_drawable(p._real)
    drawn = "".join("".join(t for t, _f, _s in line) for line in _frag_lines(p._real))
    for probe in ("DNA", "ATP", "H2O", "95%", "R&D", "<b>x</b>"):
        assert probe in drawn, probe


@pytest.mark.parametrize("width", [WIDTH, WIDTH / 2, WIDTH / 3, 80])
def test_wrap_measures_the_fallback_font(style, width):
    # In Helvetica M, W, % and the em dash are much wider than the Arabic font's
    # missing glyph (646/1000). A probe measured in the Arabic font packs too much
    # on a line; reportlab then re-wraps the reordered line on its own, adding a
    # line and putting its pieces in the wrong order (the reversed-lines bug).
    text = "مقدمة " + "MMMM WWWW %% — " * 10 + "نهاية"
    p = appmod._ArabicParagraph(appmod._ar_shape(text), style)
    p.wrap(width, 10000)
    lines = p._real.blPara.lines
    assert len(lines) >= 2
    assert all(line.lineBreak for line in lines[:-1]), "reportlab had to re-wrap a line"
    for line in _frag_lines(p._real):
        w = sum(pdfmetrics.stringWidth(t, f, s) for t, f, s in line)
        assert w <= width + 0.01, (w, width, line)


def test_english_pdf_never_uses_the_arabic_fallback(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("English PDFs must not change")

    monkeypatch.setattr(appmod, "_ar_pdf_markup", _boom)
    monkeypatch.setattr(appmod, "_ar_pdf_text", _boom)
    g = {"title": "T", "sections": [{"title": "S", "bullets": ["DNA 95% (x) - word " * 40]}],
         "keywords": [{"term": "k", "definition": "d"}], "flashcards": [{"q": "q", "a": "a"}],
         "objectives": ["o"], "mcqs": [], "language": "en"}
    assert len(appmod.build_pdf(g, "en", "t").read()) > 1000
