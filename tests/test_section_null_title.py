"""
A section whose title the model sent as JSON null (or a non-text value) no
longer shows as "Section 1/2: None…" in the progress line, and is not sent to
the model as the section "None" (nightly 2026-11-07).

_sections_parallel used sec.get('title', '') for the progress message and the
pass-2 prompt: a null title became the text "None" (a dict its Python repr).
A text or number title is unchanged.

Offline: the LLM is faked and records the pass-2 prompts.
"""
import json

import app as appmod


def _run(monkeypatch, titles):
    prompts = []

    def call(prompt, retries=3, num_predict=4096):
        if "Create a study guide overview" in prompt:
            return {"title": "T", "sections": [
                {"title": t, "slide_nums": [i + 1]} for i, t in enumerate(titles)]}
        if "Extract detailed exam study notes" in prompt:
            prompts.append(prompt)
            return {"bullets": [f"Fact {len(prompts)}"]}
        return {"flashcards": [{"q": "Q", "a": "A"}],
                "mcqs": [{"q": "Q", "options": ["A) x", "B) y"], "answer": "A"}]}

    monkeypatch.setattr(appmod, "_call_ollama", call)
    monkeypatch.setattr(appmod, "ollama_running", lambda: True)
    monkeypatch.setattr(appmod, "_log_usage_async", lambda *a, **k: None)
    appmod.app.config["TESTING"] = True
    c = appmod.app.test_client()
    text = " ".join(f"Topic{i} " + ("word " * 99) for i in range(1, 7))
    r = c.post("/api/summarize-text", json={"text": text, "language": "en"})
    ev = [json.loads(l[6:]) for l in r.get_data(as_text=True).splitlines()
          if l.startswith("data: ")]
    assert ev[-1].get("step") == "done", ev[-1]
    msgs = [e.get("msg", "") for e in ev if e.get("step") == "section"]
    return msgs, prompts


def test_null_and_dict_titles_never_show_as_none(monkeypatch):
    msgs, prompts = _run(monkeypatch, [None, {"x": 1}, "Beta"])
    joined = " ".join(msgs)
    assert "None" not in joined and "{" not in joined, msgs
    assert "Section 1/3: …" in msgs and "Section 3/3: Beta…" in msgs, msgs
    assert not any('section "None"' in p or "{'x'" in p for p in prompts), prompts
    assert any('section "Beta"' in p for p in prompts)


def test_number_title_kept(monkeypatch):
    msgs, prompts = _run(monkeypatch, [2024, "Beta"])
    assert "Section 1/2: 2024…" in msgs, msgs
    assert any('section "2024"' in p for p in prompts)
