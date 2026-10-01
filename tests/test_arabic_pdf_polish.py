"""
Arabic PDF polish (review of the Arabic line-order fix, 2026-10-01).

1. Speed: _ArabicParagraph redid its whole layout (probe wrap, pure-Python bidi on
   every line, a second Paragraph) on EVERY wrap(), and tables / KeepTogether call
   wrap() on each cell 2-10 times: Arabic builds got ~3x slower. The layout is now
   cached per width.
2. Hyphens between Arabic words were padded with U+002D, which the bundled Noto
   Naskh Arabic font has no glyph for (a box). They now use U+2010 HYPHEN.
3. A paragraph that starts with a Latin term ("DNA هو ...") was laid out
   left-to-right inside an Arabic guide, so the term ended up last for a
   right-to-left reader. Arabic guides now lay every paragraph out right-to-left.
4. The footer reordered the whole string as ONE line (title last for an RTL
   reader, lines reversed if it ever wrapped), and its Latin "Made with
   alimne.app" line used the Arabic font, which has no Latin letters.
5. Arabic data tables kept left-to-right column order, so the first column was
   drawn on the far left.

English PDFs are untouched (test_arabic_pdf_lines.py checks that). Offline.
"""
import io
import json

import arabic_reshaper
import pytest
from pypdf import PdfReader
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics

import app as appmod

_MID = "تتكون الخلية من أجزاء كثيرة تعمل معا لتحافظ على الحياة وتنتج الطاقة اللازمة"
LONG = " ".join(["البداية"] + [_MID] * 4 + ["النهاية"])
WIDTH = 17.4 * cm - 24


@pytest.fixture
def style():
    assert appmod._ensure_arabic_font()
    return ParagraphStyle("t", fontName=appmod._ARABIC_FONT, fontSize=9.5,
                          leading=16.5, alignment=TA_RIGHT)


def _ar_guide(**over):
    g = {"title": "اختبار", "sections": [{"title": "قسم", "bullets": ["الخلية وحدة الحياة"]}],
         "keywords": [], "flashcards": [], "mcqs": [], "objectives": [], "language": "ar"}
    g.update(over)
    return json.loads(json.dumps(g))


# ── 1. the layout is cached per width ─────────────────────────────────────────

def test_rewrapping_at_the_same_width_does_not_redo_the_layout(style, monkeypatch):
    p = appmod._ArabicParagraph(appmod._ar_shape(LONG), style)
    calls = []
    real = appmod._ar_display_lines
    monkeypatch.setattr(appmod, "_ar_display_lines", lambda *a, **k: calls.append(1) or real(*a, **k))
    first = p.wrap(WIDTH, 10000)
    per_layout = len(calls)
    assert per_layout == 1                      # one bidi pass per layout (all lines)
    for _ in range(8):                          # tables / KeepTogether re-wrap cells
        assert p.wrap(WIDTH, 10000) == first
    assert len(calls) == per_layout, "the layout was rebuilt for a width it already had"


def test_cached_layout_follows_the_latest_width(style):
    p = appmod._ArabicParagraph(appmod._ar_shape(LONG), style)
    wide_size = p.wrap(WIDTH, 10000)
    wide_lines = appmod._para_line_texts(p._real)
    narrow_size = p.wrap(WIDTH / 3, 10000)
    narrow_lines = appmod._para_line_texts(p._real)
    assert len(narrow_lines) > len(wide_lines) and narrow_size[1] > wide_size[1]
    assert p.wrap(WIDTH, 10000) == wide_size                 # back to the first width
    assert appmod._para_line_texts(p._real) == wide_lines    # draw() uses the right layout


