"""
Nightly debug run: build_markdown / build_pdf still crashed at the very end of
generation (after every LLM pass had run) on loose quiz and table shapes, so
the student got "Processing failed" (credit refunded, guide lost):
  - "mcqs": null, or a question whose "options" is null / a number
  - a table whose "headers" or "rows" is a bare number
And "headers": "Role, Duty" (a string) printed one column per character.
"""
import io

from pypdf import PdfReader

import app as appmod


def _guide(**over):
    g = {
        "title": "Cells", "subtitle": "Bio",
        "objectives": ["Know organelles"],
        "sections": [{"title": "Organelles", "slide_nums": [1],
                      "bullets": ["Mitochondria make ATP"]}],
        "keywords": [{"term": "ATP", "definition": "Energy carrier"}],
        "flashcards": [{"q": "What makes ATP?", "a": "Mitochondria"}],
        "mcqs": [{"q": "Powerhouse?", "options": ["A) Mitochondria", "B) Nucleus"],
                  "answer": "A", "explanation": "ATP"}],
    }
    g.update(over)
    return g


def _pdf_text(guide, lang="en"):
    pdf = appmod.build_pdf(guide, lang)
    return "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(pdf.getvalue())).pages)


def _both(guide):
    text = _pdf_text(dict(guide))
    md = appmod.build_markdown(guide)
    return text, md


def test_null_mcqs():
    text, md = _both(_guide(mcqs=None))
    assert "Organelles" in text and "## Organelles" in md


def test_mcq_with_null_or_number_options():
    for bad in (None, 5):
        g = _guide(mcqs=[{"q": "Powerhouse?", "options": bad, "answer": "A"},
                         {"q": "Second?", "options": ["A) x", "B) y"], "answer": "B"}])
        text, md = _both(g)
        assert "Organelles" in text
        assert "**1. Powerhouse?**" in md and "   A) x" in md


def test_table_with_number_headers_or_rows():
    for tbl in ({"headers": 3, "rows": [["a"]]}, {"headers": ["h1", "h2"], "rows": 7}):
        sec = {"title": "Organelles", "slide_nums": [1], "bullets": ["Mitochondria make ATP"],
               "table": tbl}
        text, md = _both(_guide(sections=[sec]))
        assert "Mitochondria make ATP" in text and "- Mitochondria make ATP" in md


def test_string_headers_is_one_column_not_one_per_character():
    sec = {"title": "Organelles", "slide_nums": [1], "bullets": ["b"],
           "table": {"headers": "Role, Duty", "rows": [["Nucleus"]]}}
    text, md = _both(_guide(sections=[sec]))
    assert "Role, Duty" in text and "Nucleus" in text
    assert "| Role, Duty |" in md and "| R | o |" not in md


# End to end: the stream must finish with `done` (no refund) on these shapes.
import json
import pytest
from tests.test_llm_shapes import client, _run  # noqa: F401  (fixture + helper)


@pytest.mark.parametrize("quiz", [
    {"flashcards": [{"q": "Q", "a": "A"}], "mcqs": None},
    {"flashcards": [{"q": "Q", "a": "A"}], "mcqs": [{"q": "Q", "options": None, "answer": "A"}]},
])
def test_stream_finishes_on_loose_mcqs(client, monkeypatch, quiz):  # noqa: F811
    ov = {"title": "Topic", "sections": [{"title": "A", "slide_nums": [1]}],
          "keywords": [{"term": "t", "definition": "d"}]}

    def call(prompt, retries=3, num_predict=4096):
        if "Create a study guide overview" in prompt:
            return json.loads(json.dumps(ov))
        if "Extract detailed exam study notes" in prompt:
            return {"bullets": ["Fact", "Other"],
                    "table": {"headers": 3, "rows": [["a"]]}}
        return json.loads(json.dumps(quiz))

    monkeypatch.setattr(appmod, "_call_ollama", call)
    ev = _run(client)
    assert ev[-1].get("step") == "done", ev[-1]
    assert client.ledger["refunded"] == 0
