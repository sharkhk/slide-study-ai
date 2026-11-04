"""
Nightly debug run: the model's overview JSON can hold a null (or an empty list)
as an item of "sections" or "keywords" (e.g. a trailing `null`). The generation
pipeline turned each such item into a section titled "None" (or "[]") - which
was sent to the AI for notes and shown in the guide, PDF and Markdown - and a
key term "None". Such items are now skipped; a plain string or number item still
becomes a section / key term as before.
"""
import json

import pytest

import app as appmod

TEXT = "Cells divide by mitosis into two identical daughter cells. " * 20


def _llm(prompt, retries=3, num_predict=4096):
    if "Create a study guide overview" in prompt:
        return {"title": "Cells", "subtitle": "s", "objectives": ["o"],
                "sections": [{"title": "Mitosis", "slide_nums": [1]}, None, [], "Meiosis"],
                "keywords": [{"term": "Spindle", "definition": "d"}, None, [], "Chromatid", 46]}
    if "Extract detailed exam study notes" in prompt:
        title = prompt.split('the section "', 1)[1].split('"', 1)[0]
        return {"bullets": [f"Fact about {title}", "Another fact about " + title]}
    return {"flashcards": [{"q": "Q", "a": "A"}],
            "mcqs": [{"q": "Q", "options": ["A) x", "B) y"], "answer": "A", "explanation": "e"}]}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(appmod, "_client_ip", lambda: "203.0.113.7")
    monkeypatch.setattr(appmod, "_rate_limit", {})
    monkeypatch.setattr(appmod, "_log_usage_async", lambda *a, **k: None)
    monkeypatch.setattr(appmod, "ollama_running", lambda: True)
    monkeypatch.setattr(appmod, "_call_ollama", _llm)
    monkeypatch.setattr(appmod, "_ensure_arabic_font", lambda: False)
    appmod.app.config["TESTING"] = True
    return appmod.app.test_client()


def _generate(client):
    r = client.post("/api/summarize-text", json={"text": TEXT, "language": "en"})
    events = [json.loads(l[len("data: "):]) for l in r.get_data(as_text=True).splitlines()
              if l.startswith("data: ")]
    job_id = next((e["job_id"] for e in events if e.get("job_id")), None)
    assert job_id, events
    return job_id


def test_null_overview_items_do_not_become_none_sections_or_terms(client):
    job_id = _generate(client)
    g = client.get(f"/api/guide/{job_id}").get_json()
    titles = [s.get("title") for s in g["sections"]]
    terms = [k.get("term") for k in g["keywords"]]
    assert titles == ["Mitosis", "Meiosis"], titles
    assert terms == ["Spindle", "Chromatid", "46"], terms
    md = client.get(f"/api/download/{job_id}?format=md").get_data(as_text=True)
    assert "None" not in md and "[]" not in md, md


def test_overview_items_helper_used_by_every_pipeline():
    # The same helper normalises the upload, text/YouTube and legacy pipelines.
    raw = [{"title": "A"}, None, [], {}, "", "  ", "B", 3, True]
    assert appmod._overview_items(raw, "title", {"slide_nums": []}) == [
        {"title": "A"}, {}, {"title": "B", "slide_nums": []}, {"title": "3", "slide_nums": []}]
    assert appmod._overview_items(None, "term", {"definition": ""}) == []
    assert appmod._overview_items("x", "term", {"definition": ""}) == []