def test_an_arabic_guide_with_a_big_table_lays_out_each_cell_once_per_width(monkeypatch):
    assert appmod._ensure_arabic_font()
    made, layouts = [], [0]
    real_cls, real_lines = appmod._ArabicParagraph, appmod._para_line_texts

    class Spy(real_cls):
        def __init__(self, *a, **k):
            self.widths = set()
            super().__init__(*a, **k)
            made.append(self)

        def wrap(self, w, h):
            self.widths.add(w)
            return super().wrap(w, h)

        def split(self, w, h):
            self.widths.add(w)
            return super().split(w, h)

    def counting_lines(para):              # called once per layout build
        layouts[0] += 1
        return real_lines(para)

    monkeypatch.setattr(appmod, "_ArabicParagraph", Spy)
    monkeypatch.setattr(appmod, "_para_line_texts", counting_lines)
    rows = [[f"خلية {r} {c} " + _MID for c in range(6)] for r in range(6)]
    g = _ar_guide(sections=[{"title": "قسم", "bullets": [LONG] * 3,
                             "table": {"headers": [f"عمود {c}" for c in range(6)], "rows": rows}}])
    appmod.build_pdf(g, "ar", "t")
    distinct = sum(len(p.widths) for p in made)
    assert made and layouts[0] <= distinct, f"{layouts[0]} layouts for {distinct} distinct cell widths"


# ── 2. hyphens between Arabic words are drawable ─────────────────────────────

def test_hyphen_between_arabic_words_uses_a_glyph_the_font_has():
    assert appmod._ensure_arabic_font()
    shaped = appmod._ar_shape("النمسا-المجر")
    assert "-" not in shaped, "U+002D has no glyph in Noto Naskh Arabic (prints a box)"
    assert "\N{HYPHEN}" in shaped
    face = pdfmetrics.getFont(appmod._ARABIC_FONT).face
    missing = sorted({hex(ord(ch)) for ch in shaped if ord(ch) not in face.charToGlyph})
    assert missing == [], missing


def test_hyphens_elsewhere_are_untouched():
    # between digits or Latin letters a hyphen is not padded (bidi treats 2-3 as one number)
    assert "2-3" in appmod._ar_shape("صفحات 2-3")
    assert "X-ray" in appmod._ar_shape("أشعة X-ray")


# ── 3. Arabic guides lay out every paragraph right-to-left ───────────────────

def test_latin_first_paragraph_reads_right_to_left_in_an_arabic_guide(monkeypatch):
    assert appmod._ensure_arabic_font()
    made = []
    real = appmod._ArabicParagraph

    class Spy(real):
        def __init__(self, shaped, style, *a, **k):
            super().__init__(shaped, style, *a, **k)
            made.append(self)

    monkeypatch.setattr(appmod, "_ArabicParagraph", Spy)
    bullet = "DNA هو المادة الوراثية في الخلية"
    appmod.build_pdf(_ar_guide(sections=[{"title": "قسم", "bullets": [bullet]}]), "ar", "t")
    ps = [p for p in made if "DNA" in p._shaped]
    assert ps, "the bullet was not drawn by _ArabicParagraph"
    for p in ps:
        assert p._base_dir == "R"
        p.wrap(WIDTH, 10000)
        line = appmod._para_line_texts(p._real)[0]
        # visual order: read from the right, the Latin term comes FIRST
        assert line.rstrip().endswith("DNA"), line


def test_base_dir_defaults_to_auto_detection(style):
    assert appmod._ArabicParagraph("DNA abc", style)._base_dir == "L"
    assert appmod._ArabicParagraph("DNA abc", style, base_dir="R")._base_dir == "R"


def test_pure_latin_or_number_cells_still_display_unchanged(style):
    for s in ("3.5", "ATP", "ATP synthase"):
        p = appmod._ArabicParagraph(appmod._ar_shape(s), style, base_dir="R")
        p.wrap(WIDTH, 10000)
        assert appmod._para_line_texts(p._real) == [s]


# ── 4. the footer ─────────────────────────────────────────────────────────────

def _runs(pdf_bytes):
    """[(text, BaseFont)] for every text run drawn in the PDF."""
    out = []
    for page in PdfReader(io.BytesIO(pdf_bytes)).pages:
        def visit(text, cm_, tm, font, size):
            if text.strip():
                out.append((text, str((font or {}).get("/BaseFont", ""))))
        page.extract_text(visitor_text=visit)
    return out


