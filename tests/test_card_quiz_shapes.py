"""
Nightly debug run: the model sometimes answers a flash card or quiz field as a
list or an object instead of a string (e.g. "What are the responsibilities of
the PM?" -> "a": ["Plan", "Lead"]). The guide kept it raw, so the PDF, Markdown,
Anki CSV and shared page printed Python reprs like "['Plan', 'Lead']", and the
web app joined a list without spaces or crashed on an object. Such a field is
now its text.
"""
import app as appmod


def test_flashcard_fields_become_text(monkeypatch):
    monkeypatch.setattr(appmod, "_call_ollama", lambda *a, **k: {"flashcards": [
        {"q": "Duties of the PM?", "a": ["Plan", "Lead"]},
        {"q": {"text": "What is ATP?"}, "a": {"answer": "The cell's energy carrier"}},
        {"q": "Year of the treaty?", "a": 1648},
        {"q": "Plain?", "a": "Plain answer"},
        {"q": None, "a": None},
    ]})
    cards = appmod.pass3_flashcards({"title": "T", "sections": []}, "en")["flashcards"]
    assert cards == [
        {"q": "Duties of the PM?", "a": "Plan; Lead"},
        {"q": "What is ATP?", "a": "The cell's energy carrier"},
        {"q": "Year of the treaty?", "a": "1648"},
        {"q": "Plain?", "a": "Plain answer"},
    ]


def test_quiz_fields_become_text(monkeypatch):
    monkeypatch.setattr(appmod, "_call_ollama", lambda *a, **k: {"mcqs": [
        {"q": {"text": "Which organelle makes ATP?"},
         "options": [{"text": "A. Mitochondria"}, "B. Nucleus", 3, None],
         "answer": "A", "explanation": ["Mitochondria", "make ATP"]},
        {"q": "Plain?", "options": ["A. x", "B. y"], "answer": "B", "explanation": "Because"},
    ]})
    mcqs = appmod.pass4_mcq({"title": "T", "sections": []}, "en")["mcqs"]
    assert mcqs[0] == {"q": "Which organelle makes ATP?",
                       "options": ["A. Mitochondria", "B. Nucleus", "3"],
                       "answer": "A", "explanation": "Mitochondria; make ATP"}
    assert mcqs[1] == {"q": "Plain?", "options": ["A. x", "B. y"], "answer": "B",
                       "explanation": "Because"}


def test_question_answer_keys_are_kept(monkeypatch):
    monkeypatch.setattr(appmod, "_call_ollama", lambda *a, **k: [
        {"question": "Q?", "answer": ["x", "y"]}, "junk"])
    cards = appmod.pass3_flashcards({"title": "T", "sections": []}, "en")["flashcards"]
    assert cards == [{"question": "Q?", "answer": "x; y", "q": "Q?", "a": "x; y"}]
