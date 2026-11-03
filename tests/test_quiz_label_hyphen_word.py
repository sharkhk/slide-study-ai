"""
Nightly debug run: an unlabelled quiz option that is a letter-hyphen word in
its own letter's position ("B-cells" second, "D-glucose" fourth) counted as
that position's label, so the whole question was treated as already labelled
and left as it was: option[0] was "A" / "T" / "B" / ... and the answer the
option's text, so the right option was never scored right. A hyphen joined to
a word is not a label separator; "B - text" / "B- text" still are.
"""
import app as appmod


def _check(m):
    # the web quiz's own check finds exactly one correct option
    assert sum(o[0] == m["answer"] for o in m["options"]) == 1


def test_letter_hyphen_word_in_its_own_position_gets_labels():
    opts = ["T-cells", "B-cells", "Neutrophils", "Platelets"]
    out = appmod._text_mcqs([{"q": "Which make antibodies?", "options": list(opts),
                              "answer": "B-cells"}])
    assert out[0]["options"] == ["A. T-cells", "B. B-cells", "C. Neutrophils", "D. Platelets"]
    assert out[0]["answer"] == "B"
    _check(out[0])


def test_fourth_option_d_glucose_gets_labels():
    opts = ["Sucrose", "Lactose", "Fructose", "D-glucose"]
    out = appmod._text_mcqs([{"q": "Blood sugar?", "options": list(opts), "answer": "D-glucose"}])
    assert out[0]["options"] == ["A. Sucrose", "B. Lactose", "C. Fructose", "D. D-glucose"]
    assert out[0]["answer"] == "D"
    _check(out[0])


def test_partly_labelled_with_spaced_hyphen_unchanged():
    for opts, ans in ((["A - one", "two"], "A"), (["A- one", "two"], "A"),
                      (["A. one", "two"], "A"), (["A-B", "B-C"], "A")):
        out = appmod._text_mcqs([{"q": "Q?", "options": list(opts), "answer": ans}])
        assert out[0]["options"] == opts
