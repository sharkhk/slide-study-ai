"""
Guard: ordinary-but-loose LLM JSON shapes must not throw away a finished guide.
Numeric table headers (years), a null title, or slide_nums that is a bare int /
null / nested list used to raise after every LLM pass had run, so the student got
"Processing failed" (credit refunded, guide lost). A string "bullets" field was
split into one bullet per character.
"""
import io
import json

import pytest

import app as appmod

TXT = b"Inflation rose from 2019 to 2020. " * 40


@pytest.fixture
def client(monkeypatch):
    led = {"consumed": 0, "refunded": 0}

    def consume(uid):
        led["consumed"] += 1
        return True, 5, ""

    def refund(uid):
        led["refunded"] += 1
        return True

    monkeypatch.setattr(appmod, "_consume_token", consume)
    monkeypatch.setattr(appmod, "_refund_token", refund)
    monkeypatch.setattr(appmod, "ollama_running", lambda: True)
    monkeypatch.setattr(appmod, "_log_usage_async", lambda *a, **k: None)
    appmod.app.config["TESTING"] = True
    c = appmod.app.test_client()
    c.ledger = led
    return c


def _fake_llm(monkeypatch, overview=None, section=None):
    ov = overview or {"title": "Topic", "subtitle": "s", "objectives": ["o"],
                      "sections": [{"title": "A", "slide_nums": [1]}],
                      "keywords": [{"term": "t", "definition": "d"}]}
    sec = section or {"bullets": ["Fact one", "Fact two"]}

    def call(prompt, retries=3, num_predict=4096):
        if "Create a study guide overview" in prompt:
            return json.loads(json.dumps(ov))
        if "Extract detailed exam study notes" in prompt:
            return json.loads(json.dumps(sec))
        return {"flashcards": [{"q": "Q", "a": "A"}],
                "mcqs": [{"q": "Q", "options": ["A) x", "B) y"], "answer": "A", "explanation": "e"}]}

    monkeypatch.setattr(appmod, "_call_ollama", call)


def _run(client):
    resp = client.post("/api/summarize-stream", data={
        "file": (io.BytesIO(TXT), "lecture.txt"), "language": "en"},
        content_type="multipart/form-data")
    return [json.loads(l[6:]) for l in resp.get_data(as_text=True).splitlines()
            if l.startswith("data: ")]


def test_numeric_table_headers(client, monkeypatch):
    _fake_llm(monkeypatch, section={"bullets": ["CPI rose"],
              "table": {"headers": ["Metric", 2019, 2020], "rows": [["CPI", 1.8, 1.2]]}})
    ev = _run(client)
    assert ev[-1].get("step") == "done", ev[-1]
    assert client.ledger["refunded"] == 0


def test_null_title(client, monkeypatch):
    _fake_llm(monkeypatch, overview={"title": None, "sections": [{"title": "A", "slide_nums": [1]}]})
    ev = _run(client)
    assert ev[-1].get("step") == "done", ev[-1]


@pytest.mark.parametrize("nums", [1, None, [[1, 2]], "1"])
def test_loose_slide_nums(client, monkeypatch, nums):
    _fake_llm(monkeypatch, overview={"title": "T", "sections": [{"title": "A", "slide_nums": nums}]})
    ev = _run(client)
    assert ev[-1].get("step") == "done", ev[-1]


def test_string_bullets_stay_one_bullet(client, monkeypatch):
    _fake_llm(monkeypatch, section={"bullets": "Water is split in the thylakoid."})
    ev = _run(client)
    assert ev[-1].get("step") == "done", ev[-1]
    g = client.get(f"/api/guide/{ev[-1]['job_id']}").get_json()
    assert g["sections"][0]["bullets"] == ["Water is split in the thylakoid."]
