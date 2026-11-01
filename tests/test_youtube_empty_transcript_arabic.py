"""
Nightly debug run: a YouTube video with no captions whose audio transcribes to
nothing (music, silence) reached the text pipeline with an empty transcript and
ended with the error "No content extracted" — in English, even for an Arabic
visitor. It now follows the request's language; English requests get exactly
the same text as before.
"""
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
                out.append(ev)
    return out


def _no_captions(vid):
    raise ValueError("no_captions")


@pytest.mark.parametrize("lang,arabic", [("ar", True), ("en", False)])
def test_empty_transcript_error_in_request_language(monkeypatch, lang, arabic):
    monkeypatch.setattr(appmod, "ollama_running", lambda: True)
    monkeypatch.setattr(appmod, "_yt_duration", lambda vid: 600)
    monkeypatch.setattr(appmod, "_fetch_captions", _no_captions)
    monkeypatch.setattr(appmod, "GROQ_API_KEY", "test-key")
    monkeypatch.setattr(appmod, "_transcribe_with_whisper", lambda vid: "")
    r = appmod.app.test_client().post(
        "/api/youtube",
        json={"url": "https://youtu.be/dQw4w9WgXcQ", "language": lang},
        headers={"X-Device-Id": "dev-yt-empty-%s" % lang})
    assert r.status_code == 200, r.get_data(as_text=True)
    errs = _errors(r)
    assert errs, r.get_data(as_text=True)
    msg = errs[-1]["error"]
    assert _has_arabic(msg) is arabic, msg
    if not arabic:
        assert msg == "No content extracted"
