"""
Section slide numbers sent as strings ("3") pick the section's own slides
(nightly 2026-11-06).

_slide_nums kept only ints, so a model reply like {"slide_nums": ["1"]} /
["2", "3", "4", "5", "6"] matched no slide and every section fell back to an
even slice of the material: the first section's notes were written from slides
1-3 (including the second section's content) and the second section never saw
slides 2-3. Digit strings now count as slide numbers; ints, a bare int, null and
nested lists behave as before.

Offline: the LLM is faked and records which slides each section was given.
"""
import json
import re

import pytest

import app as appmod


def test_slide_nums_accepts_digit_strings():
    assert appmod._slide_nums({"slide_nums": ["1", " 2 ", 3]}) == {1, 2, 3}
    assert appmod._slide_nums({"slide_nums": "4"}) == {4}


@pytest.mark.parametrize("raw,expected", [
    ([1, 2], {1, 2}), (5, {5}), (None, set()), ([[1, 2]], set()),
    (["x", "", "1.5", "-2"], set()),
])
def test_slide_nums_other_shapes_unchanged(raw, expected):
    assert appmod._slide_nums({"slide_nums": raw}) == expected


def test_string_slide_nums_route_each_section_its_own_slides(monkeypatch):
    seen = {}

    def call(prompt, retries=3, num_predict=4096):
        if "Create a study guide overview" in prompt:
            return {"title": "T", "sections": [
                {"title": "Alpha", "slide_nums": ["1"]},
                {"title": "Beta", "slide_nums": ["2", "3", "4", "5", "6"]}]}
        if "Extract detailed exam study notes" in prompt:
            title = "Alpha" if '"Alpha"' in prompt else "Beta"
            seen[title] = sorted(int(n) for n in
                                 re.findall(r"^Slide (\d+):", prompt, re.M))
            return {"bullets": [f"Fact about {title}"]}
        return {"flashcards": [{"q": "Q", "a": "A"}],
                "mcqs": [{"q": "Q", "options": ["A) x", "B) y"], "answer": "A"}]}

    monkeypatch.setattr(appmod, "_call_ollama", call)
    monkeypatch.setattr(appmod, "ollama_running", lambda: True)
    monkeypatch.setattr(appmod, "_log_usage_async", lambda *a, **k: None)
    appmod.app.config["TESTING"] = True
    c = appmod.app.test_client()
    text = " ".join(f"Topic{i} " + ("word " * 99) for i in range(1, 7))
    assert len(appmod._text_to_slides(text)) == 6
    r = c.post("/api/summarize-text", json={"text": text, "language": "en"})
    ev = [json.loads(l[6:]) for l in r.get_data(as_text=True).splitlines() if l.startswith("data: ")]
    assert ev[-1].get("step") == "done", ev[-1]
    assert seen == {"Alpha": [1], "Beta": [2, 3, 4, 5, 6]}
