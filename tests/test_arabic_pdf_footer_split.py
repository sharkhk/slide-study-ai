"""
Nightly debug run: an Arabic guide whose last line (the footer) fell at the very
bottom of a page made build_pdf crash with AttributeError: 'Paragraph' object has
no attribute 'blPara' - the visitor got "Processing failed" after all the AI work.
When less than one line fits, reportlab's Paragraph.split() drops the cached real
paragraph's layout (blPara) and returns []; the paragraph then moves to the next
page, where _ArabicParagraph.wrap() reused the cached size without wrapping again
and draw() had nothing to draw. wrap() now re-wraps a layout that lost blPara.
"""
import io
import random

from reportlab.pdfgen import canvas

import app as appmod
from tests.test_arabic_pdf_lines import BULLET_WIDTH, LEADING, SHORT, style  # noqa: F401


def test_paragraph_draws_after_a_split_that_did_not_fit(style):
    p = appmod._ArabicParagraph(appmod._ar_shape(SHORT), style)
    p.wrap(BULLET_WIDTH, 10000)
    assert p.split(BULLET_WIDTH, LEADING / 2) == []   # not even one line fits here
    p.wrap(BULLET_WIDTH, 10000)                       # the next page
    p.canv = canvas.Canvas(io.BytesIO())
    p.draw()                                          # raised AttributeError
    assert appmod._para_line_texts(p._real)


_W = ("الخلية وحدة الحياة الأساسية وتنتج الميتوكوندريا الطاقة اللازمة للعمليات "
      "الحيوية في جسم الإنسان والنبات").split()


def _guide(seed):
    rng = random.Random(seed)
    s = lambda a, b: " ".join(rng.choice(_W) for _ in range(rng.randint(a, b)))
    return {"title": s(2, 8), "subtitle": s(2, 6), "language": "ar",
            "objectives": [s(5, 15) for _ in range(rng.randint(2, 5))],
            "sections": [{"title": s(1, 4), "bullets": [s(8, 40) for _ in range(rng.randint(3, 7))]}
                         for _ in range(rng.randint(2, 6))],
            "keywords": [{"term": s(1, 2), "definition": s(4, 12)} for _ in range(rng.randint(4, 10))],
            "flashcards": [{"q": s(3, 8) + "؟", "a": s(3, 15)} for _ in range(rng.randint(5, 12))],
            "mcqs": []}


def test_arabic_guide_with_the_footer_at_a_page_bottom_builds(style):
    pdf = appmod.build_pdf(_guide(97), "ar", "t").read()   # seed 97 put the footer there
    assert pdf.startswith(b"%PDF")
