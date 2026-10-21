"""
Nightly debug run: a chat question that failed inside the server (an AI error
or timeout) answered "Processing failed — please try again." in English, and
the client shows that text as sent, so an Arabic visitor asking about an
Arabic guide got English. The failure text now follows the chat's language
(the request's en/ar, else the guide's own). English is unchanged.
"""
import uuid

import pytest

import app as appmod


def _has_arabic(s):
    return any("؀" <= ch <= "ۿ" for ch in s or "")


def _store(language):
    jid = uuid.uuid4().hex
    appmod.store_job(jid, b"%PDF-1.4 t", "# T\n", {"title": "T", "language": language,
                     "sections": [{"title": "S", "bullets": ["fact one"]}]}, None, "g_study_guide.pdf")
    return jid


@pytest.fixture
def ai_down(monkeypatch):
    monkeypatch.setattr(appmod, "_rate_limit", {})
    monkeypatch.setattr(appmod, "_call_ollama",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("groq down")))


@pytest.mark.parametrize("guide_lang,req_lang", [("ar", "ar"), ("ar", "auto"), ("en", "ar")])
def test_failed_chat_answers_arabic_in_arabic(ai_down, guide_lang, req_lang):
    r = appmod.app.test_client().post(f"/api/chat/{_store(guide_lang)}",
                                      json={"question": "ما هو؟", "language": req_lang})
    assert r.status_code == 500
    err = r.get_json()["error"]
    assert _has_arabic(err) and "groq" not in err


@pytest.mark.parametrize("guide_lang,req_lang", [("en", "en"), ("en", "auto"), ("ar", "en")])
def test_failed_chat_answers_english_as_before(ai_down, guide_lang, req_lang):
    r = appmod.app.test_client().post(f"/api/chat/{_store(guide_lang)}",
                                      json={"question": "What?", "language": req_lang})
    assert r.status_code == 500
    assert r.get_json()["error"] == "Processing failed — please try again."
