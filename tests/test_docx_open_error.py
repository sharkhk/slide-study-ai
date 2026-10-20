"""
Nightly debug run: Word uploads were reported as PowerPoint files. extract_slides
swallowed every error from _extract_docx and retried the file as a .pptx, so a
Word document with no readable paragraphs ("No readable text found in the Word
document.") or a damaged .docx (a truncated download) ended with "Couldn't open
this PowerPoint file ... Open it in PowerPoint". Word files now get Word texts,
in the request's language.
"""
import io

import docx
import pytest

import app as appmod


def _docx(*paras):
    d = docx.Document()
    for p in paras:
        d.add_paragraph(p)
    b = io.BytesIO()
    d.save(b)
    return b.getvalue()


def _err(raw, name):
    with pytest.raises(ValueError) as ei:
        appmod.extract_slides(io.BytesIO(raw), name)
    return ei.value


def test_word_file_without_text_says_word_not_powerpoint():
    e = _err(_docx(), "notes.docx")
    assert str(e) == "No readable text found in the Word document."
    assert appmod._GEN_ERR_AR.get(str(e))


def test_damaged_docx_says_word_not_powerpoint():
    e = _err(_docx("hello")[:200], "notes.docx")
    assert "PowerPoint" not in str(e)
    assert "Word" in str(e)
    assert isinstance(e, appmod._FileOpenError)
    assert "PowerPoint" not in e.ar and "Word" in e.ar


def test_damaged_pptx_still_says_powerpoint():
    e = _err(_docx("hello")[:200], "slides.pptx")
    assert str(e) == appmod._PPTX_OPEN_EN


def test_readable_docx_still_extracted():
    slides = appmod.extract_slides(io.BytesIO(_docx("Photosynthesis makes sugar.")), "n.docx")
    assert "Photosynthesis" in slides[0]["content"]
