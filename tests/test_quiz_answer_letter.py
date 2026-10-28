"""
Nightly debug run: the web quiz and the /api/view/quiz page mark an option
correct only when its first character equals the question's `answer`
(letter === q.answer). The prompt asks for "just the letter", but the model's
answer was kept as sent, so an answer like "a", "B)", "C. option three" or
["D"] never matched: every pick was scored wrong, and Markdown printed
"['D']". A quiz answer is now the label letter of the option it names; an
answer that names no option is left as it was.
"""
import app as appmod

OPTS = ["A. one", "B. two", "C. three", "D. four"]


def _mcqs(monkeypatch, answers):
    monkeypatch.setattr(appmod, "_call_ollama", lambda *a, **k: {"mcqs": [
        {"q": f"Q{i}?", "options": list(OPTS), "answer": ans, "explanation": "e"}
        for i, ans in enumerate(answers)]})
    return appmod.pass4_mcq({"title": "T", "sections": []}, "en")["mcqs"]


def test_quiz_answer_is_the_option_letter(monkeypatch):
    mcqs = _mcqs(monkeypatch, ["A", "a", "B)", "C. three", "three", ["D"], " b "])
    assert [m["answer"] for m in mcqs] == ["A", "A", "B", "C", "C", "D", "B"]
    for m in mcqs:   # the web quiz's own check finds exactly one correct option
        assert sum(o[0] == m["answer"] for o in m["options"]) == 1


def test_arabic_letters_and_unmatched_answers_unchanged(monkeypatch):
    monkeypatch.setattr(appmod, "_call_ollama", lambda *a, **k: {"mcqs": [
        {"q": "س؟", "options": ["أ. واحد", "ب. اثنان"], "answer": "ب"},
        {"q": "Q?", "options": ["Paris", "London"], "answer": "Paris"},
        {"q": "Q?", "options": list(OPTS), "answer": "E"},
        {"q": "Q?", "options": list(OPTS)},
    ]})
    mcqs = appmod.pass4_mcq({"title": "T", "sections": []}, "ar")["mcqs"]
    assert mcqs[0]["answer"] == "ب"
    assert mcqs[1]["answer"] == "Paris"      # unlabelled options: keep the text
    assert mcqs[2]["answer"] == "E"
    assert "answer" not in mcqs[3]


def test_rehydrated_quiz_answer_is_the_option_letter():
    out = appmod._text_mcqs([{"q": "Q?", "options": list(OPTS), "answer": "c)"}])
    assert out[0]["answer"] == "C"
