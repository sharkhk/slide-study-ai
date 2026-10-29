"""
Nightly debug run: the model sometimes names a flash card's fields "question" /
"answer" (or a quiz question's "question") instead of "q" / "a". The guide kept
the card, but the web app, Markdown, PDF and Anki CSV read only q / a: the web
flash cards and quiz showed a blank question, the PDF dropped the card and the
Markdown printed an empty "Q1:". Such a field is now also its q / a.
"""
import io

import pypdf

import app as appmod


def _cards(monkeypatch, cards):
    monkeypatch.setattr(appmod, "_call_ollama", lambda *a, **k: {"flashcards": cards})
    return appmod.pass3_flashcards({"title": "T", "sections": []}, "en")["flashcards"]


def test_flashcard_question_answer_keys_become_q_a(monkeypatch):
    cards = _cards(monkeypatch, [
        {"question": "What is ATP?", "answer": "The energy carrier"},
        {"q": "Plain?", "a": "Plain answer"},
        {"q": "", "question": "Fallback?", "a": "Yes"},
    ])
    assert [(c["q"], c["a"]) for c in cards] == [
        ("What is ATP?", "The energy carrier"), ("Plain?", "Plain answer"), ("Fallback?", "Yes")]


def test_quiz_question_key_becomes_q(monkeypatch):
    monkeypatch.setattr(appmod, "_call_ollama", lambda *a, **k: {"mcqs": [
        {"question": "Which organelle makes ATP?", "options": ["A. Mitochondria", "B. Nucleus"],
         "answer": "A", "explanation": "x"}]})
    m = appmod.pass4_mcq({"title": "T", "sections": []}, "en")["mcqs"][0]
    assert m["q"] == "Which organelle makes ATP?"
    assert m["answer"] == "A"


def test_long_key_cards_reach_pdf_and_markdown(monkeypatch):
    monkeypatch.setattr(appmod, "_GUIDE_KEY", b"k" * 32)
    guide = {"title": "Cells", "subtitle": "",
             "sections": [{"title": "ATP", "bullets": ["Mitochondria make ATP."]}],
             "flashcards": [{"question": "What is ATP?", "answer": "The energy carrier"}],
             "mcqs": [{"question": "Which organelle makes ATP?",
                       "options": ["A. Mitochondria", "B. Nucleus"], "answer": "A"}],
             "keywords": [], "objectives": [], "language": "en"}
    client = appmod.app.test_client()
    blob = appmod._guide_blob(guide, "cells.pdf")
    r = client.post("/api/rehydrate", json={"guide_blob": blob, "sig": appmod._guide_sig(blob)})
    assert r.status_code == 200, r.get_json()
    job_id = r.get_json()["job_id"]
    g = client.get(f"/api/guide/{job_id}").get_json()
    assert g["flashcards"][0]["q"] == "What is ATP?"
    assert g["mcqs"][0]["q"] == "Which organelle makes ATP?"
    md = appmod.get_job(job_id)["md"]
    pdf = client.get(f"/api/download/{job_id}").data
    text = "".join(p.extract_text() for p in pypdf.PdfReader(io.BytesIO(pdf)).pages)
    for out in (md, text):
        assert "What is ATP?" in out and "The energy carrier" in out
    assert "Which organelle makes ATP?" in md   # the PDF has no quiz section
