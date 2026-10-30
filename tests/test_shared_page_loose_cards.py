"""
Nightly debug run: a guide shared before cards and quiz fields were made text
(2026-10-25) can still hold a list or an object as a flash card answer, a quiz
option or an explanation in its shared_guides row. The public /s/<slug> page
str()'d them, so visitors saw Python reprs like "['Plan', 'Lead']" or
"{'text': 'Paris'}". The page now reads cards and quiz through the same
_text_cards / _text_mcqs as a fresh guide; the stored row is not touched.
"""
import app as appmod


def _page(guide):
    return appmod._render_shared_guide({"slug": "abcdefgh", "language": "en",
                                        "guide": {"title": "T", "language": "en", **guide}})


def test_list_and_object_card_fields_render_as_text():
    html = _page({"flashcards": [{"q": {"text": "Steps?"}, "a": ["Plan", "Lead"]}]})
    assert "Plan; Lead" in html and "Steps?" in html
    assert "[&#39;" not in html and "{&#39;" not in html


def test_object_options_and_list_explanation_render_as_text():
    html = _page({"mcqs": [{"q": "Capital?", "options": [{"text": "A. Paris"}, {"text": "B. Rome"}],
                            "answer": "a", "explanation": ["It is", "in France"]}]})
    assert "A. Paris" in html and "It is; in France" in html
    assert "{&#39;" not in html and "[&#39;" not in html
    assert '<li class="opt correct">✓ A. Paris</li>' in html


def test_question_answer_card_keys_still_render():
    html = _page({"flashcards": [{"question": "Why?", "answer": "Because"}]})
    assert "Why?" in html and "Because" in html
