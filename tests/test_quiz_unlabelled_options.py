"""
Nightly debug run: the web quiz, /api/view/quiz and the shared page score a
pick by option[0] == answer. When the model sent options without a letter
label (["Paris", "London"], answer "Paris"), option[0] was "P" and the answer
"Paris": the right option was never highlighted and every pick scored wrong
(and "Paris" / "Prague" shared the same "letter"). Unlabelled options now get
A. / B. / … labels (أ. / ب. / … for Arabic options), and the answer becomes the
label of the option it names.
"""
import app as appmod


def _check(m):
    # the web quiz's own check finds exactly one correct option
    assert sum(o[0] == m["answer"] for o in m["options"]) == 1


def test_unlabelled_options_get_labels_and_answer_letter(monkeypatch):
    monkeypatch.setattr(appmod, "_call_ollama", lambda *a, **k: {"mcqs": [
        {"q": "Capital of France?", "options": ["Prague", "Paris", "London"], "answer": "paris"},
        {"q": "Q?", "options": ["one", "two", "three", "four"], "answer": "C"},
        {"q": "Q?", "options": ["one", "two"], "answer": "nothing"},
    ]})
    mcqs = appmod.pass4_mcq({"title": "T", "sections": []}, "en")["mcqs"]
    assert mcqs[0]["options"] == ["A. Prague", "B. Paris", "C. London"]
    assert mcqs[0]["answer"] == "B"
    _check(mcqs[0])
    assert mcqs[1]["answer"] == "C"
    _check(mcqs[1])
    assert mcqs[2]["options"] == ["A. one", "B. two"]
    assert mcqs[2]["answer"] == "nothing"     # names no option: kept as text


def test_unlabelled_arabic_options_get_arabic_labels():
    out = appmod._text_mcqs([{"q": "س؟", "options": ["باريس", "لندن"], "answer": "لندن"}])
    assert out[0]["options"] == ["أ. باريس", "ب. لندن"]
    assert out[0]["answer"] == "ب"
    _check(out[0])


def test_labelled_options_unchanged():
    opts = ["A. one", "B. two"]
    out = appmod._text_mcqs([{"q": "Q?", "options": list(opts), "answer": "B"},
                             {"q": "س؟", "options": ["أ. واحد", "ب. اثنان"], "answer": "ب"}])
    assert out[0]["options"] == opts and out[0]["answer"] == "B"
    assert out[1]["options"] == ["أ. واحد", "ب. اثنان"] and out[1]["answer"] == "ب"
