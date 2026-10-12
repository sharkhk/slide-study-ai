"""
Nightly debug run: two everyday generation failures answered an Arabic visitor in
English, because the app shows an un-coded server error as the server wrote it:
- a file with no readable text (e.g. a scanned PDF): "No readable content in this file"
- a YouTube video over 50 minutes: "This video is too long. ..."
They now follow the request's language (_wants_ar), like the busy / bad-URL texts.
English requests get the same English text as before.
"""
import io
import json

import pytest

import app as appmod


def _has_arabic(s):
    return any("؀" <= ch <= "ۿ" for ch in s or "")


def _sse_events(resp):
    out = []
    for line in resp.get_data(as_text=True).splitlines():
        if line.startswith("data:"):
            out.append(json.loads(line[5:].strip()))
    return out


def _post_empty_file(lang):
    client = appmod.app.test_client()
    return client.post("/api/summarize-stream",
                       data={"file": (io.BytesIO(b"   \n  "), "scan.txt"), "language": lang},
                       content_type="multipart/form-data",
                       headers={"X-Device-Id": "dev-arabic-errors-%s" % lang})


@pytest.mark.parametrize("lang,arabic", [("ar", True), ("en", False)])
def test_unreadable_file_error_in_request_language(monkeypatch, lang, arabic):
    monkeypatch.setattr(appmod, "ollama_running", lambda: True)
    monkeypatch.setattr(appmod, "extract_slides", lambda *a, **k: [{"slide_num": 1, "title": "", "content": ""}])
    r = _post_empty_file(lang)
    assert r.status_code == 200, r.get_data(as_text=True)
    errs = [e for e in _sse_events(r) if e.get("error")]
    assert errs, "expected an error event"
    assert _has_arabic(errs[-1]["error"]) is arabic, errs[-1]
    if not arabic:
        assert errs[-1]["error"] == "No readable content in this file"


@pytest.mark.parametrize("lang,arabic", [("ar", True), ("en", False)])
def test_too_long_video_error_in_request_language(monkeypatch, lang, arabic):
    monkeypatch.setattr(appmod, "ollama_running", lambda: True)
    monkeypatch.setattr(appmod, "_yt_duration", lambda vid: 3600)
    r = appmod.app.test_client().post("/api/youtube",
                                      json={"url": "https://youtu.be/dQw4w9WgXcQ", "language": lang})
    assert r.status_code == 400
    body = r.get_json()
    assert _has_arabic(body["error"]) is arabic, body
    if not arabic:
        assert body["error"] == "This video is too long. Maximum supported length is 50 minutes."