def test_arabic_footer_is_laid_out_in_logical_order(monkeypatch):
    assert appmod._ensure_arabic_font()
    made = []
    real = appmod._ArabicParagraph

    class Spy(real):
        def __init__(self, shaped, style, *a, **k):
            super().__init__(shaped, style, *a, **k)
            made.append(self)

    monkeypatch.setattr(appmod, "_ArabicParagraph", Spy)
    title = "الخلية النباتية"
    appmod.build_pdf(_ar_guide(title=title), "ar", "t")
    sep = " \N{HYPHEN} "                        # the Arabic font has no "·"
    want = appmod._ar_shape(f"{title}{sep}دليل الدراسة بالذكاء الاصطناعي{sep}حظ سعيد!")
    footers = [p for p in made if p._shaped == want]
    assert len(footers) == 1, "the Arabic footer line must be one _ArabicParagraph in logical order"
    assert footers[0]._base_dir == "R"
    face = pdfmetrics.getFont(appmod._ARABIC_FONT).face
    assert all(ord(ch) in face.charToGlyph for ch in want), "every footer glyph must exist in the font"


def test_long_arabic_footer_keeps_its_lines_in_order(style):
    title = " ".join(["البداية"] + [_MID] * 2)
    p = appmod._ArabicParagraph(appmod._ar_shape(f"{title}  ·  حظ سعيد!"), style, base_dir="R")
    p.wrap(WIDTH, 10000)
    lines = appmod._para_line_texts(p._real)
    assert len(lines) >= 2
    first = arabic_reshaper.reshape("البداية")[::-1]
    assert first in lines[0]


def test_made_with_line_is_drawn_in_helvetica_in_arabic_pdfs():
    assert appmod._ensure_arabic_font()
    runs = _runs(appmod.build_pdf(_ar_guide(), "ar", "t").read())
    latin = [(t, f) for t, f in runs if "alimne.app" in t or "Made with" in t]
    assert latin, runs[-5:]
    for t, f in latin:
        assert "Helvetica" in f, (t, f)


def test_english_footer_is_unchanged():
    runs = _runs(appmod.build_pdf({"title": "Cells", "sections": [], "keywords": [], "flashcards": [],
                                   "mcqs": [], "language": "en"}, "en", "t").read())
    text = " ".join(t for t, _ in runs)
    assert "Cells" in text and "AI Exam Study Guide" in text and "Good luck!" in text
    assert "alimne.app" in text


# ── 5. Arabic data tables run right-to-left ───────────────────────────────────

def test_arabic_table_columns_are_drawn_right_to_left(monkeypatch):
    assert appmod._ensure_arabic_font()
    tables = []
    real = appmod.Table

    class Spy(real):
        def __init__(self, data, *a, **k):
            tables.append(data)
            super().__init__(data, *a, **k)

    monkeypatch.setattr(appmod, "Table", Spy)
    headers = ["المكون", "الوظيفة", "الموقع"]
    rows = [["النواة", "التحكم", "الوسط"], ["الميتوكوندريا", "الطاقة"]]   # short row is padded
    appmod.build_pdf(_ar_guide(sections=[{"title": "قسم", "bullets": [],
                                          "table": {"headers": headers, "rows": rows}}]), "ar", "t")
    shaped_hdr = [appmod._ar_shape(h) for h in headers]
    data = [t for t in tables if len(t) == 3 and len(t[0]) == 3
            and {getattr(c, "_shaped", None) for c in t[0]} == set(shaped_hdr)]
    assert len(data) == 1, "the data table was not found"
    cells = [[c._shaped for c in row] for row in data[0]]
    # column 0 (the first header) is drawn on the RIGHT: data columns are reversed
    assert cells[0] == shaped_hdr[::-1]
    assert cells[1] == [appmod._ar_shape(x) for x in ["الوسط", "التحكم", "النواة"]]
    assert cells[2] == ["", appmod._ar_shape("الطاقة"), appmod._ar_shape("الميتوكوندريا")]


def test_english_table_columns_keep_their_order(monkeypatch):
    tables = []
    real = appmod.Table

    class Spy(real):
        def __init__(self, data, *a, **k):
            tables.append(data)
            super().__init__(data, *a, **k)

    monkeypatch.setattr(appmod, "Table", Spy)
    g = {"title": "T", "sections": [{"title": "S", "bullets": [],
         "table": {"headers": ["First", "Second", "Third"], "rows": [["a", "b", "c"]]}}],
         "keywords": [], "flashcards": [], "mcqs": [], "language": "en"}
    appmod.build_pdf(g, "en", "t")
    data = [t for t in tables if len(t) == 2 and len(t[0]) == 3]
    assert len(data) == 1
    assert [c.getPlainText() for c in data[0][0]] == ["First", "Second", "Third"]
