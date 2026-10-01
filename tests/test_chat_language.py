"""
Chat in Auto mode answers in the GUIDE's language (review, 2026-10-01).

After "Auto no longer switches the site language" (test_auto_language.py), chat
in Auto took its language from cur.guide?.language and otherwise fell back to the
UI (browser) language. cur.guide is only filled by a background GET /api/guide
that swallows its errors, so when that fetch failed an Arabic guide on an English
browser was answered "in English" - and the server could not correct it, because
/api/chat mapped anything but "ar" to English.

Now, in Auto, the client sends the guide's language when it has the guide and
'auto' otherwise (never the UI language), and /api/chat resolves 'auto' (or no
language) from the stored guide itself. An explicit en/ar choice still wins.

Offline: the LLM is faked; the frontend checks are static (no JS runner).
"""
import os
import re

import pytest

import app as appmod

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_JSX = os.path.join(ROOT, "frontend", "src", "App_dev.jsx")


@pytest.fixture
def client():
    appmod.app.config["TESTING"] = True
    return appmod.app.test_client()


@pytest.fixture
def prompts(monkeypatch):
    seen = []

    def call(prompt, retries=3, num_predict=4096):
        seen.append(prompt)
        return {"answer": "ok"}
    monkeypatch.setattr(appmod, "_call_ollama", call)
    return seen


def _store(language):
    jid = appmod.uuid.uuid4().hex
    guide = {"title": "الخلية", "sections": [{"title": "قسم", "bullets": ["نص"]}]}
    if language is not None:
        guide["language"] = language
    appmod.store_job(jid, b"%PDF-1.4 test", "# T\n", guide, None, "x_study_guide.pdf")
    return jid


def _asked_in(prompt):
    m = re.search(r"Answer this question (in \w+)", prompt)
    assert m, prompt[:200]
    return m.group(1)


# ── server: 'auto' (or no language) follows the stored guide ──────────────────
@pytest.mark.parametrize("body_lang", ["auto", None, "", "fr", 5])
def test_auto_chat_on_an_arabic_guide_answers_in_arabic(client, prompts, body_lang):
    jid = _store("ar")
    body = {"question": "ما وظيفة النواة؟"}
    if body_lang is not None:
        body["language"] = body_lang
    r = client.post(f"/api/chat/{jid}", json=body, headers={"Accept-Language": "en-US,en;q=0.9"})
    assert r.status_code == 200, r.get_data(as_text=True)[:300]
    assert _asked_in(prompts[-1]) == "in Arabic"


@pytest.mark.parametrize("guide_lang", ["en", None, "xx"])
def test_auto_chat_on_an_english_guide_answers_in_english(client, prompts, guide_lang):
    jid = _store(guide_lang)
    r = client.post(f"/api/chat/{jid}", json={"question": "What is it?", "language": "auto"},
                    headers={"Accept-Language": "ar-AE,ar;q=0.9"})
    assert r.status_code == 200
    assert _asked_in(prompts[-1]) == "in English"


@pytest.mark.parametrize("guide_lang,choice", [("ar", "en"), ("en", "ar"), (None, "ar")])
def test_an_explicit_language_choice_still_wins(client, prompts, guide_lang, choice):
    jid = _store(guide_lang)
    r = client.post(f"/api/chat/{jid}", json={"question": "q?", "language": choice})
    assert r.status_code == 200
    assert _asked_in(prompts[-1]) == ("in Arabic" if choice == "ar" else "in English")


# ── client: Auto never substitutes the UI language for the guide's ────────────
def _ask_guide_body():
    src = open(APP_JSX, encoding="utf-8").read()
    m = re.search(r"const askGuide = async \(id, q\) => \{", src)
    assert m, "askGuide not found"
    end = src.index("\n  }\n", m.end())
    return src[m.start():end]


def test_auto_chat_never_falls_back_to_the_ui_language():
    body = _ask_guide_body()
    m = re.search(r"const language = (.+)", body)
    assert m, body[:400]
    expr = m.group(1)
    assert "uiLang" not in expr, f"Auto chat must not use the UI language: {expr}"
    assert "lang === 'auto'" in expr and "cur.guide?.language" in expr and "'auto'" in expr.split("||")[-1]


def test_served_bundle_sends_auto_not_the_ui_language():
    dist = os.path.join(ROOT, "dist")
    html = open(os.path.join(dist, "index.html"), encoding="utf-8").read()
    refs = re.findall(r'src="/?(assets/index-[\w-]+\.js)"', html)
    assert len(refs) == 1, refs
    js = open(os.path.join(dist, *refs[0].split("/")), encoding="utf-8").read()
    i = js.index("/api/chat/")
    window = js[max(0, i - 300):i]
    # minified: const X = lang==="auto" ? (cur.guide?.language) || "auto" : lang
    assert re.search(r'==="auto"\?\(.{0,60}\.language\)\|\|"auto":', window), \
        f"{refs[0]} still falls back to a variable (the UI language): ...{window[-200:]}"
