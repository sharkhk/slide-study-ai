"""
Arabic PDF: brackets around Latin text (reported 2026-10-01).

build_pdf reorders Arabic itself with python-bidi's pure-Python get_display(),
which predates UAX#9 bracket pairing (BD16 / rule N0). Each bracket was resolved
on its own from its neighbours, so in

    يستخدم الجسم جزيء ATP (adenosine triphosphate) لتخزين

the "(" (between two Latin words) went left-to-right while the ")" (between
Latin and Arabic) went right-to-left, was mirrored and jumped to the other end
of the Latin run: the PDF showed "(ATP (adenosine triphosphate". Same for
"DNA 95% (x) - ..." -> "(DNA 95% (x". Symmetric cases such as "(DNA)" at the
end of Arabic text were already right and must stay right.

Brackets are now paired (BD16) and resolved together (N0) before the neutral
rules. Wrapped paragraphs resolve the whole paragraph first and reorder each
line afterwards (UAX#9 L1-L4 are per line, the rest per paragraph), so a line
break inside "( ... )" no longer flips the closing bracket either.

pypdf's default extraction drops parts of mixed right-to-left lines, so the
drawn text is read back in layout mode, which keeps every glyph in drawing order.
"""
import io
import json
import random
import re

import pytest
from bidi.algorithm import get_display as legacy_get_display
from bidi.mirror import MIRRORED
from pypdf import PdfReader
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm

import app as appmod

ATP = "يستخدم الجسم جزيء ATP (adenosine triphosphate) لتخزين الطاقة"
MIXED = "الخلية DNA 95% (x) - تعمل"
SYMMETRIC = "الحمض النووي (DNA)"
WIDTH = 17.4 * cm - 24


def rev(arabic):
    """Arabic text as drawn: reshaped, then right-to-left."""
    return appmod._ar_shape(arabic)[::-1]


def _display(text, base_dir=None):
    return appmod._ar_display(appmod._ar_shape(text), base_dir)


@pytest.fixture
def style():
    assert appmod._ensure_arabic_font()
    return ParagraphStyle("t", fontName=appmod._ARABIC_FONT, fontSize=9.5,
                          leading=16.5, alignment=TA_RIGHT)


# ── the reported bug, end to end ──────────────────────────────────────────────

def test_pdf_keeps_parentheses_around_latin_text():
    assert appmod._ensure_arabic_font()
    guide = {
        "title": "بيولوجيا",
        "sections": [{"title": "الطاقة", "bullets": [ATP, MIXED, SYMMETRIC]}],
        "keywords": [{"term": "ATP", "definition": ATP}],
        "flashcards": [], "mcqs": [], "language": "ar",
    }
    pdf = appmod.build_pdf(json.loads(json.dumps(guide)), "ar", "t").read()
    layout = "\n".join(p.extract_text(extraction_mode="layout")
                       for p in PdfReader(io.BytesIO(pdf)).pages)
    assert "ATP (adenosine triphosphate)" in layout
    assert "(ATP" not in layout
    assert "DNA 95% (x)" in layout
    assert "(DNA 95%" not in layout
    assert "(DNA)" in layout                       # symmetric case: unchanged


# ── one line ──────────────────────────────────────────────────────────────────

CASES = [
    # the two reports
    (ATP, "R", rev("لتخزين الطاقة") + " ATP (adenosine triphosphate) " + rev("يستخدم الجسم جزيء")),
    (MIXED, "R", rev("تعمل") + " - DNA 95% (x) " + rev("الخلية")),
    # already right before, must stay right
    (SYMMETRIC, "R", "(DNA) " + rev("الحمض النووي")),
    ("(DNA) هو الحمض", "R", rev("هو الحمض") + " (DNA)"),
    ("الماء (ماء) هنا", "R", rev("هنا") + " (" + rev("ماء") + ") " + rev("الماء")),
    ("العدد (5) هنا", "R", rev("هنا") + " (5) " + rev("العدد")),
    ("مصفوفة [x, y] و {a} نهاية", "R",
     rev("نهاية") + " {a} " + rev("و") + " [x, y] " + rev("مصفوفة")),
    ("Term (EN)", "L", "Term (EN)"),
    # nested pairs and pairs holding both directions
    ("مثال ATP (a (b) c) نهاية", "R", rev("نهاية") + " ATP (a (b) c) " + rev("مثال")),
    ("كلمة ABC (DEF ع) كلمة", "R", rev("كلمة") + " (" + rev("ع") + " DEF) ABC " + rev("كلمة")),
    # left-to-right paragraph with an Arabic term in brackets after Arabic
    ("ABC كلمة (عربي) DEF", "L", "ABC (" + rev("عربي") + ") " + rev("كلمة") + " DEF"),
    # an unpaired bracket is resolved on its own, as before
    ("كلمة ABC) كلمة", "R", rev("كلمة") + " (ABC " + rev("كلمة")),
]


@pytest.mark.parametrize("text,base_dir,expected", CASES)
def test_brackets_resolve_as_a_pair(text, base_dir, expected):
    assert _display(text, base_dir) == expected


def _canon(s):
    """Map both glyphs of a mirrored pair to one, so only widths are compared."""
    return sorted(min(ch, MIRRORED.get(ch, ch)) for ch in s)


@pytest.mark.parametrize("text,base_dir,expected", CASES)
def test_reordering_never_changes_what_is_measured(text, base_dir, expected):
    # The probe wraps the logical text; the drawn line must have the same width.
    shaped = appmod._ar_shape(text)
    assert _canon(appmod._ar_display(shaped, base_dir)) == _canon(shaped)


def test_text_without_brackets_is_reordered_exactly_as_before():
    rnd = random.Random(20261001)
    alphabet = ["ب", "ت", "ع", "ل", "ة", "م",
                "A", "b", "Z", "1", "5", "٣", " ", " ", "%", "-", "+", ",", ".", ":",
                "/", "?", "!", "«", "»", "<", ">", "·", "—", "#", "$"]
    for _ in range(600):
        s = appmod._ar_shape("".join(rnd.choice(alphabet) for _ in range(rnd.randint(1, 30))))
        for base_dir in (None, "R", "L"):
            assert appmod._ar_display(s, base_dir) == legacy_get_display(s, base_dir=base_dir), \
                (ascii(s), base_dir)


# ── wrapped paragraphs ────────────────────────────────────────────────────────

def _latin(line):
    return re.sub(r" +", " ", re.sub(r"[^\x20-\x7e]", " ", line)).strip()


def test_line_break_inside_brackets_keeps_each_bracket_on_its_side(style):
    text = "تعتمد الخلية على جزيء ATP (adenosine triphosphate) لتخزين الطاقة ونقلها"
    split_seen = False
    for width in range(60, 420, 6):
        p = appmod._ArabicParagraph(appmod._ar_shape(text), style)
        p.wrap(width, 10000)
        lines = appmod._para_line_texts(p._real)
        if not any("(" in ln and ")" in ln for ln in lines):
            split_seen = True
        for ln in lines:
            latin = _latin(ln)
            if latin:
                assert latin in "ATP (adenosine triphosphate)", (width, lines)
        # still one drawn line per probe line: nothing re-wrapped
        assert all(line.lineBreak for line in p._real.blPara.lines[:-1]), width
    assert split_seen, "no width put a line break inside the brackets"


def test_one_line_paragraph_matches_ar_display(style):
    p = appmod._ArabicParagraph(appmod._ar_shape(ATP), style)
    p.wrap(WIDTH, 10000)
    assert appmod._para_line_texts(p._real) == [_display(ATP, "R")]
