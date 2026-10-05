"""
Nightly debug run: one loose keyword or section in the pass-1 overview (a keyword
without "term", a numeric term, a section with a null/missing title) made
pass3_flashcards and pass4_mcq raise KeyError/TypeError while building their
prompt. Both errors were swallowed, so the paid guide was delivered with no
flash cards and no quiz (and no refund). Bad entries are now skipped.
"""
import io
import json

import pytest

import app as appmod

TXT = b"Inflation rose from 2019 to 2020. " * 40


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(appmod, "_consume_token", lambda uid: (True, 5, ""))
    monkeypatch.setattr(appmod, "_refund_token", lambda uid: True)
    monkeypatch.setattr(appmod, "ollama_running", lambda: True)
    monkeypatch.setattr(appmod, "_log_usage_async", lambda *a, **k: None)
    appmod.app.config["TESTING"] = True
    return appmod.app.test_client()


def _fake_llm(monkeypatch, overview):
    def call(prompt, retries=3, num_predict=4096):
        if "Create a study guide overview" in prompt:
            return json.loads(json.dumps(overview))
        if "Extract detailed exam study notes" in prompt:
            return {"bullets": ["Fact one", "Fact two"]}
        if "flash cards" in prompt:
            return {"flashcards": [{"q": "Q", "a": "A"}]}
        return {"mcqs": [{"q": "Q", "options": ["A) x", "B) y"], "answer": "A", "explanation": "e"}]}

    monkeypatch.setattr(appmod, "_call_ollama", call)


@pytest.mark.parametrize("overview", [
    {"title": "T", "sections": [{"title": "A", "slide_nums": [1]}],
     "keywords": [{"name": "t", "definition": "d"}]},
    {"title": "T", "sections": [{"title": "A", "slide_nums": [1]}],
     "keywords": [{"term": 5, "definition": "d"}]},
    {"title": "T", "sections": [{"title": None, "slide_nums": [1]}]},
    {"title": "T", "sections": [{"name": "A", "slide_nums": [1]}]},
    {"title": "T", "sections": [{"title": "A", "slide_nums": [1]}], "keywords": None},
])
def test_loose_overview_keeps_cards_and_quiz(client, monkeypatch, overview):
    _fake_llm(monkeypatch, overview)
    resp = client.post("/api/summarize-stream", data={
        "file": (io.BytesIO(TXT), "lecture.txt"), "language": "en"},
        content_type="multipart/form-data")
    ev = [json.loads(l[6:]) for l in resp.get_data(as_text=True).splitlines()
          if l.startswith("data: ")]
    assert ev[-1].get("step") == "done", ev[-1]
    g = client.get(f"/api/guide/{ev[-1]['job_id']}").get_json()
    assert g["flashcards"], "flash cards were dropped"
    assert g["mcqs"], "quiz was dropped"
