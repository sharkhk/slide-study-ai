"""
Arabic PDF line order (reported 2026-10-01).

reportlab here has no RTL support (rtlSupport off, no rlbidi/uharfbuzz), so
build_pdf reorders Arabic itself with python-bidi. It used to run get_display()
over the WHOLE paragraph BEFORE reportlab wrapped it: bidi reverses the string,
reportlab then broke that reversed string into lines, and every Arabic paragraph
longer than one line came out with its lines in REVERSE order (the first
sentence printed on the last line).

Arabic plain-text paragraphs are now wrapped in logical order first and each line
is reordered on its own (_ArabicParagraph). English PDFs are untouched.
"""
import io

import arabic_reshaper
import pytest
from pypdf import PdfReader
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm

import app as appmod

FIRST, LAST = "البداية", "النهاية"   # البداية / النهاية
_MID = ("تتكون الخلية من "
        "أجزاء كثيرة تعمل "
        "معا لتحافظ على "
        "الحياة وتنتج "
        "الطاقة اللازمة")
LONG = " ".join([FIRST] + [_MID] * 4 + [LAST])
SHORT = "مرحبا بالعالم"            # مرحبا بالعالم
BULLET_WIDTH = 17.4 * cm - 24     # the section panel (W) minus its 12pt side padding
LEADING = 16.5


def _guide(bullets, title="اختبار"):
    return {"title": title, "sections": [{"title": "قسم", "bullets": bullets}],
            "keywords": [], "flashcards": [], "mcqs": [], "language": "ar"}


def _forms(word):
    shaped = arabic_reshaper.reshape(word)
    return shaped, shaped[::-1]        # logical order and visual (drawn) order


def _line_of(lines, word):
    hits = [i for i, line in enumerate(lines) if any(f in line for f in _forms(word))]
    assert len(hits) == 1, (word, hits, lines)
    return hits[0]


def _pdf_lines(guide):
    pdf = appmod.build_pdf(guide, "ar", "t").read()
    text = "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages)
    return [line for line in text.split("\n") if line.strip()]


@pytest.fixture
def style():
    assert appmod._ensure_arabic_font()
    return ParagraphStyle("t", fontName=appmod._ARABIC_FONT, fontSize=9.5,
                          leading=LEADING, alignment=TA_RIGHT)


def _drawn_lines(p):
    """The visual text of each line the paragraph will actually draw."""
    return appmod._para_line_texts(p._real)


# ── the reported bug, end to end ──────────────────────────────────────────────

def test_long_arabic_bullet_starts_on_its_first_line():
    assert appmod._ensure_arabic_font()
    lines = _pdf_lines(_guide([LONG]))
    first, last = _line_of(lines, FIRST), _line_of(lines, LAST)
    assert first < last, "the first sentence was printed on the last line"
    assert last - first >= 2, "the test paragraph must wrap to at least 3 lines"


def test_one_line_arabic_text_still_renders():
    assert appmod._ensure_arabic_font()
    lines = _pdf_lines(_guide([SHORT], title=SHORT))
    joined = "\n".join(lines)
    for word in SHORT.split():
        assert any(f in joined for f in _forms(word)), word


# ── the flowable ──────────────────────────────────────────────────────────────

def test_paragraph_wraps_in_logical_order_then_reorders_each_line(style):
    p = appmod._ArabicParagraph(appmod._ar_shape(LONG), style)
    w, h = p.wrap(BULLET_WIDTH, 10000)
    lines = _drawn_lines(p)
    assert len(lines) >= 3
    assert _forms(FIRST)[1] in lines[0]
    assert _forms(LAST)[1] in lines[-1]
    assert h == pytest.approx(len(lines) * LEADING)


def test_rewrap_at_another_width_recomputes_the_lines(style):
    p = appmod._ArabicParagraph(appmod._ar_shape(LONG), style)
    p.wrap(BULLET_WIDTH, 10000)
    wide = len(_drawn_lines(p))
    p.wrap(BULLET_WIDTH / 3, 10000)    # tables wrap cells again with other widths
    narrow = _drawn_lines(p)
    assert len(narrow) > wide
    assert _forms(FIRST)[1] in narrow[0]
    assert _forms(LAST)[1] in narrow[-1]


def test_split_across_pages_keeps_the_order(style):
    p = appmod._ArabicParagraph(appmod._ar_shape(LONG), style)
    p.wrap(BULLET_WIDTH, 10000)
    parts = p.split(BULLET_WIDTH, LEADING * 2 + 1)
    assert len(parts) == 2
    for part in parts:
        part.wrap(BULLET_WIDTH, 10000)
    top, rest = appmod._para_line_texts(parts[0]), appmod._para_line_texts(parts[1])
    assert len(top) == 2
    assert _forms(FIRST)[1] in top[0]
    assert _forms(LAST)[1] in rest[-1]


def test_one_line_paragraph_matches_the_old_whole_string_output(style):
    p = appmod._ArabicParagraph(appmod._ar_shape(SHORT), style)
    p.wrap(BULLET_WIDTH, 10000)
    assert _drawn_lines(p) == [appmod._ar(SHORT)]


def test_markup_in_model_text_stays_literal(style):
    hostile = SHORT + ' R&D <img src="http://169.254.169.254/x"/> <b>x</b>'
    p = appmod._ArabicParagraph(appmod._ar_shape(hostile), style)
    p.wrap(BULLET_WIDTH, 10000)
    drawn = "".join(_drawn_lines(p))
    assert "R&D" in drawn and "<img" in drawn and "<b>" in drawn


def test_hyphen_between_arabic_words_stays_separate():
    # _ar()'s fix is kept: a hyphen between two Arabic letters is padded so the
    # reshaper does not merge the two words (drawn as U+2010, which the Arabic
    # font has - see test_arabic_pdf_polish.py).
    ar_word_a, ar_word_b = "النمسا", "المجر"
    assert appmod._ar_shape(f"{ar_word_a}-{ar_word_b}") == arabic_reshaper.reshape(f"{ar_word_a} \N{HYPHEN} {ar_word_b}")
    assert appmod._ar(f"{ar_word_a}-{ar_word_b}") == appmod._ar_display(appmod._ar_shape(f"{ar_word_a}-{ar_word_b}"))


def test_english_pdf_never_uses_the_arabic_paragraph(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("English PDFs must not change")

    monkeypatch.setattr(appmod, "_ArabicParagraph", _boom, raising=False)
    g = {"title": "T", "sections": [{"title": "S", "bullets": ["word " * 120],
         "table": {"headers": ["A", "B"], "rows": [["a", "b"]]}}],
         "keywords": [{"term": "k", "definition": "d"}], "flashcards": [{"q": "q", "a": "a"}],
         "objectives": ["o"], "mcqs": [], "language": "en"}
    assert len(appmod.build_pdf(g, "en", "t").read()) > 1000
