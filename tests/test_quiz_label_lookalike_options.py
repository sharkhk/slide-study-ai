"""
Nightly debug run: unlabelled quiz options are labelled A. / B. / ... (see
test_quiz_unlabelled_options.py), but only when NO option looked labelled.
One option such as "U.S.A", "3.14" or "x-axis" matches the label pattern, so
the whole question was left unlabelled: option[0] was "C" / "M" / ... and the
answer the option's text, so the right option was never scored right. Numeric
options like "1.5 m/s" / "1.0 m/s" shared one "letter" ("1"), so both picks
scored right. Such questions now get proper labels too.
"""
import app as appmod


def _check(m):
    # the web quiz's own check finds exactly one correct option
    assert sum(o[0] == m["answer"] for o in m["options"]) == 1


def test_one_lookalike_option_still_gets_labels():
    out = appmod._text_mcqs([{"q": "Which country?", "options": ["Canada", "Mexico", "U.S.A"],
                              "answer": "U.S.A"}])
    assert out[0]["options"] == ["A. Canada", "B. Mexico", "C. U.S.A"]
    assert out[0]["answer"] == "C"
    _check(out[0])


def test_options_sharing_a_first_character_get_labels():
    out = appmod._text_mcqs([{"q": "Speed?", "options": ["1.5 m/s", "1.0 m/s", "2.0 m/s"],
                              "answer": "1.0 m/s"}])
    assert out[0]["options"] == ["A. 1.5 m/s", "B. 1.0 m/s", "C. 2.0 m/s"]
    assert out[0]["answer"] == "B"
    _check(out[0])


def test_properly_labelled_options_unchanged():
    for opts, ans in ((["A. one", "B. two", "C. three"], "B"),
                      (["a) one", "b) two"], "a"),
                      (["A. one", "two"], "A")):       # partly labelled: left as before
        out = appmod._text_mcqs([{"q": "Q?", "options": list(opts), "answer": ans}])
        assert out[0]["options"] == opts
