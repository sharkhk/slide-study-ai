"""
A chat reply without an "answer" key answers Arabic visitors in Arabic (nightly
2026-11-06).

When the model's JSON had no "answer" key (e.g. {"response": ...}, {} or a list
of strings), /api/chat answered "No answer found in the material." - in English
even when the question was asked in Arabic (explicitly, or 'auto' on an Arabic
guide). The default now follows the chat language; English is unchanged.

Offline: the LLM is faked.
"""
import re

import pytest

import app as appmod

_AR = re.compile(r"[؀-ۿ]")


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(appmod, "_call_ollama",
                        lambda prompt, retries=3, num_predict=4096: {"response": "x"})
    appmod.app.config["TESTING"] = True
    return appmod.app.test_client()


def _store(language):
    jid = appmod.uuid.uuid4().hex
    guide = {"title": "T", "language": language,
             "sections": [{"title": "S", "bullets": ["b"]}]}
    appmod.store_job(jid, b"%PDF-1.4 test", "# T\n", guide, None, "x_study_guide.pdf")
    return jid


@pytest.mark.parametrize("guide_lang,req_lang", [("en", "ar"), ("ar", "auto"), ("ar", None)])
def test_missing_answer_key_is_arabic_for_arabic_chat(client, guide_lang, req_lang):
    body = {"question": "لماذا؟"}
    if req_lang is not None:
        body["language"] = req_lang
    r = client.post(f"/api/chat/{_store(guide_lang)}", json=body)
    assert r.status_code == 200, r.get_data(as_text=True)[:300]
    ans = r.get_json()["answer"]
    assert ans and _AR.search(ans), ans
    assert "No answer found" not in ans


@pytest.mark.parametrize("guide_lang,req_lang", [("en", "en"), ("en", "auto"), ("ar", "en")])
def test_missing_answer_key_stays_english_for_english_chat(client, guide_lang, req_lang):
    r = client.post(f"/api/chat/{_store(guide_lang)}",
                    json={"question": "why?", "language": req_lang})
    assert r.status_code == 200
    assert r.get_json()["answer"] == "No answer found in the material."
