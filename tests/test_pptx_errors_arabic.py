"""
Nightly debug run: two .pptx upload failures answered an Arabic visitor in English,
because their texts were missing from _GEN_ERR_AR (the app shows an un-coded
server error as the server wrote it):
- a deck with more than _MAX_PAGES slides: "Presentation has too many slides (max 1200)."
- a deck read through the raw-XML fallback with no text on any slide:
  "No readable content found in this file"
They now follow the request's language; English requests get the same text as before.
"""
import io
import json
import zipfile

import pytest

import app as appmod


def _has_arabic(s):
    return any("؀" <= ch <= "ۿ" for ch in s or "")


def _zip(files):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        for n, c in files.items():
            z.writestr(n, c)
    return b.getvalue()


def _too_many_slides():
    from pptx import Presentation
    prs = Presentation()
    layout = prs.slide_layouts[6]
    for _ in range(appmod._MAX_PAGES + 1):
        prs.slides.add_slide(layout)
    b = io.BytesIO()
    prs.save(b)
    return b.getvalue()


# No officeDocument relationship → python-pptx fails → raw-XML fallback, no text.
_NO_TEXT_FALLBACK = _zip({
    "[Content_Types].xml": '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
    "_rels/.rels": '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>',
    "ppt/slides/slide1.xml": "<p/>",
})

_EN = {
    "too_many": f"Presentation has too many slides (max {appmod._MAX_PAGES}).",
    "no_text": "No readable content found in this file",
}


@pytest.fixture(scope="module")
def decks():
    return {"too_many": _too_many_slides(), "no_text": _NO_TEXT_FALLBACK}


def _errors(resp):
    out = []
    for line in resp.get_data(as_text=True).splitlines():
        if line.startswith("data:"):
            evt = json.loads(line[5:].strip())
            if "error" in evt:
                out.append(evt["error"])
    return out


@pytest.mark.parametrize("case", sorted(_EN))
@pytest.mark.parametrize("lang,arabic", [("ar", True), ("en", False)])
def test_pptx_upload_error_in_request_language(monkeypatch, decks, case, lang, arabic):
    monkeypatch.setattr(appmod, "ollama_running", lambda: True)
    monkeypatch.setattr(appmod, "FREE_MODE", True)
    client = appmod.app.test_client()
    resp = client.post("/api/summarize-stream",
                       data={"file": (io.BytesIO(decks[case]), "lecture.pptx"), "language": lang},
                       content_type="multipart/form-data",
                       headers={"X-Device-Id": "dev-pptx-err-%s-%s" % (case, lang)})
    assert resp.status_code == 200
    errs = _errors(resp)
    assert len(errs) == 1, errs
    assert _has_arabic(errs[0]) is arabic, errs[0]
    if not arabic:
        assert errs[0] == _EN[case]
