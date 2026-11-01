"""
Nightly debug run: one very long field (a bullet, a key-term definition, a
flash card, an objective of ~800+ words) made a table row taller than a page,
and build_pdf raised reportlab's LayoutError at the very end of generation,
after every AI pass had run: the student got "Processing failed" and the guide
was lost (and /api/rehydrate could not rebuild it). The row now splits across
pages instead, and a normal guide's PDF is built exactly as before.
"""
import io

import pytest
from pypdf import PdfReader

import app as appmod

LONG_EN = "photosynthesis " * 1500
LONG_AR = "كلمة " * 1500


def _guide(word, **over):
    g = {
        "title": "Plants", "subtitle": "Bio",
        "objectives": ["Understand light"],
        "sections": [{"title": "Light", "slide_nums": [1], "bullets": ["Leaves absorb light"]}],
        "keywords": [{"term": "Chlorophyll", "definition": "A pigment"}],
        "flashcards": [{"q": "What absorbs light?", "a": "Chlorophyll"}],
        "mcqs": [],
    }
    g.update(over)
    return g


def _cases(long):
    return {
        "bullet":     {"sections": [{"title": "S", "slide_nums": [1], "bullets": [long]}]},
        "definition": {"keywords": [{"term": "K", "definition": long}]},
        "card":       {"flashcards": [{"q": long, "a": long}]},
        "objective":  {"objectives": [long]},
    }


@pytest.mark.parametrize("lang,long", [("en", LONG_EN), ("ar", LONG_AR)])
@pytest.mark.parametrize("field", ["bullet", "definition", "card", "objective"])
def test_a_very_long_field_still_builds_a_pdf(lang, long, field):
    pdf = appmod.build_pdf(_guide(long, **_cases(long)[field]), lang).read()
    reader = PdfReader(io.BytesIO(pdf))
    assert len(reader.pages) >= 2          # the long field spans pages, nothing dropped
    if lang == "en":
        text = "".join(p.extract_text() for p in reader.pages)
        assert text.count("photosynthesis") >= 1400


def test_a_normal_guide_is_built_once_without_split_rows(monkeypatch):
    calls = []
    real = appmod.BaseDocTemplate.multiBuild
    monkeypatch.setattr(appmod.BaseDocTemplate, "multiBuild",
                        lambda self, *a, **k: (calls.append(1), real(self, *a, **k))[1])
    pdf = appmod.build_pdf(_guide("x"), "en").read()
    assert pdf.startswith(b"%PDF")
    assert len(calls) == 1
