"""
Nightly debug run: when a YouTube video had no captions and the audio
transcription failed (a Whisper/Groq HTTP error, or audio too large), an Arabic
visitor was answered in English: "Processing failed — please try again.",
"Video audio exceeds 20 MB — …". These texts are shown as sent, so they now
follow the request's language. English requests get exactly the same text.
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


def _post(lang):
    return appmod.app.test_client().post(
        "/api/youtube",
        json={"url": "https://youtu.be/dQw4w9WgXcQ", "language": lang},
        headers={"X-Device-Id": "dev-yt-whisper-%s" % lang})


def _no_captions(vid):
    raise ValueError("no_captions")


def _whisper_http_error(vid):
    raise RuntimeError("500 Server Error: Internal Server Error for url: https://api.groq.com/...")


def _whisper_too_large(vid):
    raise ValueError("Video audio exceeds 20 MB — try a shorter video (under ~15 minutes).")


@pytest.mark.parametrize("whisper,en", [
    (_whisper_http_error, "Processing failed — please try again."),
    (_whisper_too_large, "Video audio exceeds 20 MB — try a shorter video (under ~15 minutes)."),
])
@pytest.mark.parametrize("lang,arabic", [("ar", True), ("en", False)])
def test_transcription_failure_in_request_language(monkeypatch, lang, arabic, whisper, en):
    monkeypatch.setattr(appmod, "ollama_running", lambda: True)
    monkeypatch.setattr(appmod, "_yt_duration", lambda vid: 600)
    monkeypatch.setattr(appmod, "_fetch_captions", _no_captions)
    monkeypatch.setattr(appmod, "GROQ_API_KEY", "test-key")
    monkeypatch.setattr(appmod, "_transcribe_with_whisper", whisper)
    r = _post(lang)
    assert r.status_code == 200, r.get_data(as_text=True)
    errs = _errors(r)
    assert errs, r.get_data(as_text=True)
    msg = errs[-1]["error"]
    assert _has_arabic(msg) is arabic, msg
    assert "api.groq.com" not in msg
    if not arabic:
        assert msg == en


def test_every_whisper_message_has_arabic():
    for en in ("Audio download produced no file.",
               "Video audio exceeds 20 MB — try a shorter video (under ~15 minutes).",
               "Audio file too large for Whisper — try a shorter video (under ~15 minutes).",
               "yt-dlp not installed — cannot transcribe audio."):
        assert _has_arabic(appmod._GEN_ERR_AR.get(en)), en
