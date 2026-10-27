"""
Nightly debug run: a guide the browser signed before flash card / quiz fields
were made text (2026-10-25) can still hold a list or an object as a card's
answer or a quiz option. POST /api/rehydrate rebuilt it as-is, so the restored
PDF and Markdown printed Python reprs like "['Plan', 'Lead']" and /api/guide
served the raw object back to the web app. A restored guide's cards and quiz
are now text, the same as a freshly generated one.
"""
import io

import pypdf

import app as appmod

KEY = b"k" * 32

OLD_GUIDE = {
    "title": "Cells", "subtitle": "",
    "sections": [{"title": "ATP", "bullets": ["Mitochondria make ATP."]}],
    "flashcards": [
        {"q": "Duties of the PM?", "a": ["Plan", "Lead"]},
        {"q": {"text": "What is ATP?"}, "a": {"answer": "The energy carrier"}},
    ],
    "mcqs": [{"q": "Which organelle makes ATP?",
              "options": [{"text": "A. Mitochondria"}, "B. Nucleus"],
              "answer": "A", "explanation": ["Mitochondria", "make ATP"]}],
    "keywords": [], "objectives": [], "language": "en",
}


def test_rehydrated_old_guide_has_text_cards_and_quiz(monkeypatch):
    monkeypatch.setattr(appmod, "_GUIDE_KEY", KEY)
    client = appmod.app.test_client()
    blob = appmod._guide_blob(OLD_GUIDE, "cells.pdf")
    r = client.post("/api/rehydrate", json={"guide_blob": blob, "sig": appmod._guide_sig(blob)})
    assert r.status_code == 200, r.get_json()
    job_id = r.get_json()["job_id"]

    g = client.get(f"/api/guide/{job_id}").get_json()
    assert g["flashcards"] == [{"q": "Duties of the PM?", "a": "Plan; Lead"},
                               {"q": "What is ATP?", "a": "The energy carrier"}]
    assert g["mcqs"][0]["options"] == ["A. Mitochondria", "B. Nucleus"]
    assert g["mcqs"][0]["explanation"] == "Mitochondria; make ATP"

    md = appmod.get_job(job_id)["md"]
    pdf = client.get(f"/api/download/{job_id}").data
    text = "".join(p.extract_text() for p in pypdf.PdfReader(io.BytesIO(pdf)).pages)
    for out in (md, text):
        assert "['" not in out and "{'" not in out
        assert "Plan; Lead" in out
