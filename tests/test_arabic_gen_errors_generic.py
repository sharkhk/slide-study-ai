"""
Nightly debug run: when a generation failed inside the server (an AI error or
timeout) or a file couldn't be read (a scanned PDF, an empty .txt, an unknown
format…), an Arabic visitor was answered in English: "Processing failed —
please try again.", "No readable text found in the PDF — …". These texts are
shown as sent, so they now follow the request's language. English requests get
exactly the same text as before.
"""
import io
import json

import pytest

import app as appmod


def _has_arabic(s):
    return any("؀" <= ch <= "ۿ" for ch in s or "")


def _errors(resp):
    out = []
    for line in resp.get_data(as_text=True).splitlines():
        if line.startswith("data:"):
            ev = json.loads(line[5:].strip())
            if ev.get("error"):
                out.append(ev["error"])
    return out


def _post(lang, data=b"%PDF-1.4\n%%EOF", name="lecture.pdf"):
    return appmod.app.test_client().post(
        "/api/summarize-stream",
        data={"file": (io.BytesIO(data), name), "language": lang},
        content_type="multipart/form-data",
        headers={"X-Device-Id": "dev-generic-errors-%s" % lang})


def _ai_down(*a, **k):
    raise RuntimeError("upstream exploded")


@pytest.mark.parametrize("lang,arabic", [("ar", True), ("en", False)])
def test_internal_failure_in_request_language(monkeypatch, lang, arabic):
    monkeypatch.setattr(appmod, "ollama_running", lambda: True)
    monkeypatch.setattr(appmod, "_call_ollama", _ai_down)
    r = _post(lang, b"Cells divide by mitosis.\n" * 10, "notes.txt")
    errs = _errors(r)
    assert errs, r.get_data(as_text=True)
    assert _has_arabic(errs[-1]) is arabic, errs[-1]
    assert "upstream exploded" not in errs[-1]
    if not arabic:
        assert errs[-1] == "Processing failed — please try again."


@pytest.mark.parametrize("data,name,en", [
    (b"not a document", "lecture.pdf",
     "Unrecognised file format. Supported: .pptx, .ppt, .pdf, .docx, .doc, .txt"),
    (b"\n  \n", "notes.txt", "The text file appears to be empty."),
])
@pytest.mark.parametrize("lang,arabic", [("ar", True), ("en", False)])
def test_unreadable_file_in_request_language(monkeypatch, lang, arabic, data, name, en):
    monkeypatch.setattr(appmod, "ollama_running", lambda: True)
    errs = _errors(_post(lang, data, name))
    assert errs
    assert _has_arabic(errs[-1]) is arabic, errs[-1]
    if not arabic:
        assert errs[-1] == en


def test_every_extraction_message_has_arabic():
    # the file-reading texts a visitor can meet all have an Arabic version
    for en in ("No readable text found in the PDF — it may be a scanned/image-based file.",
               "No readable text found in the Word document.",
               "No readable text found in the binary .ppt file",
               f"PDF has too many pages (max {appmod._MAX_PAGES}).",
               "Processing failed — please try again."):
        ev = appmod._gen_error_event(ValueError(en) if "Processing" not in en else RuntimeError("x"), ar=True)
        assert _has_arabic(ev["error"]), en
        assert appmod._gen_error_event(ValueError(en) if "Processing" not in en else RuntimeError("x"))["error"] == en
